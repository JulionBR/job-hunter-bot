import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import write_profile
from jobbot.storage import JsonStore
from jobbot.workspace import PROFILE_FILES, WorkspaceProvisioner, profile_ready, slugify


def test_slugify() -> None:
    assert slugify("Maria José da Silva") == "maria-jose-da-silva"
    assert slugify("!!!") == "candidato"
    assert len(slugify("a" * 80)) == 30


def test_profile_ready(tmp_path: Path) -> None:
    assert not profile_ready(tmp_path)
    write_profile(tmp_path)
    assert profile_ready(tmp_path)
    (tmp_path / PROFILE_FILES[0]).write_text("# [YOUR_NAME]")
    assert not profile_ready(tmp_path)
    write_profile(tmp_path, placeholder="x [YOUR_STACK] y")
    assert not profile_ready(tmp_path)
    write_profile(tmp_path)
    (tmp_path / PROFILE_FILES[3]).unlink()
    assert not profile_ready(tmp_path)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_provisioner_clones_local_upstream_and_marks_trust(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q", str(upstream)], check=True)
    (upstream / "README.md").write_text("upstream")
    (upstream / ".claude").mkdir()
    (upstream / ".claude" / "keep.md").write_text("k")
    (upstream / "tools").mkdir()
    (upstream / "tools" / "keep.md").write_text("k")
    subprocess.run([*git, "-C", str(upstream), "add", "."], check=True)
    subprocess.run([*git, "-C", str(upstream), "commit", "-q", "-m", "init"], check=True)

    home = tmp_path / "home"
    reference = home / "ai-job-search"
    (reference / ".agents" / "skills").mkdir(parents=True)
    (reference / ".agents" / "skills" / "s.md").write_text("skill")
    (reference / ".claude").mkdir()
    (reference / ".claude" / "settings.json").write_text("{}")
    (reference / "tools").mkdir()
    (reference / "tools" / "security_guards.py").write_text("# guards")
    (reference / "tools" / "jobbot_tex.py").write_text("# tex")
    subprocess.run(["git", "init", "-q", str(reference)], check=True)
    subprocess.run(["git", "-C", str(reference), "remote", "add", "upstream", str(upstream)], check=True)

    from contextlib import nullcontext

    store = JsonStore(tmp_path / "state")
    provisioner = WorkspaceProvisioner(home, reference, home / "candidatos", store, nullcontext)
    workspace = home / "candidatos" / "alice-2002"
    provisioner.create_folder(workspace)

    assert (workspace / "README.md").read_text() == "upstream"
    assert (workspace / ".agents" / "skills" / "s.md").exists()
    assert (workspace / ".claude" / "settings.json").exists()
    assert (workspace / "tools" / "security_guards.py").exists()
    assert (workspace / "tools" / "jobbot_tex.py").read_text() == "# tex"
    exclude = workspace / ".git" / "info" / "exclude"
    assert exclude.read_text().count(".jobbot-*") == 1
    assert (workspace / "documents" / "cv").is_dir()
    cfg = home / ".claude.json"
    assert json.loads(cfg.read_text())["projects"][str(workspace)]["hasTrustDialogAccepted"] is True
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    provisioner.create_folder(workspace)  # idempotent on an existing folder
    assert exclude.read_text().count(".jobbot-*") == 1
