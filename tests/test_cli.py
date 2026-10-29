import json
import os
from pathlib import Path

import pytest

from conftest import write_profile
from jobbot.__main__ import main


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated JOBBOT_HOME. ``Settings.load`` writes to os.environ, so every key it may touch is
    registered with monkeypatch first and restored after the test."""
    monkeypatch.setenv("JOBBOT_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", os.environ["PATH"])
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "ADMIN_IDS",
        "JOBBOT_TOP_N",
        "JOBBOT_DELIVERY_HOUR",
        "JOBBOT_ENVIO_HORA",
    ):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def users_json(home: Path) -> dict[str, dict[str, object]]:
    return json.loads((home / "jobbot" / "state" / "users.json").read_text())  # type: ignore[no-any-return]


def test_add_user_computes_profile_ready(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = home / "ws"
    workspace.mkdir()
    write_profile(workspace)
    assert main(["add-user", "--chat-id", "2002", "--name", "Alice", "--workspace", str(workspace)]) == 0
    data = users_json(home)["2002"]
    assert data["name"] == "Alice" and data["workspace"] == str(workspace)
    assert data["profile_ready"] is True
    assert "registered Alice" in capsys.readouterr().out


def test_add_user_not_ready_without_profile(home: Path) -> None:
    workspace = home / "ws"
    workspace.mkdir()
    main(["add-user", "--chat-id", "2003", "--name", "Bob", "--workspace", str(workspace)])
    assert users_json(home)["2003"]["profile_ready"] is False


def test_add_user_flag_forces_ready_and_keeps_existing_state(home: Path) -> None:
    workspace = home / "ws"
    workspace.mkdir()
    args = ["add-user", "--chat-id", "2004", "--name", "Cris", "--workspace", str(workspace)]
    main(args)
    state = home / "jobbot" / "state" / "users.json"
    data = json.loads(state.read_text())
    data["2004"]["manual_search_day"] = "05/05"
    state.write_text(json.dumps(data))
    main([*args, "--profile-ready"])
    after = users_json(home)["2004"]
    assert after["profile_ready"] is True
    assert after["manual_search_day"] == "05/05"


def test_requires_a_command(home: Path) -> None:
    with pytest.raises(SystemExit):
        main([])


def test_aliases_are_accepted() -> None:
    from jobbot.__main__ import build_parser

    parser = build_parser()
    assert parser.parse_args(["daily"]).command == "daily"
    assert parser.parse_args(["enviar"]).command == "enviar"


def test_add_user_resolves_relative_workspace(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (home / "ws").mkdir()
    monkeypatch.chdir(home)
    assert main(["add-user", "--chat-id", "2005", "--name", "Dani", "--workspace", "ws"]) == 0
    assert users_json(home)["2005"]["workspace"] == str((home / "ws").resolve())


def test_add_user_rejects_missing_workspace(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["add-user", "--chat-id", "2006", "--name", "Edu", "--workspace", str(home / "nope")])
    assert code == 1
    assert "workspace folder not found" in capsys.readouterr().err
    assert not (home / "jobbot" / "state" / "users.json").exists()


@pytest.mark.parametrize("command", ["bot", "search", "deliver", "daily", "enviar"])
def test_service_commands_require_the_telegram_token(
    home: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    assert main([command]) == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err


def test_add_user_does_not_need_the_token(home: Path) -> None:
    (home / "ws").mkdir()
    assert main(["add-user", "--chat-id", "2007", "--name", "Fa", "--workspace", str(home / "ws")]) == 0


def _open_session(home: Path, chat: str) -> None:
    state = home / "jobbot" / "state" / "users.json"
    data = json.loads(state.read_text())
    data[chat]["profile_session"] = "uuid-1"
    data[chat]["profile_session_started"] = "2026-01-05T10:00:00-03:00"
    state.write_text(json.dumps(data))


def test_add_user_again_keeps_session_with_its_start_time(home: Path) -> None:
    workspace = home / "ws"
    workspace.mkdir()
    args = ["add-user", "--chat-id", "2005", "--name", "Dani", "--workspace", str(workspace)]
    main(args)
    _open_session(home, "2005")
    main(args)
    after = users_json(home)["2005"]
    assert after["profile_session"] == "uuid-1"
    assert after["profile_session_started"] == "2026-01-05T10:00:00-03:00"


def test_add_user_profile_ready_clears_open_session(home: Path) -> None:
    workspace = home / "ws"
    workspace.mkdir()
    args = ["add-user", "--chat-id", "2006", "--name", "Eli", "--workspace", str(workspace)]
    main(args)
    _open_session(home, "2006")
    main([*args, "--profile-ready"])
    after = users_json(home)["2006"]
    assert after["profile_ready"] is True
    assert "profile_session" not in after and "profile_session_started" not in after
