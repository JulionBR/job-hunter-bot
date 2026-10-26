"""Telegram Bot API client (stdlib urllib, long polling) and the admin notifier."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("jobbot")

Markup = dict[str, Any]
MESSAGE_LIMIT = 4000


class Telegram(Protocol):
    """What the services need from Telegram (tests provide a fake)."""

    def send_message(
        self, chat: int, text: str, markup: Markup | None = None, silent: bool = False
    ) -> None: ...

    def send_plain(self, chat: int, text: str) -> None: ...

    def send_document(self, chat: int, path: Path) -> None: ...

    def download_file(self, file_id: str) -> bytes: ...

    def answer_callback(self, callback_id: str, text: str) -> None: ...

    def clear_keyboard(self, chat: int, message_id: int) -> None: ...

    def send_typing(self, chat: int) -> None: ...

    def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict[str, Any]]: ...

    def set_commands(self, cmds: Sequence[tuple[str, str]], scope: dict[str, Any] | None = None) -> None: ...


class TelegramClient:
    """Thin Bot API client."""

    def __init__(self, token: str) -> None:
        self._api = f"https://api.telegram.org/bot{token}/"
        self._file_api = f"https://api.telegram.org/file/bot{token}/"

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        data = urllib.parse.urlencode(
            {
                k: json.dumps(v) if isinstance(v, dict | list) else v
                for k, v in params.items()
                if v is not None
            }
        ).encode()
        with urllib.request.urlopen(self._api + method, data=data, timeout=75) as response:
            result: dict[str, Any] = json.load(response)
            return result

    def send_message(self, chat: int, text: str, markup: Markup | None = None, silent: bool = False) -> None:
        """Send HTML; a failure is logged and swallowed so one bad chat never stops a run."""
        try:
            self.call(
                "sendMessage",
                chat_id=chat,
                text=text[:MESSAGE_LIMIT],
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
                disable_notification=silent or None,
            )
        except Exception as ex:
            log.error(f"telegram falhou para {chat}: {ex}")

    def send_plain(self, chat: int, text: str) -> None:
        """Send plain text, split in chunks. Errors propagate (the worker reports them)."""
        text = text.strip() or "(sem resposta)"
        for i in range(0, len(text), MESSAGE_LIMIT):
            self.call("sendMessage", chat_id=chat, text=text[i : i + MESSAGE_LIMIT])

    def send_document(self, chat: int, path: Path) -> None:
        boundary = uuid.uuid4().hex
        path = Path(path)
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
            + path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        request = urllib.request.Request(
            self._api + "sendDocument",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        urllib.request.urlopen(request, timeout=120).close()

    def download_file(self, file_id: str) -> bytes:
        remote = self.call("getFile", file_id=file_id)["result"]["file_path"]
        with urllib.request.urlopen(self._file_api + remote, timeout=120) as response:
            content: bytes = response.read()
            return content

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def clear_keyboard(self, chat: int, message_id: int) -> None:
        self.call(
            "editMessageReplyMarkup",
            chat_id=chat,
            message_id=message_id,
            reply_markup={"inline_keyboard": []},
        )

    def send_typing(self, chat: int) -> None:
        self.call("sendChatAction", chat_id=chat, action="typing")

    def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict[str, Any]]:
        response = self.call(
            "getUpdates",
            timeout=timeout,
            offset=offset,
            allowed_updates=["message", "callback_query"],
        )
        updates: list[dict[str, Any]] = response["result"]
        return updates

    def set_commands(self, cmds: Sequence[tuple[str, str]], scope: dict[str, Any] | None = None) -> None:
        self.call(
            "setMyCommands",
            commands=[{"command": c, "description": d} for c, d in cmds],
            scope=scope,
        )


class Notifier:
    """Sends a message to every admin."""

    def __init__(self, telegram: Telegram, admin_ids: Iterable[int]) -> None:
        self._telegram = telegram
        self._admin_ids = sorted(admin_ids)

    def notify(self, text: str, markup: Markup | None = None, silent: bool = False) -> None:
        for admin in self._admin_ids:
            self._telegram.send_message(admin, text, markup, silent)
