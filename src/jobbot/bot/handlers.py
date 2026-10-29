"""Thin handlers by role: they parse the input and call services, with no business logic of their own."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from jobbot import messages
from jobbot.clock import Clock
from jobbot.config import Settings
from jobbot.models import JobStatus, User
from jobbot.services.access import AccessService
from jobbot.services.admin import AdminService
from jobbot.services.applications import ApplicationService
from jobbot.services.profile import ProfileService
from jobbot.services.search import SearchService
from jobbot.storage import JobRepository, JsonStore, UserRepository
from jobbot.telegram import Telegram
from jobbot.workspace import PortalAudience

Spawn = Callable[[Callable[[], object]], None]

# A failed application can still be turned down; queued/generated/sent ones are already in progress.
REJECTABLE = (JobStatus.NEW, JobStatus.WAITING, JobStatus.ERROR)
CALLBACK_STATUS = {"a": JobStatus.QUEUED, "s": JobStatus.SKIPPED, "d": JobStatus.SENT}


class TaskQueue(Protocol):
    """Serial queue of Claude jobs (the Worker)."""

    def submit(self, name: str, fn: Callable[[], None], chat: int) -> int: ...


PCD_ANSWERS = {"sim": True, "s": True, "nao": False, "não": False, "n": False}


def parse_chat_id(arg: str) -> int | None:
    """``arg`` as a chat id, only if it is exactly the canonical decimal form."""
    try:
        chat = int(arg)
    except ValueError:
        return None
    return chat if str(chat) == arg else None


class GuestHandlers:
    """People who are not approved yet: every message becomes (at most) one access request."""

    def __init__(self, access: AccessService) -> None:
        self._access = access

    def handle(self, chat: int, message: dict[str, Any], text: str) -> None:
        self._access.request_access(chat, message.get("from", {}), text)


class AdminHandlers:
    def __init__(
        self,
        telegram: Telegram,
        users: UserRepository,
        access: AccessService,
        admin: AdminService,
        search: SearchService,
        spawn: Spawn,
        portals: PortalAudience | None = None,
    ) -> None:
        self._telegram = telegram
        self._users = users
        self._portals = portals or PortalAudience()
        self._access = access
        self._admin = admin
        self._search = search
        self._spawn = spawn

    def handle(self, chat: int, cmd: str, arg: str, sender: Mapping[str, Any] | None = None) -> bool:
        """Handle an admin command; False if ``cmd`` is not one of them."""
        say = self._telegram.send_message
        if cmd == "/usuarios":
            say(chat, self._admin.users_summary())
        elif cmd == "/pendentes":
            self._access.send_pending(chat)
        elif cmd == "/participar":
            name = str((sender or {}).get("first_name") or chat)
            # Like an approval, it clones a repo: keep it off the polling thread.
            self._spawn(lambda: self._access.join_as_admin(chat, name))
        elif cmd == "/remover":
            target = parse_chat_id(arg)
            removed = None if target is None else self._access.remove(target)
            say(chat, messages.removed(removed.name, removed.workspace) if removed else messages.REMOVE_USAGE)
        elif cmd == "/buscar" and (not arg or self._is_user(arg)):
            say(chat, messages.admin_search_started(arg))
            only = parse_chat_id(arg) if arg else None
            self._spawn(lambda: self._search.run(only, True))
        elif cmd == "/pcd":
            self._set_pcd(chat, arg)
        elif cmd == "/log":
            self._send_log(chat, arg)
        elif cmd == "/saude":
            say(chat, self._admin.health())
        else:
            return False
        return True

    def _set_pcd(self, chat: int, arg: str) -> None:
        target, _, answer = arg.partition(" ")
        pcd = PCD_ANSWERS.get(answer.strip().lower())
        chat_id = parse_chat_id(target)
        user = None
        if chat_id is not None and pcd is not None:
            user = self._users.update(chat_id, lambda u: setattr(u, "pcd", pcd))
        if user is None or pcd is None:
            self._telegram.send_message(chat, messages.PCD_USAGE)
            return
        found = self._portals.sync(user)
        self._telegram.send_message(chat, messages.pcd_set(user.name, pcd, found))

    def _is_user(self, arg: str) -> bool:
        chat = parse_chat_id(arg)
        return chat is not None and self._users.get(chat) is not None

    def _send_log(self, chat: int, arg: str) -> None:
        chunks = self._admin.log_chunks(arg)
        if not chunks:
            self._telegram.send_message(
                chat, messages.LOG_NO_ERRORS if arg == "erros" else messages.LOG_EMPTY
            )
            return
        for chunk in chunks:
            self._telegram.send_message(chat, messages.log_block(chunk), silent=True)


def _is_finish_word(text: str) -> bool:
    """A bare "Fim" / "fim." / "fim!" (the user forgot the slash) while a /perfil is open."""
    return text.strip().lower() in ("fim", "fim.", "fim!")


class CandidateHandlers:
    """Approved candidates (admins who are also candidates fall here when no admin command matched)."""

    def __init__(
        self,
        settings: Settings,
        telegram: Telegram,
        users: UserRepository,
        profile: ProfileService,
        search: SearchService,
        reports: AdminService,
        queue: TaskQueue,
        spawn: Spawn,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._telegram = telegram
        self._users = users
        self._clock = clock
        self._profile = profile
        self._search = search
        self._reports = reports
        self._queue = queue
        self._spawn = spawn

    def handle(self, user: User, message: dict[str, Any], cmd: str, text: str) -> None:
        chat = user.chat_id
        session = self._profile.current_session(chat)
        if "document" in message:
            self._profile.save_cv(user, message["document"])
        elif cmd == "/perfil":
            session = self._profile.start(chat)
            self._queue.submit("setup_turn", lambda: self._profile.turn(chat, None, session), chat)
        elif session is not None and (cmd == "/fim" or _is_finish_word(text)):
            # Runs after the turns already queued, so the last answer is in the profile when it is checked.
            self._telegram.send_message(chat, messages.PROFILE_FINISH_QUEUED)
            queued = session
            self._queue.submit("setup_finish", lambda: self._profile.finish_queued(chat, queued), chat)
        elif cmd == "/fim":
            self._profile.finish(user)
        elif session and text and not text.startswith("/"):
            self._telegram.send_typing(chat)
            self._queue.submit("setup_turn", lambda: self._profile.turn(chat, text, session), chat)
        elif cmd == "/buscar":
            self._manual_search(user)
        elif cmd == "/status":
            self._telegram.send_message(chat, messages.status_line(self._reports.status_counts(chat)))
        else:
            is_admin = chat in self._settings.admin_ids
            self._telegram.send_message(chat, messages.help_text(self._settings.delivery_hour, is_admin))

    def _manual_search(self, user: User) -> None:
        chat = user.chat_id
        if not user.profile_ready:
            self._telegram.send_message(chat, messages.PROFILE_FIRST)
            return
        today = self._clock.today()
        already = False

        def mark(u: User) -> None:
            nonlocal already
            already = u.manual_search_day == today
            u.manual_search_day = today

        self._users.update(chat, mark)
        if already and chat not in self._settings.admin_ids:
            self._telegram.send_message(chat, messages.MANUAL_SEARCH_DONE)
            return
        self._telegram.send_message(chat, messages.MANUAL_SEARCH_STARTED)
        self._spawn(lambda: self._search.run(chat, True))


class CallbackHandlers:
    """Inline-button callbacks: ``ok:``/``no:`` (admin) and ``a:``/``s:``/``d:`` (candidate)."""

    def __init__(
        self,
        settings: Settings,
        telegram: Telegram,
        users: UserRepository,
        store: JsonStore,
        access: AccessService,
        applications: ApplicationService,
        queue: TaskQueue,
        spawn: Spawn,
    ) -> None:
        self._settings = settings
        self._telegram = telegram
        self._users = users
        self._store = store
        self._access = access
        self._applications = applications
        self._queue = queue
        self._spawn = spawn

    def handle(self, query: dict[str, Any]) -> None:
        chat, message_id = query["message"]["chat"]["id"], query["message"]["message_id"]
        kind, arg = query["data"].split(":", 1)
        answer = self._telegram.answer_callback
        if kind in ("ok", "no"):
            if chat not in self._settings.admin_ids:
                answer(query["id"], messages.ADMIN_ONLY_ANSWER)
                return
            self._telegram.clear_keyboard(chat, message_id)
            if kind == "ok":
                self._spawn(lambda: self._access.approve(int(arg)))
                answer(query["id"], messages.APPROVING_ANSWER)
            else:
                self._access.refuse(int(arg))
                answer(query["id"], messages.REFUSED_ANSWER)
            return
        if self._users.get(chat) is None:
            answer(query["id"], messages.NO_ACCESS_ANSWER)
            return
        status = CALLBACK_STATUS[kind]
        jobs = JobRepository(self._store, chat)
        job = jobs.get(arg)
        if job is None:
            answer(query["id"], messages.JOB_NOT_FOUND_ANSWER)
            return
        if kind == "s" and job.status not in REJECTABLE:
            self._telegram.clear_keyboard(chat, message_id)
            answer(query["id"], messages.IN_PROGRESS_ANSWER)
            return
        jobs.set_status(arg, status)
        self._telegram.clear_keyboard(chat, message_id)
        if kind == "a":
            position = self._queue.submit("apply_job", lambda: self._applications.apply_job(chat, arg), chat)
            note = messages.queued_answer(position)
        else:
            note = messages.SKIPPED_ANSWER if kind == "s" else messages.SENT_ANSWER
        answer(query["id"], note)
