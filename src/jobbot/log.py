"""Logging setup: stdlib logging into ``state/log.txt`` with a single rotated backup."""

from __future__ import annotations

import contextlib
import fcntl
import logging
from pathlib import Path

LOGGER_NAME = "jobbot"
MAX_BYTES = 2_000_000


class ReopeningFileHandler(logging.Handler):
    """Append to a file, reopening it on every record so several processes can share it.

    When the file exceeds ``max_bytes`` it is renamed to ``<name>.1`` (replacing any older backup).
    Rotation is serialised across processes with an advisory lock on ``<name>.lock``.
    """

    def __init__(self, path: Path, max_bytes: int = MAX_BYTES) -> None:
        super().__init__()
        self.path = path
        self.max_bytes = max_bytes
        self.backup = path.with_name(path.name + ".1")
        self._lock_path = path.with_name(path.name + ".lock")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record) + "\n"
            with self._lock_path.open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with contextlib.suppress(FileNotFoundError):
                    if self.path.stat().st_size > self.max_bytes:
                        self.path.replace(self.backup)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            self.handleError(record)


def setup_logging(state_dir: Path) -> logging.Logger:
    """Configure and return the ``jobbot`` logger (idempotent: replaces previous handlers)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = ReopeningFileHandler(state_dir / "log.txt")
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    return logger
