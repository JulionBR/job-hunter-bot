import fcntl
import stat
from pathlib import Path

from conftest import FakeTelegram
from jobbot.claude import ClaudeRunner
from jobbot.telegram import Notifier


def fake_cli(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fakeclaude"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def make_runner(tmp_path: Path, body: str) -> tuple[ClaudeRunner, FakeTelegram]:
    state = tmp_path / "state"
    state.mkdir()
    telegram = FakeTelegram()
    return ClaudeRunner(state, Notifier(telegram, [1001]), executable=fake_cli(tmp_path, body)), telegram


def test_run_passes_arguments_and_syncs_staging(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    stage = workspace / ".jobbot-staging" / "claude" / "skills" / "upskill"
    stage.mkdir(parents=True)
    (stage / "plan.md").write_text("p")
    runner, _ = make_runner(tmp_path, 'echo "$@"')
    result = runner.run("oi", workspace, session="abc", resume=True)
    assert result.ok
    assert result.output.startswith("-p oi --permission-mode acceptEdits --append-system-prompt")
    assert result.output.strip().endswith("--resume abc")
    assert (workspace / ".claude" / "skills" / "upskill" / "plan.md").exists()
    assert "--session-id" in runner.run("oi", workspace, session="abc").output


def test_expired_token_alerts_admins(tmp_path: Path) -> None:
    runner, telegram = make_runner(tmp_path, "echo '401 unauthorized'; exit 1")
    result = runner.run("oi", tmp_path)
    assert not result.ok
    assert "token do Claude" in telegram.last(1001)


def test_other_failure_does_not_alert(tmp_path: Path) -> None:
    runner, telegram = make_runner(tmp_path, "echo boom; exit 1")
    assert not runner.run("oi", tmp_path).ok
    assert telegram.messages == []


def test_timeout(tmp_path: Path) -> None:
    runner, _ = make_runner(tmp_path, "sleep 5")
    result = runner.run("oi", tmp_path, timeout=1)
    assert not result.ok and result.output == "Tempo esgotado."


def test_is_busy_reflects_the_lock(tmp_path: Path) -> None:
    runner, _ = make_runner(tmp_path, "true")
    assert not runner.is_busy()
    with (tmp_path / "state" / "claude.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert runner.is_busy()
    with runner.exclusive():
        assert runner.is_busy()


def test_system_note_is_appended_after_staging_and_base_notes(tmp_path: Path) -> None:
    from jobbot.prompts import BASE_NOTE, STAGING_NOTE

    runner, _ = make_runner(tmp_path, 'for a in "$@"; do last="$a"; done; printf %s "$last" > args.txt')
    workspace = tmp_path / "ws"
    workspace.mkdir()
    runner.run("oi", workspace, system="EXTRA")
    assert (workspace / "args.txt").read_text() == f"{STAGING_NOTE}\n\n{BASE_NOTE}\n\nEXTRA"
    runner.run("oi", workspace)
    assert (workspace / "args.txt").read_text() == f"{STAGING_NOTE}\n\n{BASE_NOTE}"


def test_tmp_folder_is_removed_after_run(tmp_path: Path) -> None:
    runner, _ = make_runner(tmp_path, "mkdir -p .jobbot-tmp; echo x > .jobbot-tmp/a.json")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert runner.run("oi", workspace).ok
    assert not (workspace / ".jobbot-tmp").exists()
