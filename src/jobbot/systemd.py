"""systemd queries (infrastructure): used by /saude to show the search timer."""

from __future__ import annotations

import subprocess


def systemctl_show(unit: str, prop: str) -> str:
    """``systemctl show <unit> -p <prop> --value``, or an em dash if it fails or is empty."""
    try:
        out = subprocess.run(
            ["systemctl", "show", unit, "-p", prop, "--value"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return "—"
    return out or "—"
