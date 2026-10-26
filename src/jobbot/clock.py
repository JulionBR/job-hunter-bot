"""Time helpers bound to the configured timezone."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

QUIET_BEFORE_HOUR = 8


class Clock:
    """Wall clock in the bot's timezone (injectable, so tests do not depend on the real time)."""

    def __init__(self, tz: ZoneInfo) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)

    def today(self) -> str:
        """Day label used in messages and in the manual-search limit (``dd/mm``)."""
        return self.now().strftime("%d/%m")

    def stamp(self) -> str:
        """Day and time label for access requests (``dd/mm HH:MM``)."""
        return self.now().strftime("%d/%m %H:%M")

    def is_quiet(self) -> bool:
        """Overnight, notifications go out without sound."""
        return self.now().hour < QUIET_BEFORE_HOUR
