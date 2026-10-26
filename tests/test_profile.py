from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import ADMIN, ALICE, Env, FixedClock, MakeEnv, write_profile
from jobbot.prompts import SETUP_NOTE


def test_profile_not_ready_blocks_manual_search(env: Env) -> None:
    env.add_candidate(ready=False)
    env.message(ALICE, "/buscar")
    assert "Primeiro monte" in env.telegram.last(ALICE)


def test_setup_conversation(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    env.message(ALICE, "/perfil")
    assert "Vamos montar seu perfil" in env.telegram.last(ALICE)
    env.run_queue()
    first = env.claude.calls[-1]
    assert first["resume"] is False
    assert first["timeout"] == 1800
    assert first["system"] == SETUP_NOTE
    assert first["cwd"] == workspace
    assert env.telegram.plain[-1].text == "texto"
    env.message(ALICE, "sou engenheira")
    assert env.telegram.typing == [ALICE]
    env.run_queue()
    second = env.claude.calls[-1]
    assert second["prompt"] == "sou engenheira"
    assert second["resume"] is True
    assert second["system"] == SETUP_NOTE
    assert second["session"] == first["session"]


def test_setup_error_message(env: Env) -> None:
    env.add_candidate(ready=False)
    env.claude.ok = False
    env.message(ALICE, "/perfil")
    env.run_queue()
    assert env.telegram.plain[-1].text.startswith("❌ Deu erro")


def test_finish_marks_profile_ready_and_notifies_admin(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "/perfil")
    env.message(ALICE, "/fim")
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_ready
    assert not env.app.profile.is_active(ALICE)
    assert "Perfil pronto" in env.telegram.last(ALICE)
    assert any("Perfil de Alice pronto" in t for t in env.texts(1001))


def test_finish_incomplete_profile(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace, placeholder="# [YOUR_NAME]")
    env.message(ALICE, "/fim")
    user = env.app.users.get(ALICE)
    assert user is not None and not user.profile_ready
    assert "ainda está incompleto" in env.telegram.last(ALICE)


def test_turn_without_session_is_noop(env: Env) -> None:
    env.add_candidate()
    env.app.profile.turn(ALICE, "oi")
    assert env.claude.calls == []


def test_cv_upload(env: Env) -> None:
    workspace = env.add_candidate()
    env.telegram.files["f1"] = b"%PDF-cv"
    env.message(ALICE, "", document={"file_id": "f1", "file_name": "../cv.pdf"})
    assert (workspace / "documents" / "cv" / "cv.pdf").read_bytes() == b"%PDF-cv"
    assert "Currículo salvo (cv.pdf)" in env.telegram.last(ALICE)
    env.message(ALICE, "", document={"file_id": "f1", "file_name": "virus.exe"})
    assert env.telegram.last(ALICE) == "Mande o currículo em PDF ou Word (.docx)."


def test_profile_session_survives_restart_and_fim_clears_it(env: Env, make_env: MakeEnv) -> None:
    workspace = env.add_candidate(ready=False)
    env.message(ALICE, "/perfil")
    env.run_queue()
    session = env.claude.calls[-1]["session"]
    stored = env.app.users.get(ALICE)
    assert stored is not None and stored.profile_session == session

    restarted = make_env()  # same home: a new process reading the same users.json
    assert restarted.app.profile.is_active(ALICE)
    assert restarted.app.profile.active_count() == 1
    restarted.message(ALICE, "continuando")
    restarted.run_queue()
    assert restarted.claude.calls[-1]["session"] == session
    assert restarted.claude.calls[-1]["resume"] is True

    write_profile(workspace)
    restarted.message(ALICE, "/fim")
    cleared = restarted.app.users.get(ALICE)
    assert cleared is not None and cleared.profile_session is None
    assert not restarted.app.profile.is_active(ALICE)


def test_admin_summary_marks_open_conversation(env: Env) -> None:
    env.add_candidate()
    env.message(ALICE, "/perfil")
    env.message(ADMIN, "/saude")
    assert "Conversas de /perfil abertas: 1" in env.telegram.last(ADMIN)


def test_abandoned_session_expires_after_48h(make_env: MakeEnv) -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    day1 = make_env(clock=FixedClock(tz, datetime(2026, 1, 5, 10, 0)))
    day1.add_candidate(ready=False)
    day1.message(ALICE, "/perfil")
    day1.run_queue()
    calls = len(day1.claude.calls)

    later = make_env(clock=FixedClock(tz, datetime(2026, 1, 6, 9, 0)))  # 23 h later: still open
    assert later.app.profile.is_active(ALICE)

    stale = make_env(clock=FixedClock(tz, datetime(2026, 1, 8, 10, 0)))  # 72 h later: expired
    assert not stale.app.profile.is_active(ALICE)
    assert stale.app.profile.active_count() == 0
    stale.message(ALICE, "obrigada!")
    stale.run_queue()
    assert len(stale.claude.calls) == 0 and calls > 0
    assert "Como funciona" in stale.telegram.last(ALICE)
