"""Tailored application: /apply through Claude, PDFs back to the candidate, Gupy text."""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path

from jobbot import messages
from jobbot.claude import ClaudeRunnerPort
from jobbot.models import JobStatus
from jobbot.prompts import APPLY_NOTE, GUPY_NOTE, GUPY_PROMPT, SUMMARY_END, SUMMARY_START
from jobbot.storage import JobRepository, JsonStore, UserRepository
from jobbot.telegram import Notifier, Telegram

log = logging.getLogger("jobbot")

PDF_DIRS = ("cv", "cover_letters", "documents/applications")
SUMMARY_LIMIT = 900
LOG_OUTPUT_LIMIT = 4000
APPLY_OUTPUT_PREFIX = "apply-saida"
GUPY_LABEL = re.compile(r"^(?:texto|resposta|apresente-se|sobre voc[êe])\s*:\s*", re.IGNORECASE)
QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("'", "'"), ("«", "»"))


def extract_summary(output: str) -> str | None:
    """The candidate-facing summary: the block after the last SUMMARY_START up to the next SUMMARY_END.

    Markdown (``**``, leading ``#``, backticks) is stripped and the text cut at ``SUMMARY_LIMIT``.
    Returns None when there is no block (or it is empty); the raw output is never used.
    """
    start = output.rfind(SUMMARY_START)
    if start < 0:
        return None
    body = output[start + len(SUMMARY_START) :]
    end = body.find(SUMMARY_END)
    if end < 0:
        return None
    text = body[:end].replace("**", "").replace("`", "")
    text = "\n".join(re.sub(r"^\s*#+\s*", "", line).rstrip() for line in text.strip().splitlines())
    text = text.strip()[:SUMMARY_LIMIT].rstrip()
    return text or None


def clean_gupy_text(text: str) -> str:
    """Strip markdown, a leading label such as "Texto:" and wrapping quotes from the Gupy text."""
    text = text.replace("*", "").replace("`", "").strip()
    text = GUPY_LABEL.sub("", text).strip()
    for opening, closing in QUOTE_PAIRS:
        if len(text) > 1 and text.startswith(opening) and text.endswith(closing):
            text = text[1:-1].strip()
            break
    return text


class ApplicationService:
    def __init__(
        self,
        users: UserRepository,
        store: JsonStore,
        claude: ClaudeRunnerPort,
        telegram: Telegram,
        notifier: Notifier,
    ) -> None:
        self._users = users
        self._store = store
        self._claude = claude
        self._telegram = telegram
        self._notifier = notifier

    def apply_job(self, chat: int, job_id: str) -> None:
        jobs = JobRepository(self._store, chat)
        user, job = self._users.get(chat), jobs.get(job_id)
        if user is None or job is None:
            return
        workspace, start, session = user.workspace, time.time() - 1, str(uuid.uuid4())
        self._telegram.send_message(chat, messages.generating(job.title, job.company))
        result = self._claude.run(f"/apply {job.url}", workspace, session=session, system=APPLY_NOTE)
        log.info(f"{APPLY_OUTPUT_PREFIX}[{user.name}]: {result.output[-LOG_OUTPUT_LIMIT:]!r}")
        pdfs = self._new_pdfs(workspace, start)
        if not result.ok or not pdfs:
            jobs.set_status(job_id, JobStatus.ERROR)
            self._notifier.notify(
                messages.apply_failed_admin(user.name, job.title, job.company, result.output)
            )
            self._telegram.send_message(chat, messages.FILES_FAILED, messages.retry_keyboard(job_id))
            return
        self._telegram.send_plain(chat, extract_summary(result.stdout) or messages.APPLY_SUMMARY_FALLBACK)
        for pdf in pdfs:
            self._telegram.send_document(chat, pdf)
        gupy = self._claude.run(
            GUPY_PROMPT, workspace, timeout=600, session=session, resume=True, system=GUPY_NOTE
        )
        if gupy.ok:
            text = clean_gupy_text(gupy.stdout)
            if text:
                self._telegram.send_plain(chat, messages.GUPY_INTRO)
                self._telegram.send_plain(chat, messages.gupy_text(text))
            else:
                log.error(f"gupy[{user.name}] falhou: texto vazio, nada enviado")
        jobs.set_status(job_id, JobStatus.GENERATED)
        self._telegram.send_message(chat, messages.application_ready(job.url), messages.sent_keyboard(job_id))

    @staticmethod
    def _new_pdfs(workspace: Path, start: float) -> list[Path]:
        """PDFs written after ``start`` inside the workspace (symlinks and outside targets are skipped)."""
        root = workspace.resolve()
        found: list[Path] = []
        for directory in PDF_DIRS:
            for pdf in (workspace / directory).rglob("*.pdf"):
                try:
                    if pdf.is_symlink() or not pdf.resolve().is_relative_to(root):
                        continue
                    if pdf.stat().st_mtime > start:
                        found.append(pdf)
                except FileNotFoundError:
                    continue
        return sorted(found)
