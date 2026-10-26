"""Bot runtime: serial Worker for Claude jobs and the long-polling loop."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from jobbot import messages
from jobbot.bot.router import Router
from jobbot.config import Settings
from jobbot.messages import ADMIN_CMDS, USER_CMDS
from jobbot.services.admin import TaskInfo
from jobbot.storage import UserRepository
from jobbot.telegram import Telegram

log = logging.getLogger("jobbot")

RETRY_DELAY = 10


class Worker:
    """Runs one Claude job at a time, in submission order."""

    def __init__(self, telegram: Telegram) -> None:
        self._telegram = telegram
        self._queue: queue.Queue[tuple[str, Callable[[], None], int]] = queue.Queue()
        self._current: TaskInfo | None = None

    def submit(self, name: str, fn: Callable[[], None], chat: int) -> int:
        """Enqueue a job; returns the queue size right after (the position shown to the user)."""
        self._queue.put((name, fn, chat))
        return self._queue.qsize()

    def current_task(self) -> TaskInfo | None:
        return self._current

    def queue_size(self) -> int:
        return self._queue.qsize()

    def process_next(self) -> None:
        """Block for the next job and run it; a failure is logged and reported to the chat."""
        name, fn, chat = self._queue.get()
        self._current = (name, chat, time.time())
        try:
            fn()
        except Exception as ex:
            log.error(f"{name} erro: {ex}")
            self._telegram.send_message(chat, messages.worker_error(ex))
        self._current = None

    def run_forever(self) -> None:
        while True:
            self.process_next()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, daemon=True)
        thread.start()
        return thread


class BotApp:
    def __init__(
        self,
        settings: Settings,
        telegram: Telegram,
        users: UserRepository,
        router: Router,
        worker: Worker,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._telegram = telegram
        self._users = users
        self._router = router
        self._worker = worker
        self._sleep = sleep
        self._offset: int | None = None

    def set_commands(self) -> None:
        """Publish the command menus: candidates by default, admins get their own (scoped by chat)."""
        try:
            self._telegram.set_commands(USER_CMDS)
            for admin in sorted(self._settings.admin_ids):
                admin_list = (
                    ADMIN_CMDS + [c for c in USER_CMDS if c[0] != "buscar"]
                    if self._users.get(admin)
                    else ADMIN_CMDS
                )
                self._telegram.set_commands(admin_list, {"type": "chat", "chat_id": admin})
        except Exception as ex:
            log.error(f"setMyCommands: {ex}")

    def handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._router.on_callback(update["callback_query"])
        elif "message" in update:
            self._router.on_message(update["message"])

    def poll_once(self) -> None:
        """One getUpdates round: errors never escape (a failed poll waits and retries)."""
        try:
            updates = self._telegram.get_updates(self._offset, 50)
        except Exception as ex:
            log.error(f"getUpdates: {ex}")
            self._sleep(RETRY_DELAY)
            return
        for update in updates:
            self._offset = update["update_id"] + 1
            try:
                self.handle_update(update)
            except Exception as ex:
                log.error(f"update erro: {ex}")

    def run(self) -> None:
        self.set_commands()
        self._worker.start()
        log.info("bot iniciado")
        while True:
            self.poll_once()
