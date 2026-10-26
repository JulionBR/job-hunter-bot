import os
from pathlib import Path

import pytest

from jobbot.config import ConfigError, Settings, parse_admin_ids, parse_env_text


def test_parse_env_text_ignores_comments_and_garbage() -> None:
    text = "# comment\n\nA=1\n  B = two words \nnoequals\nC=x=y\n=novalue\n"
    assert parse_env_text(text) == {"A": "1", "B": "two words", "C": "x=y"}


def test_parse_admin_ids() -> None:
    assert parse_admin_ids("1001, 1002,,") == frozenset({1001, 1002})
    assert parse_admin_ids("") == frozenset()


def test_from_env_defaults() -> None:
    s = Settings.from_env({})
    assert s.home == Path("/home/jobbot")
    assert s.top_n == 5
    assert s.delivery_hour == 7
    assert s.admin_ids == frozenset()
    assert s.tz.key == "America/Sao_Paulo"


def test_derived_paths() -> None:
    s = Settings.from_env({"JOBBOT_HOME": "/srv/x"})
    assert s.reference_workspace == Path("/srv/x/ai-job-search")
    assert s.candidates_dir == Path("/srv/x/candidatos")
    assert s.state_dir == Path("/srv/x/jobbot/state")
    assert s.env_file == Path("/srv/x/.config/jobbot/env")


def test_delivery_hour_legacy_name() -> None:
    assert Settings.from_env({"JOBBOT_ENVIO_HORA": "9"}).delivery_hour == 9
    both = {"JOBBOT_DELIVERY_HOUR": "6", "JOBBOT_ENVIO_HORA": "9"}
    assert Settings.from_env(both).delivery_hour == 6


def test_load_reads_env_file_without_overriding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".config" / "jobbot" / "env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("TELEGRAM_BOT_TOKEN=from-file\nADMIN_IDS=1001\nJOBBOT_TOP_N=3\n")
    monkeypatch.setenv("JOBBOT_HOME", str(tmp_path))
    monkeypatch.setenv("JOBBOT_TOP_N", "8")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    s = Settings.load()
    assert s.telegram_token == "from-file"
    assert s.admin_ids == frozenset({1001})
    assert s.top_n == 8
    path = os.environ["PATH"]
    assert path.endswith(":/usr/bin")
    assert ".local/bin" in path.split(":")[1]


def test_load_require_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBBOT_HOME", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert Settings.load().telegram_token == ""
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        Settings.load(require_token=True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert Settings.load(require_token=True).telegram_token == "t"
