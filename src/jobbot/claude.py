"""Claude Code CLI runner: one run at a time (global flock), staging sync, expired-token alert."""

from __future__ import annotations

import fcntl
import fnmatch
import logging
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jobbot import messages
from jobbot.prompts import BASE_NOTE, STAGING_ALLOWED, STAGING_NOTE
from jobbot.telegram import Notifier

log = logging.getLogger("jobbot")

TOKEN_ERROR_MARKERS = ("401", "unauthorized", "oauth", "login", "expired")


@dataclass(frozen=True)
class ClaudeResult:
    ok: bool
    output: str


class ClaudeRunnerPort(Protocol):
    """What the services need from the Claude runner (tests provide a fake)."""

    def run(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = 3600,
        session: str | None = None,
        resume: bool = False,
        system: str = "",
    ) -> ClaudeResult: ...

    def is_busy(self) -> bool: ...


class StagingSync:
    """Applies to ``.claude/`` the profile files Claude left in ``.jobbot-staging/claude/``.

    Only allow-listed paths are copied; symlinks and anything else are ignored (and logged).
    """

    def __init__(self, allowed: Sequence[str] = STAGING_ALLOWED) -> None:
        self._allowed = tuple(allowed)

    def _allowed_path(self, rel: Path) -> bool:
        """Anchored match: same number of segments as the pattern, each segment fnmatch-ed."""
        parts = rel.parts
        return any(
            len(parts) == len(pattern.split("/"))
            and all(
                fnmatch.fnmatchcase(part, pat) for part, pat in zip(parts, pattern.split("/"), strict=True)
            )
            for pattern in self._allowed
        )

    def sync(self, workspace: Path) -> list[str]:
        workspace = Path(workspace)
        stage = workspace / ".jobbot-staging" / "claude"
        applied: list[str] = []
        for f in sorted(stage.rglob("*")) if stage.exists() else []:
            rel = f.relative_to(stage)
            if f.is_file() and not f.is_symlink() and self._allowed_path(rel):
                dest = workspace / ".claude" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
                f.unlink()
                applied.append(str(rel))
            elif f.is_file():
                log.info(f"staging ignorado (fora da lista): {rel}")
        if applied:
            log.info(f"staging aplicado em {workspace.name}: {applied}")
        return applied


class ClaudeRunner:
    """Runs ``claude -p`` non-interactively inside a candidate's workspace.

    A single global lock (``claude.lock``, shared across processes) serialises every run so the
    subscription limit is not blown.
    """

    def __init__(
        self,
        state_dir: Path,
        notifier: Notifier,
        staging: StagingSync | None = None,
        executable: str = "claude",
    ) -> None:
        self._lock_path = state_dir / "claude.lock"
        self._notifier = notifier
        self._staging = staging or StagingSync()
        self._executable = executable

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the global Claude lock (blocking)."""
        with self._lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def is_busy(self) -> bool:
        with self._lock_path.open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    def run(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = 3600,
        session: str | None = None,
        resume: bool = False,
        system: str = "",
    ) -> ClaudeResult:
        """``session`` is the conversation UUID; ``resume=True`` continues it.

        ``system`` is appended to the system prompt after the staging and base notes.
        """
        cmd = [
            self._executable,
            "-p",
            prompt,
            "--permission-mode",
            "acceptEdits",
            "--append-system-prompt",
            f"{STAGING_NOTE}\n\n{BASE_NOTE}\n\n{system}".strip(),
        ]
        if session:
            cmd += ["--resume" if resume else "--session-id", session]
        with self.exclusive():
            log.info(f"claude[{Path(cwd).name}]: {prompt[:80]!r}")
            try:
                p = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stdin=subprocess.DEVNULL,
                )
                out, ok = p.stdout + p.stderr, p.returncode == 0
            except subprocess.TimeoutExpired:
                out, ok = "Tempo esgotado.", False
            self._staging.sync(Path(cwd))
            shutil.rmtree(Path(cwd) / ".jobbot-tmp", ignore_errors=True)
        log.info(f"claude ok={ok}: {out[-500:]!r}")
        if not ok and any(s in out.lower() for s in TOKEN_ERROR_MARKERS):
            self._notifier.notify(messages.TOKEN_EXPIRED)
        return ClaudeResult(ok, out)
