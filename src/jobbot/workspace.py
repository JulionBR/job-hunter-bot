"""Candidate workspaces: slug, provisioning from the reference clone, profile readiness."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from jobbot.models import User
from jobbot.storage import JsonStore

log = logging.getLogger("jobbot")


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


FRONTMATTER_FENCE = "---"
BOM = "\ufeff"
_VALUE = r"(?P<value>\"[^\"]*\"|'[^']*'|[^#\s]*)"
_AUDIENCE_LINE = re.compile(rf"^audience:[ \t]*{_VALUE}")
_ENABLED_LINE = re.compile(rf"^(?P<head>enabled:[ \t]*){_VALUE}(?P<rest>.*)$")


def _scalar(raw: str) -> str:
    return raw.strip("'\"").strip().lower()


def _split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body) :]


def _audience_tag(text: str) -> str | None:
    """The ``audience:`` tag of a portal's frontmatter, or None (same tolerance as ``_set_enabled``)."""
    lines = text.removeprefix(BOM).splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return None
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_FENCE:
            return None
        match = _AUDIENCE_LINE.match(line)
        if match:
            return _scalar(match.group("value")) or None
    return None


def _set_enabled(text: str, audiences: Mapping[str, bool]) -> tuple[bool, str | None]:
    """Set the frontmatter ``enabled:`` line(s) of a portal whose ``audience:`` tag is in ``audiences``.

    Returns ``(is_portal, new_text)``; ``new_text`` is None when nothing has to change. Only the
    ``enabled:`` value changes (trailing comment and line endings are kept); a missing line is inserted
    right after ``audience:``. Repeated ``enabled:`` keys are all updated.
    """
    bom = BOM if text.startswith(BOM) else ""
    lines = text[len(bom) :].splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return False, None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == FRONTMATTER_FENCE), None)
    if end is None:
        return False, None
    aud = None
    enabled = False
    for i in range(1, end):
        match = _AUDIENCE_LINE.match(lines[i])
        if match:
            tag = _scalar(match.group("value"))
            if tag in audiences:
                aud, enabled = i, audiences[tag]
                break
    if aud is None:
        return False, None
    word = "true" if enabled else "false"
    changed = False
    found = False
    for i in range(1, end):
        body, eol = _split_eol(lines[i])
        match = _ENABLED_LINE.match(body)
        if match is None:
            continue
        found = True
        if _scalar(match.group("value")) != word:
            lines[i] = f"{match.group('head')}{word}{match.group('rest')}{eol}"
            changed = True
    if not found:
        body, eol = _split_eol(lines[aud])
        eol = eol or ("\r\n" if "\r\n" in lines[0] else "\n")
        lines[aud] = body + eol
        lines.insert(aud + 1, f"enabled: {word}{eol}")
        changed = True
    return True, (bom + "".join(lines)) if changed else None


def _write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` through a temp file in the same folder, keeping its mode and line endings."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".SKILL-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _portal_files(workspace: Path, chat_id: int) -> Iterator[tuple[Path, str]]:
    """Yield ``(SKILL.md, text)`` of every readable portal in the workspace, skipping symlinks."""
    agents = workspace / ".agents"
    skills = agents / "skills"
    for folder in (agents, skills):
        if folder.is_symlink():
            log.warning(f"portais {chat_id}: {folder} é symlink, ignorado")
            return
    if not skills.is_dir():
        return
    for skill in sorted(skills.glob("*/SKILL.md")):
        if skill.parent.is_symlink() or skill.is_symlink():
            log.warning(f"portal {skill} é symlink, ignorado")
            continue
        try:
            with skill.open(encoding="utf-8", newline="") as f:
                yield skill, f.read()
        except (OSError, UnicodeError) as ex:
            log.warning(f"portal {skill} ignorado: {ex}")


class PortalAudience:
    """Turns audience-restricted portals on or off per candidate.

    A portal declares ``audience: <x>`` in the frontmatter of its ``.agents/skills/<portal>/SKILL.md``;
    ``/scrape`` skips it when the frontmatter has ``enabled: false``. Tags are free-form (``pcd``, ``ti``...);
    a tag the user has no value for is left alone.
    """

    def tags(self, workspace: Path, chat_id: int = 0) -> set[str]:
        """Every ``audience:`` tag declared by the portals installed in ``workspace``."""
        found: set[str] = set()
        for _, text in _portal_files(workspace, chat_id):
            tag = _audience_tag(text)
            if tag:
                found.add(tag)
        return found

    def sync(self, user: User, only: str | None = None) -> int:
        """Apply ``user.audiences`` to the matching portals of the workspace; returns how many were found.

        ``only`` restricts the pass to one tag. Tags the user has no value for are left alone (count 0).
        """
        audiences = dict(user.audiences)
        if only is not None:
            audiences = {only: audiences[only]} if only in audiences else {}
        if not audiences:
            return 0
        count = 0
        for skill, text in _portal_files(user.workspace, user.chat_id):
            try:
                is_portal, updated = _set_enabled(text, audiences)
                if is_portal:
                    count += 1
                if updated is not None:
                    _write_atomic(skill, updated)
                    log.info(f"portal {skill.parent.name} {user.chat_id}: audiences={audiences}")
            except (OSError, UnicodeError) as ex:
                log.warning(f"portal {skill} ignorado: {ex}")
        return count
