"""Access requests: a single request per person, approval creates the workspace, refusal, removal."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from jobbot import messages
from jobbot.clock import Clock
from jobbot.config import Settings
from jobbot.models import PendingRequest, User
from jobbot.services.profile import ProfileService
from jobbot.storage import PendingRepository, UserRepository
from jobbot.telegram import Notifier, Telegram
from jobbot.workspace import PortalAudience, Provisioner, slugify

log = logging.getLogger("jobbot")


class AccessService:
    def __init__(
        self,
        settings: Settings,
        users: UserRepository,
        pending: PendingRepository,
        provisioner: Provisioner,
        profile: ProfileService,
        telegram: Telegram,
        notifier: Notifier,
        clock: Clock,
        portals: PortalAudience | None = None,
    ) -> None:
        self._settings = settings
        self._users = users
        self._pending = pending
        self._provisioner = provisioner
        self._profile = profile
        self._telegram = telegram
        self._notifier = notifier
        self._clock = clock
        self._portals = portals or PortalAudience()

    def request_access(self, chat: int, sender: Mapping[str, Any], text: str) -> None:
        """Register the request (once) and warn the admins with approve/refuse buttons."""
        name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x) or str(chat)
        username = f"@{sender['username']}" if sender.get("username") else ""
        request = PendingRequest(chat, name, username, self._clock.stamp())
        if self._pending.add_if_new(request):
            self._notifier.notify(
                messages.access_request(name, username, chat, text), messages.approval_keyboard(chat)
            )
        self._telegram.send_message(chat, messages.ACCESS_REQUESTED)

    def send_pending(self, chat: int) -> None:
        """/pendentes: one message per request, each with approve/refuse buttons."""
        requests = self._pending.all()
        if not requests:
            self._telegram.send_message(chat, messages.NO_PENDING)
            return
        for p in requests:
            self._telegram.send_message(
                chat,
                messages.pending_line(p.name, p.username, p.chat_id, p.requested_at),
                messages.approval_keyboard(p.chat_id),
            )

    def approve(self, chat: int) -> None:
        request = self._pending.pop(chat)
        if request is None or self._users.get(chat):
            return
        user = self._enroll(chat, request.name)
        if user is None:
            return
        self._telegram.send_message(chat, messages.access_granted(self._settings.delivery_hour))
        self._notifier.notify(messages.approved_admin(request.name, user.workspace))

    def join_as_admin(self, chat: int, name: str) -> None:
        """/participar: an admin registers themselves as a candidate (same steps as an approval)."""
        if self._users.get(chat):
            self._telegram.send_message(chat, messages.ALREADY_CANDIDATE)
            return
        if self._enroll(chat, name) is not None:
            self._telegram.send_message(chat, messages.joined_as_candidate(self._settings.delivery_hour))

    def _enroll(self, chat: int, name: str) -> User | None:
        """Create the workspace folder, register the candidate and switch every audience portal off.

        On a provisioning failure the admins are warned and nobody is registered (returns None).
        """
        workspace = self._settings.candidates_dir / f"{slugify(name)}-{chat}"
        try:
            self._provisioner.create_folder(workspace)
        except Exception as ex:
            log.error(f"create_folder {chat} erro: {ex}")
            self._notifier.notify(messages.folder_failed(name, ex))
            return None
        # The reference folder may carry portals switched on for someone else: start every tag off.
        audiences = {tag: False for tag in self._portals.tags(workspace, chat)} | {"pcd": False}
        user = User(
            chat, name, workspace, profile_ready=False, since=self._clock.today(), audiences=audiences
        )
        self._users.save(user)
        self._portals.sync(user)
        return user

    def refuse(self, chat: int) -> None:
        if self._pending.pop(chat) is not None:
            self._telegram.send_message(chat, messages.ACCESS_REFUSED)

    def remove(self, chat: int) -> User | None:
        """Drop the candidate (the workspace folder is kept); returns the removed user."""
        user = self._users.get(chat)
        if user is None or not self._users.remove(chat):
            return None
        self._profile.discard(chat)
        return user
