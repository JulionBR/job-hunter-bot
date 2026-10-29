from pathlib import Path

import pytest

from conftest import ADMIN, ALICE, BOB, Env
from jobbot.__main__ import add_user
from jobbot.config import Settings
from jobbot.models import User
from jobbot.workspace import PortalAudience

PCD_SKILL = "---\nname: inklua-search\naudience: pcd\n{extra}description: x\n---\n# Body\nenabled: keep\n"


def skill(workspace: Path, name: str, text: str) -> Path:
    path = workspace / ".agents" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def user(workspace: Path, pcd: bool | None) -> User:
    return User(ALICE, "Alice", workspace, pcd=pcd)


def test_inserts_enabled_after_audience(tmp_path: Path) -> None:
    path = skill(tmp_path, "inklua-search", PCD_SKILL.format(extra=""))
    PortalAudience().sync(user(tmp_path, False))
    assert path.read_text() == (
        "---\nname: inklua-search\naudience: pcd\nenabled: false\n"
        "description: x\n---\n# Body\nenabled: keep\n"
    )


def test_replaces_existing_enabled_and_only_writes_on_change(tmp_path: Path) -> None:
    path = skill(tmp_path, "inklua-search", PCD_SKILL.format(extra="enabled: false\n"))
    PortalAudience().sync(user(tmp_path, True))
    assert "audience: pcd\nenabled: true\ndescription" in path.read_text()
    assert path.read_text().endswith("# Body\nenabled: keep\n")
    mtime = path.stat().st_mtime_ns
    PortalAudience().sync(user(tmp_path, True))
    assert path.stat().st_mtime_ns == mtime


def test_portal_without_audience_is_untouched(tmp_path: Path) -> None:
    text = "---\nname: gupy-search\n---\nbody\n"
    other = skill(tmp_path, "gupy-search", text)
    PortalAudience().sync(user(tmp_path, False))
    assert other.read_text() == text


def test_unknown_pcd_touches_nothing(tmp_path: Path) -> None:
    text = PCD_SKILL.format(extra="enabled: true\n")
    path = skill(tmp_path, "inklua-search", text)
    PortalAudience().sync(user(tmp_path, None))
    assert path.read_text() == text


def test_symlink_is_ignored(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    real.write_text(PCD_SKILL.format(extra="enabled: true\n"))
    link = tmp_path / ".agents" / "skills" / "linked" / "SKILL.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    PortalAudience().sync(user(tmp_path, False))
    assert "enabled: true" in real.read_text()


def test_malformed_files_do_not_break_sync(tmp_path: Path) -> None:
    bad = tmp_path / ".agents" / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"---\naudience: pcd\n\xff\xfe\n---\n")
    skill(tmp_path, "unclosed", "---\naudience: pcd\nno end\n")
    skill(tmp_path, "empty", "")
    good = skill(tmp_path, "good", PCD_SKILL.format(extra=""))
    PortalAudience().sync(user(tmp_path, False))
    assert "enabled: false" in good.read_text()


def test_admin_pcd_command_saves_and_syncs(env: Env) -> None:
    path = skill(env.add_candidate(), "inklua-search", PCD_SKILL.format(extra="enabled: false\n"))
    env.message(ADMIN, f"/pcd {ALICE} sim")
    stored = env.app.users.get(ALICE)
    assert stored is not None and stored.pcd is True
    assert "enabled: true" in path.read_text()
    assert "PcD sim, 1 portal(is) PcD ligados" in env.telegram.last(ADMIN)
    env.message(ADMIN, f"/pcd {ALICE} não")
    assert env.app.users.get(ALICE).pcd is False  # type: ignore[union-attr]
    assert "enabled: false" in path.read_text()
    env.message(ADMIN, f"/pcd {ALICE} s")
    env.message(ADMIN, f"/pcd {ALICE} n")
    assert env.app.users.get(ALICE).pcd is False  # type: ignore[union-attr]


def test_admin_pcd_bad_usage(env: Env) -> None:
    env.add_candidate()
    for arg in ("", str(ALICE), f"{ALICE} talvez", f"{BOB} sim"):
        env.message(ADMIN, f"/pcd {arg}".strip())
        assert env.telegram.last(ADMIN).startswith("Uso: /pcd")
    assert env.app.users.get(ALICE).pcd is None  # type: ignore[union-attr]


def test_non_admin_pcd_is_ignored(env: Env) -> None:
    env.add_candidate()
    env.message(ALICE, f"/pcd {ALICE} sim")
    assert env.app.users.get(ALICE).pcd is None  # type: ignore[union-attr]
    assert not any("PcD" in t for t in env.texts(ALICE))


def test_approve_creates_user_with_pcd_false(env: Env) -> None:
    env.message(BOB, "oi")
    env.callback(ADMIN, f"ok:{BOB}")
    created = env.app.users.get(BOB)
    assert created is not None and created.pcd is False


def test_run_for_syncs_before_claude(env: Env) -> None:
    workspace = env.add_candidate()
    path = skill(workspace, "inklua-search", PCD_SKILL.format(extra="enabled: true\n"))
    env.app.users.update(ALICE, lambda u: setattr(u, "pcd", False))
    seen: list[str] = []
    env.claude.on_run = lambda prompt, cwd: seen.append(path.read_text())
    env.app.search.run()
    assert "enabled: false" in seen[0]


