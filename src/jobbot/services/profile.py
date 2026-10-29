"""/setup conversations (profile onboarding through Claude) and CV upload."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jobbot import messages
from jobbot.claude import ClaudeRunnerPort
from jobbot.clock import Clock
from jobbot.config import Settings
from jobbot.models import User
from jobbot.prompts import SETUP_NOTE, SETUP_PROMPT
from jobbot.storage import UserRepository
from jobbot.telegram import Notifier, Telegram
from jobbot.workspace import profile_ready

SETUP_TIMEOUT = 1800
# A /perfil left open (no /fim) stops capturing free text after this, so a stray "obrigada" days later
# does not resume the setup conversation and spend quota.
SESSION_TTL = timedelta(hours=48)


class ProfileService:
    def __init__(
        self,
        settings: Settings,
        users: UserRepository,
        claude: ClaudeRunnerPort,
        telegram: Telegram,
        notifier: Notifier,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._users = users
        self._claude = claude
        self._telegram = telegram
        self._notifier = notifier
        self._clock = clock

    # The conversation UUID lives in users.json (``profile_session``), so a restart keeps it.
    def _session(self, user: User | None) -> str | None:
        """The user's open conversation, or None if there is none or it expired.

        An expired session is cleared from the stored user (never touching ``profile_ready``). A session with
        no usable start time (legacy data, corrupted value) cannot be aged, so it is treated as expired too:
        otherwise it would stay open forever and swallow free text.
        """
        if user is None or not user.profile_session:
            return None
        if self._is_expired(user.profile_session_started):
            self._users.update(user.chat_id, _expire_session(user.profile_session))
            return None
        return user.profile_session

    def _is_expired(self, started: str | None) -> bool:
        if not started:
            return True
        try:
            return self._clock.now() - datetime.fromisoformat(started) > SESSION_TTL
        except (ValueError, TypeError):  # unparsable, or naive (no timezone) and so not comparable: expired
            return True

    def is_active(self, chat: int) -> bool:
        return self._session(self._users.get(chat)) is not None

    def current_session(self, chat: int) -> str | None:
        return self._session(self._users.get(chat))

    def active_count(self) -> int:
        return sum(1 for u in self._users.all() if self._session(u) is not None)

    def discard(self, chat: int) -> None:
        self._users.update(chat, _close_session)

    def start(self, chat: int) -> str:
        """Open a new conversation and greet the user; returns its id, used by the first turn."""
        session, started = str(uuid.uuid4()), self._clock.now().isoformat()

        def open_session(u: User) -> None:
            u.profile_session, u.profile_session_started = session, started

        self._users.update(chat, open_session)
        self._telegram.send_message(chat, messages.PROFILE_INTRO)
        return session

    def turn(self, chat: int, text: str | None, session: str) -> None:
        """One Claude turn of the conversation (``None`` text means the opening turn).

        ``session`` is the id the turn was queued for; if it is no longer the current one (replaced by a new
        /perfil, closed by /fim or expired) the turn is dropped silently.
        """
        user = self._users.get(chat)
        if user is None or self._session(user) != session:
            return
        first = text is None
        result = self._claude.run(
            SETUP_PROMPT if text is None else text,
            user.workspace,
            timeout=SETUP_TIMEOUT,
            session=session,
            resume=not first,
            system=SETUP_NOTE,
        )
        if result.ok:
            self._telegram.send_plain(chat, result.stdout)
            return
        self._telegram.send_plain(chat, messages.PROFILE_ERROR)
        self._notifier.notify(messages.profile_failed_admin(user.name))

    def finish_queued(self, chat: int, session: str) -> None:
        """/fim run by the worker, after the turns queued before it.

        ``session`` is the conversation the /fim was sent in; if a new /perfil replaced it meanwhile, the new
        conversation is left alone.
        """
        user = self._users.get(chat)
        if user is not None and self._session(user) == session:
            self._close(user, session)

    def finish(self, user: User) -> None:
        """/fim: close the conversation and mark whether the profile is complete."""
        session = self._session(self._users.get(user.chat_id))
        if session is None:
            self._finish_without_session(user)
            return
        self._close(user, session)

    def _close(self, user: User, session: str) -> None:
        ready = profile_ready(user.workspace)
        closed = False

        def close(u: User) -> None:
            nonlocal closed
            if u.profile_session == session:  # a newer /perfil opened meanwhile stays
                _close_session(u)
                u.profile_ready = ready
                closed = True

        self._users.update(user.chat_id, close)
        if not closed:
            return
        if ready:
            self._telegram.send_message(user.chat_id, messages.profile_done(self._settings.delivery_hour))
            self._notifier.notify(messages.profile_done_admin(user.name), silent=True)
        else:
            self._telegram.send_message(user.chat_id, messages.PROFILE_INCOMPLETE)

    def _finish_without_session(self, user: User) -> None:
        """No open conversation: never demote a ready profile, never notify the admin."""
        fresh = self._users.get(user.chat_id) or user
        if fresh.profile_ready:
            self._telegram.send_message(user.chat_id, messages.NO_ACTIVE_PROFILE)
        elif profile_ready(user.workspace):  # files finished but /fim never arrived (e.g. expired session)
            self._users.update(user.chat_id, lambda u: setattr(u, "profile_ready", True))
            self._telegram.send_message(user.chat_id, messages.profile_done(self._settings.delivery_hour))
        else:
            self._telegram.send_message(user.chat_id, messages.PROFILE_INCOMPLETE)

    def save_cv(self, user: User, document: dict[str, Any]) -> None:
        name = Path(document.get("file_name") or "curriculo.pdf").name
        if not name.lower().endswith((".pdf", ".docx")):
            self._telegram.send_message(user.chat_id, messages.CV_FORMAT)
            return
        content = self._telegram.download_file(document["file_id"])
        dest = user.workspace / "documents" / "cv" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        self._telegram.send_message(user.chat_id, messages.cv_saved(name))


def _close_session(user: User) -> None:
    user.profile_session = None
    user.profile_session_started = None


def _expire_session(session: str) -> Callable[[User], None]:
    def clear(user: User) -> None:
        if user.profile_session == session:  # a newer /perfil opened meanwhile stays
            _close_session(user)

    return clear
