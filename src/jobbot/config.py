"""Runtime configuration: paths, admins and schedule, read from the environment and an env file."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_HOME = "/home/jobbot"
DEFAULT_TZ = "America/Sao_Paulo"


class ConfigError(RuntimeError):
    """Invalid or incomplete configuration."""


def parse_env_text(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Blank lines, ``#`` comments and lines without ``=`` are ignored."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def parse_admin_ids(raw: str) -> frozenset[int]:
    """Parse a comma-separated list of integer chat IDs (spaces tolerated, empty items skipped)."""
    return frozenset(int(item) for item in raw.replace(" ", "").split(",") if item)


def _int(env: Mapping[str, str], *names: str, default: int) -> int:
    for name in names:
        raw = env.get(name)
        if raw not in (None, ""):
            return int(str(raw))
    return default


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    home: Path
    telegram_token: str
    admin_ids: frozenset[int]
    top_n: int = 5
    delivery_hour: int = 7
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo(DEFAULT_TZ))

    @property
    def reference_workspace(self) -> Path:
        return self.home / "ai-job-search"

    @property
    def candidates_dir(self) -> Path:
        return self.home / "candidatos"

    @property
    def state_dir(self) -> Path:
        return self.home / "jobbot" / "state"

    @property
    def env_file(self) -> Path:
        return self.home / ".config" / "jobbot" / "env"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Build settings from a mapping (pure; does not touch the filesystem or ``os.environ``)."""
        home = Path(env.get("JOBBOT_HOME") or DEFAULT_HOME)
        return cls(
            home=home,
            telegram_token=env.get("TELEGRAM_BOT_TOKEN", ""),
            admin_ids=parse_admin_ids(env.get("ADMIN_IDS", "")),
            top_n=_int(env, "JOBBOT_TOP_N", default=5),
            delivery_hour=_int(env, "JOBBOT_DELIVERY_HOUR", "JOBBOT_ENVIO_HORA", default=7),
        )

    @classmethod
    def load(cls, *, require_token: bool = False) -> Settings:
        """Load the env file into ``os.environ`` (without overriding), extend PATH and build settings.

        With ``require_token=True`` raises ``ConfigError`` if TELEGRAM_BOT_TOKEN is empty.
        """
        home = Path(os.environ.get("JOBBOT_HOME") or DEFAULT_HOME)
        env_file = home / ".config" / "jobbot" / "env"
        try:
            text = env_file.read_text()
        except FileNotFoundError:
            text = ""
        for key, value in parse_env_text(text).items():
            os.environ.setdefault(key, value)
        user_home = Path.home()
        extra = f"{user_home}/.bun/bin:{user_home}/.local/bin"
        os.environ["PATH"] = f"{extra}:{os.environ.get('PATH', '')}"
        settings = cls.from_env(os.environ)
        if require_token and not settings.telegram_token:
            raise ConfigError(f"TELEGRAM_BOT_TOKEN is empty: set it in {env_file} or in the environment")
        return settings
