from pathlib import Path

from jobbot.claude import StagingSync


def stage(workspace: Path, rel: str, content: str = "x") -> Path:
    path = workspace / ".jobbot-staging" / "claude" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_allowed_files_are_applied_and_removed(tmp_path: Path) -> None:
    src = stage(tmp_path, "skills/job-application-assistant/01-profile.md", "perfil")
    stage(tmp_path, "skills/job-scraper/search-queries.md", "q")
    stage(tmp_path, "skills/upskill/plan.md", "u")
    applied = StagingSync().sync(tmp_path)
    assert len(applied) == 3
    dest = tmp_path / ".claude" / "skills" / "job-application-assistant" / "01-profile.md"
    assert dest.read_text() == "perfil"
    assert not src.exists()


def test_file_outside_allow_list_is_ignored(tmp_path: Path) -> None:
    stage(tmp_path, "settings.json", "{}")
    stage(tmp_path, "skills/job-application-assistant/SKILL.md", "no")
    assert StagingSync().sync(tmp_path) == []
    assert not (tmp_path / ".claude").exists()


def test_symlink_is_ignored(tmp_path: Path) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("segredo")
    link = tmp_path / ".jobbot-staging" / "claude" / "skills" / "upskill" / "leak.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(secret)
    assert StagingSync().sync(tmp_path) == []
    assert not (tmp_path / ".claude" / "skills" / "upskill" / "leak.md").exists()
    assert link.is_symlink()


def test_missing_staging_dir(tmp_path: Path) -> None:
    assert StagingSync().sync(tmp_path) == []


def test_match_is_anchored_and_segment_exact(tmp_path: Path) -> None:
    stage(tmp_path, "a/skills/upskill/y.md")
    stage(tmp_path, "skills/upskill/sub/x.md")
    stage(tmp_path, "skills/upskill.md")
    stage(tmp_path, "skills/job-application-assistant/sub/01.md")
    assert StagingSync().sync(tmp_path) == []
    assert not (tmp_path / ".claude").exists()
