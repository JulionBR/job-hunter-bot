"""Candidate workspaces: slug, provisioning from the reference clone, profile readiness."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from jobbot.storage import JsonStore


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:30] or "candidato"


PROFILE_FILES = (
    "CLAUDE.md",
    ".claude/skills/job-application-assistant/01-candidate-profile.md",
    ".claude/skills/job-application-assistant/04-job-evaluation.md",
    ".claude/skills/job-scraper/search-queries.md",
)
TOOLS_COPIED = (".claude/settings.json", "tools/security_guards.py", "tools/jobbot_tex.py")


def profile_ready(workspace: Path) -> bool:
    """Profile ready = the main files exist and no longer hold template placeholders."""
    files = [Path(workspace) / f for f in PROFILE_FILES]
    return all(f.exists() and "[YOUR_" not in f.read_text() for f in files)


class Provisioner(Protocol):
    def create_folder(self, workspace: Path) -> None: ...


class WorkspaceProvisioner:
    """Clean clone of ai-job-search plus portals, permissions and guards from the reference folder."""

    def __init__(
        self,
        home: Path,
        reference: Path,
        candidates_dir: Path,
        store: JsonStore,
        exclusive: Callable[[], AbstractContextManager[None]],
    ) -> None:
        self._home = home
        self._reference = reference
        self._candidates_dir = candidates_dir
        self._store = store
        self._exclusive = exclusive

    def create_folder(self, workspace: Path) -> None:
        self._candidates_dir.mkdir(parents=True, exist_ok=True)
        if not workspace.exists():
            url = subprocess.run(
                ["git", "-C", str(self._reference), "remote", "get-url", "upstream"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "clone", "-q", "--depth", "1", url, str(workspace)], check=True, timeout=600
            )
        shutil.copytree(self._reference / ".agents", workspace / ".agents", symlinks=True, dirs_exist_ok=True)
        for rel in TOOLS_COPIED:
            shutil.copy2(self._reference / rel, workspace / rel)
        exclude = workspace / ".git" / "info" / "exclude"
        if exclude.parent.exists() and (not exclude.exists() or ".jobbot-*" not in exclude.read_text()):
            with exclude.open("a") as f:
                f.write("\n.jobbot-*\n")
        (workspace / "documents" / "cv").mkdir(parents=True, exist_ok=True)
        self._trust(workspace)

    def _trust(self, workspace: Path) -> None:
        """Without the folder marked as trusted, ``claude -p`` ignores the settings.json permissions."""
        with self._exclusive():
            cfg = self._home / ".claude.json"
            data = self._store.read(cfg, {})
            data.setdefault("projects", {}).setdefault(str(workspace), {})["hasTrustDialogAccepted"] = True
            self._store.write(cfg, data)
            os.chmod(cfg, 0o600)
