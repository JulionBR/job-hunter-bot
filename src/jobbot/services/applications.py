"""Tailored application: /apply through Claude, PDFs back to the candidate, Gupy text."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from jobbot import messages
from jobbot.claude import ClaudeRunnerPort
from jobbot.models import JobStatus
from jobbot.prompts import APPLY_NOTE, GUPY_NOTE, GUPY_PROMPT
from jobbot.storage import JobRepository, JsonStore, UserRepository
from jobbot.telegram import Notifier, Telegram

PDF_DIRS = ("cv", "cover_letters", "documents/applications")


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
        pdfs = self._new_pdfs(workspace, start)
        if not result.ok or not pdfs:
            jobs.set_status(job_id, JobStatus.ERROR)
            self._notifier.notify(
                messages.apply_failed_admin(user.name, job.title, job.company, result.output)
            )
            self._telegram.send_message(chat, messages.FILES_FAILED, messages.retry_keyboard(job_id))
            return
        self._telegram.send_plain(chat, result.output.strip()[-3000:])
        for pdf in pdfs:
            self._telegram.send_document(chat, pdf)
        gupy = self._claude.run(
            GUPY_PROMPT, workspace, timeout=600, session=session, resume=True, system=GUPY_NOTE
        )
        if gupy.ok:
            self._telegram.send_plain(chat, messages.gupy_text(gupy.output))
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
