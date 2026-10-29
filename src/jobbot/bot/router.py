"""Routes Telegram updates to handlers by role: admin, candidate or unknown person."""

from __future__ import annotations

from typing import Any

from jobbot import messages
from jobbot.bot.handlers import AdminHandlers, CallbackHandlers, CandidateHandlers, GuestHandlers
from jobbot.config import Settings
from jobbot.storage import UserRepository
from jobbot.telegram import Telegram


class Router:
    def __init__(
        self,
        settings: Settings,
        telegram: Telegram,
        users: UserRepository,
        guests: GuestHandlers,
        admins: AdminHandlers,
        candidates: CandidateHandlers,
        callbacks: CallbackHandlers,
    ) -> None:
        self._settings = settings
        self._telegram = telegram
        self._users = users
        self._guests = guests
        self._admins = admins
        self._candidates = candidates
        self._callbacks = callbacks

    def on_callback(self, query: dict[str, Any]) -> None:
        self._callbacks.handle(query)

    def on_message(self, message: dict[str, Any]) -> None:
        chat = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip()
        user = self._users.get(chat)
        is_admin = chat in self._settings.admin_ids
        # Admin commands only match "/..." text: free text from an admin who is also a candidate
        # falls through to CandidateHandlers, where an open /perfil conversation takes it.
        if is_admin and cmd.startswith("/") and self._admins.handle(chat, cmd, arg, message.get("from")):
            return
        if user is None:
            if is_admin:
                self._telegram.send_message(chat, messages.ADMIN_HELP)
            else:
                self._guests.handle(chat, message, text)
            return
        self._candidates.handle(user, message, cmd, text)
