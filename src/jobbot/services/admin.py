"""Admin read models: health, log tail and users summary."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Protocol

from jobbot import messages
from jobbot.claude import ClaudeRunnerPort
from jobbot.services.applications import APPLY_OUTPUT_PREFIX
from jobbot.services.profile import ProfileService
from jobbot.storage import JobRepository, JsonStore, PendingRepository, UserRepository

ERROR_PATTERN = re.compile(r"ok=False|erro|falhou|Traceback")
# Log lines that quote Claude's output or prompts are not bot errors, even if they contain "erro".
NOT_ERRORS = (f"{APPLY_OUTPUT_PREFIX}[", "claude[", "claude ok=True")
LOG_CHUNK = 3500
SEARCH_TIMER = "jobbot-search.timer"

TaskInfo = tuple[str, int, float]  # (task name, chat, started at)


class QueueStatus(Protocol):
    """Worker view used by /saude."""

    def current_task(self) -> TaskInfo | None: ...

    def queue_size(self) -> int: ...


class AdminService:
    def __init__(
        self,
        store: JsonStore,
        users: UserRepository,
        pending: PendingRepository,
        claude: ClaudeRunnerPort,
        profile: ProfileService,
        queue: QueueStatus,
        show_unit: Callable[[str, str], str],
        started_at: float | None = None,
    ) -> None:
        self._store = store
        self._users = users
        self._pending = pending
        self._claude = claude
        self._profile = profile
        self._queue = queue
        self._show_unit = show_unit
        self._started_at = time.time() if started_at is None else started_at

    def log_tail(self, arg: str) -> list[str]:
        """Last log lines: ``arg`` is a count (default 30, max 200) or ``erros`` for the last 20 errors."""
        log_file = self._store.state_dir / "log.txt"
        lines: list[str] = []
        for f in (log_file.with_suffix(".txt.1"), log_file):
            if f.exists():
                lines += f.read_text(errors="replace").splitlines()
        if arg == "erros":
            lines = [
                line
                for line in lines
                if ERROR_PATTERN.search(line) and not any(m in line for m in NOT_ERRORS)
            ][-20:]
        else:
            lines = lines[-min(int(arg) if arg.isdigit() else 30, 200) :]
        return [line[:300] for line in lines]

    def log_chunks(self, arg: str) -> list[str]:
        """The log tail grouped in blocks that fit one Telegram message (empty if there is no log)."""
        lines = self.log_tail(arg)
        if not lines:
            return []
        chunks: list[str] = []
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > LOG_CHUNK:
                chunks.append(chunk)
                chunk = ""
            chunk += line + "\n"
        chunks.append(chunk)
        return chunks

    def health(self) -> str:
        current = self._queue.current_task()
        description = (
            f"{current[0]} para {current[1]} há {(time.time() - current[2]) / 60:.0f} min"
            if current
            else "nenhum"
        )
        errors = self.log_tail("erros")
        users = self._users.all()
        return messages.health(
            uptime_hours=(time.time() - self._started_at) / 3600,
            claude_state="ocupado" if self._claude.is_busy() else "livre",
            current=description,
            queue_size=self._queue.queue_size(),
            next_search=self._show_unit(SEARCH_TIMER, "NextElapseUSecRealtime"),
            last_search=self._show_unit(SEARCH_TIMER, "LastTriggerUSec"),
            users=len(users),
            ready=sum(1 for u in users if u.profile_ready),
            pending=len(self._pending.all()),
            open_chats=self._profile.active_count(),
            last_error=errors[-1] if errors else "",
        )

    def status_counts(self, chat: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in JobRepository(self._store, chat).all():
            counts[str(job.status)] = counts.get(str(job.status), 0) + 1
        return counts

    def users_summary(self) -> str:
        users = self._users.all()
        if not users:
            return messages.NO_USERS
        return "\n".join(
            messages.user_line(
                u.name,
                u.chat_id,
                u.profile_ready,
                self._profile.is_active(u.chat_id),
                self.status_counts(u.chat_id),
            )
            for u in users
        )