def test_users_summary_shows_pcd(env: Env) -> None:
    env.add_candidate()
    env.add_candidate(BOB, "Bob")
    env.app.users.update(BOB, lambda u: setattr(u, "pcd", True))
    env.message(ADMIN, "/usuarios")
    text = env.telegram.last(ADMIN)
    assert "PcD: ?" in text
    assert "PcD: sim" in text
    env.app.users.update(BOB, lambda u: setattr(u, "pcd", False))
    env.message(ADMIN, "/usuarios")
    assert "PcD: não" in env.telegram.last(ADMIN)


def test_pcd_serialisation() -> None:
    assert "pcd" not in User(1, "a", Path("/w")).to_dict()
    assert User.from_dict(1, {"name": "a"}).pcd is None
    assert User.from_dict(1, User(1, "a", Path("/w"), pcd=False).to_dict()).pcd is False


def test_add_user_pcd_flag_and_preserve(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path, telegram_token="x", admin_ids=frozenset())
    workspace = tmp_path / "w"
    path = skill(workspace, "inklua-search", PCD_SKILL.format(extra="enabled: true\n"))
    assert add_user(settings, 5, "Eve", workspace, True).pcd is None
    assert "enabled: true" in path.read_text()
    assert add_user(settings, 5, "Eve", workspace, True, True).pcd is True
    assert add_user(settings, 5, "Eve", workspace, True).pcd is True
    assert add_user(settings, 5, "Eve", workspace, True, False).pcd is False
    assert "enabled: false" in path.read_text()


def test_audience_comment_quotes_case_and_bom(tmp_path: Path) -> None:
    text = '\ufeff---\nname: x\naudience: "PcD"  # only PcD\n---\nbody\n'
    path = skill(tmp_path, "a", text)
    assert PortalAudience().sync(user(tmp_path, False)) == 1
    assert path.read_text(encoding="utf-8") == (
        '\ufeff---\nname: x\naudience: "PcD"  # only PcD\nenabled: false\n---\nbody\n'
    )
    single = skill(tmp_path, "b", "---\naudience: 'pcd'\nenabled: 'false'\n---\n")
    PortalAudience().sync(user(tmp_path, True))
    assert single.read_text() == "---\naudience: 'pcd'\nenabled: true\n---\n"


def test_crlf_and_enabled_comment_preserved_and_duplicates_updated(tmp_path: Path) -> None:
    path = tmp_path / ".agents" / "skills" / "c" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b"---\r\naudience: pcd\r\nenabled: true  # toggled by bot\r\nenabled: true\r\n---\r\nbody\r\n"
    )
    PortalAudience().sync(user(tmp_path, False))
    assert path.read_bytes() == (
        b"---\r\naudience: pcd\r\nenabled: false  # toggled by bot\r\nenabled: false\r\n---\r\nbody\r\n"
    )
    inserted = tmp_path / ".agents" / "skills" / "d" / "SKILL.md"
    inserted.parent.mkdir(parents=True)
    inserted.write_bytes(b"---\r\naudience: pcd\r\n---\r\n")
    PortalAudience().sync(user(tmp_path, True))
    assert inserted.read_bytes() == b"---\r\naudience: pcd\r\nenabled: true\r\n---\r\n"


def test_sync_counts_portals_and_pcd_command_says_none_installed(env: Env, tmp_path: Path) -> None:
    assert PortalAudience().sync(user(tmp_path, True)) == 0
    assert PortalAudience().sync(user(tmp_path, None)) == 0
    env.add_candidate()
    env.message(ADMIN, f"/pcd {ALICE} sim")
    assert "nenhum portal PcD instalado" in env.telegram.last(ADMIN)


def test_atomic_write_keeps_mode_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = skill(tmp_path, "inklua-search", PCD_SKILL.format(extra=""))
    path.chmod(0o640)
    PortalAudience().sync(user(tmp_path, False))
    assert path.stat().st_mode & 0o777 == 0o640
    assert [f.name for f in path.parent.iterdir()] == ["SKILL.md"]


def test_symlinked_agents_dir_warns_and_is_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    real = tmp_path / "real"
    skill(real, "inklua-search", PCD_SKILL.format(extra="enabled: true\n"))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".agents").symlink_to(real / ".agents")
    with caplog.at_level("WARNING", logger="jobbot"):
        assert PortalAudience().sync(user(ws, False)) == 0
    assert "symlink" in caplog.text
    assert "enabled: true" in (real / ".agents/skills/inklua-search/SKILL.md").read_text()


def test_pcd_only_accepts_real_bool() -> None:
    assert User.from_dict(1, {"pcd": "false"}).pcd is None
    assert User.from_dict(1, {"pcd": 1}).pcd is None
    assert User.from_dict(1, {"pcd": True}).pcd is True


def test_run_for_uses_reloaded_user(env: Env) -> None:
    workspace = env.add_candidate()
    path = skill(workspace, "inklua-search", PCD_SKILL.format(extra="enabled: false\n"))
    stale = env.app.users.get(ALICE)
    assert stale is not None and stale.pcd is None
    env.app.users.update(ALICE, lambda u: setattr(u, "pcd", True))
    env.app.search.run_for(stale, True)
    assert "enabled: true" in path.read_text()


def test_approve_syncs_new_workspace(env: Env) -> None:
    def provision(workspace: Path) -> None:
        skill(workspace, "inklua-search", PCD_SKILL.format(extra="enabled: true\n"))

    original = env.provisioner.create_folder
    env.provisioner.create_folder = lambda w: (original(w), provision(w))[0]  # type: ignore[method-assign]
    env.message(BOB, "oi")
    env.callback(ADMIN, f"ok:{BOB}")
    created = env.app.users.get(BOB)
    assert created is not None
    assert "enabled: false" in (created.workspace / ".agents/skills/inklua-search/SKILL.md").read_text()
