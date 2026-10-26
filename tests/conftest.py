"""Shared fakes and fixtures. IDs are fictional: 1001 is the admin, 2002+ are candidates."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jobbot.claude import ClaudeResult
from jobbot.clock import Clock
from jobbot.config import Settings
from jobbot.container import App, build_app
from jobbot.telegram import Markup


class FixedClock(Clock):
    """Clock frozen at a given local time."""

    def __init__(self, tz: Any, fixed: datetime) -> None:
        super().__init__(tz)
        self._fixed = fixed.replace(tzinfo=tz)

    def now(self) -> datetime:
        return self._fixed


def write_profile(workspace: Path, placeholder: str | None = None) -> None:
    """Create the four profile files (optionally leaving a template placeholder in one of them)."""
    from jobbot.workspace import PROFILE_FILES

    for rel in PROFILE_FILES:
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Alice")
    if placeholder:
        (workspace / PROFILE_FILES[1]).write_text(placeholder)


ADMIN = 1001
ALICE = 2002
BOB = 2003


@dataclass
class Sent:
    chat: int
    text: str
    markup: Markup | None = None
    silent: bool = False


@dataclass
class FakeTelegram:
    messages: list[Sent] = field(default_factory=list)
    plain: list[Sent] = field(default_factory=list)
    documents: list[tuple[int, Path]] = field(default_factory=list)
    answers: list[tuple[str, str]] = field(default_factory=list)
    cleared: list[tuple[int, int]] = field(default_factory=list)
    typing: list[int] = field(default_factory=list)
    commands: list[tuple[list[tuple[str, str]], dict[str, Any] | None]] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    updates: list[list[dict[str, Any]]] = field(default_factory=list)
    update_error: Exception | None = None
    offsets: list[int | None] = field(default_factory=list)

    def send_message(self, chat: int, text: str, markup: Markup | None = None, silent: bool = False) -> None:
        self.messages.append(Sent(chat, text, markup, silent))

    def send_plain(self, chat: int, text: str) -> None:
        self.plain.append(Sent(chat, text))

    def send_document(self, chat: int, path: Path) -> None:
        self.documents.append((chat, path))

    def download_file(self, file_id: str) -> bytes:
        return self.files[file_id]

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.answers.append((callback_id, text))

    def clear_keyboard(self, chat: int, message_id: int) -> None:
        self.cleared.append((chat, message_id))

    def send_typing(self, chat: int) -> None:
        self.typing.append(chat)

    def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict[str, Any]]:
        self.offsets.append(offset)
        if self.update_error:
            raise self.update_error
        return self.updates.pop(0) if self.updates else []

    def set_commands(self, cmds: Sequence[tuple[str, str]], scope: dict[str, Any] | None = None) -> None:
        self.commands.append((list(cmds), scope))

    def texts(self, chat: int) -> list[str]:
        return [m.text for m in self.messages if m.chat == chat]

    def last(self, chat: int) -> str:
        return self.texts(chat)[-1]


class FakeClaude:
    """Simulates Claude Code: writes a shortlist for search prompts and a PDF for /apply."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] | None = [
            {
                "title": "Analista",
                "company": "X",
                "location": "SP",
                "url": "https://a/1",
                "score": "8/10",
            }
        ]
        self.ok = True
        self.busy = False
        self.output = "texto"
        self.on_run: Callable[[str, Path], None] | None = None

    def run(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = 3600,
        session: str | None = None,
        resume: bool = False,
        system: str = "",
    ) -> ClaudeResult:
        self.calls.append(
            {
                "prompt": prompt,
                "cwd": cwd,
                "timeout": timeout,
                "session": session,
                "resume": resume,
                "system": system,
            }
        )
        if ".jobbot-shortlist.json" in prompt and self.items is not None:
            (cwd / ".jobbot-shortlist.json").write_text(json.dumps(self.items))
        if prompt.startswith("/apply") and self.ok:
            (cwd / "cv").mkdir(exist_ok=True)
            (cwd / "cv" / "a.pdf").write_bytes(b"%PDF")
        if self.on_run:
            self.on_run(prompt, cwd)
        logging.getLogger("jobbot").info(f"claude ok={self.ok} fake {prompt[:20]}")
        return ClaudeResult(self.ok, self.output)

    def is_busy(self) -> bool:
        return self.busy


class FakeProvisioner:
    def __init__(self) -> None:
        self.created: list[Path] = []
        self.error: Exception | None = None

    def create_folder(self, workspace: Path) -> None:
        if self.error:
            raise self.error
        workspace.mkdir(parents=True)
        (workspace / "CLAUDE.md").write_text("[YOUR_NAME]")
        self.created.append(workspace)


@dataclass
class Env:
    app: App
    telegram: FakeTelegram
    claude: FakeClaude
    provisioner: FakeProvisioner
    home: Path

    def message(self, chat: int, text: str, **extra: Any) -> None:
        self.app.router.on_message(
            {"chat": {"id": chat}, "text": text, "from": {"first_name": "Primo", "username": "pr"}, **extra}
        )

    def callback(self, chat: int, data: str) -> None:
        self.app.router.on_callback(
            {"id": "q", "data": data, "message": {"chat": {"id": chat}, "message_id": 5}}
        )

    def run_queue(self) -> None:
        while self.app.worker.queue_size():
            self.app.worker.process_next()

    def add_candidate(self, chat: int = ALICE, name: str = "Alice", ready: bool = True) -> Path:
        from jobbot.models import User

        workspace = self.home / "candidatos" / f"{name.lower()}-{chat}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.app.users.save(User(chat, name, workspace, profile_ready=ready, since="01/01"))
        return workspace

    def texts(self, chat: int) -> list[str]:
        return self.telegram.texts(chat)


MakeEnv = Callable[..., Env]


@pytest.fixture
def make_env(tmp_path: Path) -> MakeEnv:
    def factory(clock: Clock | None = None, **overrides: Any) -> Env:
        settings = Settings(
            home=tmp_path,
            telegram_token="x",
            admin_ids=frozenset({ADMIN}),
            **{"delivery_hour": 0, **overrides},
        )
        telegram, claude, provisioner = FakeTelegram(), FakeClaude(), FakeProvisioner()
        app = build_app(
            settings,
            telegram=telegram,
            claude=claude,
            provisioner=provisioner,
            spawn=lambda fn: fn(),
            show_unit=lambda unit, prop: f"{unit}:{prop}",
            clock=clock,
        )
        return Env(app, telegram, claude, provisioner, tmp_path)

    return factory


@pytest.fixture
def env(make_env: MakeEnv) -> Env:
    """Delivery hour 0: scheduled searches deliver immediately."""
    return make_env()
