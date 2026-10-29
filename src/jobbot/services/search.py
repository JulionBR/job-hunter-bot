"""Daily/manual job search and delivery of the results."""

from __future__ import annotations

import fcntl
import logging
import time
from collections.abc import Sequence

from jobbot import messages
from jobbot.claude import ClaudeRunnerPort
from jobbot.clock import Clock
from jobbot.config import Settings
from jobbot.messages import esc
from jobbot.models import Job, JobStatus, User
from jobbot.prompts import SHORTLIST_FILE, search_prompt
from jobbot.storage import JobRepository, JsonStore, UserRepository
from jobbot.telegram import Notifier, Telegram
from jobbot.workspace import PortalAudience

log = logging.getLogger("jobbot")

FAILED = "falhou"
SEARCH_TIMEOUT = 5400


def _key(job: Job) -> tuple[str, str]:
    return " ".join(job.title.split()).casefold(), " ".join(job.company.split()).casefold()


def same_as_rejected(job: Job, rejected: Sequence[Job]) -> bool:
    """Deterministic guard: exact (title, company) match, normalised, with a refused job."""
    return _key(job) in {_key(r) for r in rejected}


class SearchService:
    def __init__(
        self,
        settings: Settings,
        users: UserRepository,
        store: JsonStore,
        claude: ClaudeRunnerPort,
        telegram: Telegram,
        notifier: Notifier,
        clock: Clock,
        portals: PortalAudience | None = None,
    ) -> None:
        self._settings = settings
        self._users = users
        self._store = store
        self._claude = claude
        self._telegram = telegram
        self._notifier = notifier
        self._clock = clock
        self._portals = portals or PortalAudience()

    def _before_delivery(self) -> bool:
        return self._clock.now().hour < self._settings.delivery_hour

    def run(self, only: int | None = None, deliver_now: bool = False) -> None:
        """Search for everyone with a ready profile (or only ``only``), one search at a time even across
        processes. ``deliver_now=True`` (manual search) sends the jobs right away; the scheduled search
        holds them until the delivery hour."""
        with (self._store.state_dir / "daily.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if only is not None:
                    self._telegram.send_message(only, messages.SEARCH_RUNNING)
                return
            summary: list[str] = []
            started = time.time()
            for user in self._users.all():
                if (only is None or user.chat_id == only) and user.profile_ready:
                    try:
                        summary.append(f"{esc(user.name)}: {self.run_for(user, deliver_now)}")
                    except Exception as ex:
                        log.error(f"daily {user.chat_id} erro: {ex}")
                        summary.append(f"{esc(user.name)}: erro")
            log.info(f"daily fim: {summary}")
            if only is None or only not in self._settings.admin_ids:
                note = (
                    ""
                    if deliver_now or not self._before_delivery()
                    else messages.delivery_note(self._settings.delivery_hour)
                )
                self._notifier.notify(
                    messages.search_summary((time.time() - started) / 60, summary, note),
                    silent=self._clock.is_quiet(),
                )

    def run_for(self, user: User, deliver_now: bool) -> str:
        """Search for one candidate. A scheduled search before the delivery hour stores its result."""
        # Reload: the snapshot may predate a /pcd given while the search waited in line.
        self._portals.sync(self._users.get(user.chat_id) or user)
        shortlist = user.workspace / SHORTLIST_FILE
        shortlist.unlink(missing_ok=True)
        repo = JobRepository(self._store, user.chat_id)
        rejected = repo.recent_rejected()
        prompt = search_prompt(self._settings.top_n, rejected)
        self._claude.run(prompt, user.workspace, timeout=SEARCH_TIMEOUT)
        items = self._store.read(shortlist, None)
        new: list[Job] = []
        result = FAILED
        held = not deliver_now and self._before_delivery()
        if isinstance(items, list):
            status = JobStatus.WAITING if held else JobStatus.NEW
            candidates: list[Job] = []
            for item in items:
                job = Job.from_shortlist(item)
                if job is None or same_as_rejected(job, rejected):
                    continue
                job.status = status
                job.date = self._clock.today()
                candidates.append(job)
            new = repo.add_new(candidates)
            result = str(len(new))
        if held:
            self._users.update(user.chat_id, lambda u: setattr(u, "pending_result", result))
            return result
        self.tell_result(user.chat_id, result, new)
        return result

    def deliver_pending(self) -> None:
        """Scheduled at the delivery hour: sends what the overnight search stored."""
        for user in self._users.all():
            result = user.pending_result
            if result is None:
                continue
            new = JobRepository(self._store, user.chat_id).take_waiting()
            self._users.update(user.chat_id, lambda u: setattr(u, "pending_result", None))
            self.tell_result(user.chat_id, result, new)
        log.info(f"envio das {self._settings.delivery_hour}h concluído")

    def tell_result(self, chat: int, result: str, new: list[Job]) -> None:
        if result == FAILED:
            self._telegram.send_message(chat, messages.SEARCH_FAILED)
        elif not new:
            self._telegram.send_message(chat, messages.no_new_jobs(self._clock.today()))
        else:
            self.send_jobs(chat, new)

    def send_jobs(self, chat: int, new: list[Job]) -> None:
        self._telegram.send_message(chat, messages.new_jobs_header(len(new), self._clock.today()))
        for job in new:
            self._telegram.send_message(chat, messages.job_card(job), messages.job_keyboard(job.job_id))
