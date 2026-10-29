from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import ADMIN, ALICE, Env, FixedClock, MakeEnv, write_profile
from jobbot import messages
from jobbot.models import User
from jobbot.prompts import SETUP_NOTE


def test_profile_not_ready_blocks_manual_search(env: Env) -> None:
    env.add_candidate(ready=False)
    env.message(ALICE, "/buscar")
    assert env.telegram.last(ALICE) == messages.PROFILE_FIRST


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
    assert env.telegram.plain[-1].text == messages.PROFILE_ERROR
    assert env.telegram.last(ADMIN) == messages.profile_failed_admin("Alice")
    assert "/log erros" in env.telegram.last(ADMIN)


def test_profile_turn_sends_only_stdout(env: Env) -> None:
    env.add_candidate(ready=False)
    env.claude.output = "Qual é a sua área?"
    env.claude.stderr = "WARNING: update disponível, token sk-fake"
    env.message(ALICE, "/perfil")
    env.run_queue()
    assert [m.text for m in env.telegram.plain] == ["Qual é a sua área?"]


def test_finish_marks_profile_ready_and_notifies_admin(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "/perfil")
    env.message(ALICE, "/fim")
    env.run_queue()
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
    assert env.telegram.last(ALICE) == messages.PROFILE_INCOMPLETE


def test_turn_without_session_is_noop(env: Env) -> None:
    env.add_candidate()
    env.app.profile.turn(ALICE, "oi", "uuid-x")
    assert env.claude.calls == []


def test_cv_upload(env: Env) -> None:
    workspace = env.add_candidate()
    env.telegram.files["f1"] = b"%PDF-cv"
    env.message(ALICE, "", document={"file_id": "f1", "file_name": "../cv.pdf"})
    assert (workspace / "documents" / "cv" / "cv.pdf").read_bytes() == b"%PDF-cv"
    assert env.telegram.last(ALICE) == messages.cv_saved("cv.pdf")
    env.message(ALICE, "", document={"file_id": "f1", "file_name": "virus.exe"})
    assert env.telegram.last(ALICE) == messages.CV_FORMAT


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
    restarted.run_queue()
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


@pytest.mark.parametrize("text", ["Fim", "FIM", " fim. ", "fim!"])
def test_bare_fim_finishes_active_session(env: Env, text: str) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "/perfil")
    env.run_queue()
    calls = len(env.claude.calls)
    env.message(ALICE, text)
    env.run_queue()
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_ready and user.profile_session is None
    assert len(env.claude.calls) == calls
    assert "Perfil pronto" in env.telegram.last(ALICE)


def test_bare_fim_without_session_is_not_finish(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "fim")
    user = env.app.users.get(ALICE)
    assert user is not None and not user.profile_ready
    assert "Perfil pronto" not in env.telegram.last(ALICE)


def test_fim_inside_a_sentence_goes_to_claude(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "/perfil")
    env.run_queue()
    env.message(ALICE, "fim do mês")
    env.run_queue()
    assert env.claude.calls[-1]["prompt"] == "fim do mês"
    user = env.app.users.get(ALICE)
    assert user is not None and not user.profile_ready and user.profile_session is not None


def test_expired_session_is_cleared_and_keeps_profile_ready(make_env: MakeEnv) -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    day1 = make_env(clock=FixedClock(tz, datetime(2026, 1, 5, 10, 0)))
    day1.add_candidate(ready=True)
    day1.message(ALICE, "/perfil")
    stale = make_env(clock=FixedClock(tz, datetime(2026, 1, 8, 10, 0)))
    assert not stale.app.profile.is_active(ALICE)
    user = stale.app.users.get(ALICE)
    assert user is not None and user.profile_ready
    assert user.profile_session is None and user.profile_session_started is None


def test_session_without_start_time_is_treated_as_expired(env: Env) -> None:
    env.add_candidate(ready=True)
    env.app.users.update(ALICE, lambda u: setattr(u, "profile_session", "legacy-uuid"))
    assert not env.app.profile.is_active(ALICE)
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_ready and user.profile_session is None
    env.message(ALICE, "oi")
    env.run_queue()
    assert env.claude.calls == []


def _expired_with_files_on_disk(make_env: MakeEnv) -> Env:
    """Finished the conversation (files saved) but never sent /fim, and the session expired."""
    tz = ZoneInfo("America/Sao_Paulo")
    day1 = make_env(clock=FixedClock(tz, datetime(2026, 1, 5, 10, 0)))
    write_profile(day1.add_candidate(ready=False))
    day1.message(ALICE, "/perfil")
    day1.run_queue()
    return make_env(clock=FixedClock(tz, datetime(2026, 1, 8, 10, 0)))


def test_slash_fim_after_expired_session_marks_profile_ready(make_env: MakeEnv) -> None:
    stale = _expired_with_files_on_disk(make_env)
    stale.message(ALICE, "/fim")
    user = stale.app.users.get(ALICE)
    assert user is not None and user.profile_ready and user.profile_session is None
    assert len(stale.claude.calls) == 0
    assert "Perfil pronto" in stale.telegram.last(ALICE)


def test_bare_fim_after_expired_session_is_not_finish(make_env: MakeEnv) -> None:
    stale = _expired_with_files_on_disk(make_env)
    stale.message(ALICE, "Fim")
    stale.run_queue()
    user = stale.app.users.get(ALICE)
    assert user is not None and not user.profile_ready
    assert len(stale.claude.calls) == 0


@pytest.mark.parametrize("started", ["2026-10-29", "2026-10-29T10:00:00"])
def test_naive_session_start_counts_as_expired_without_error(env: Env, started: str) -> None:
    env.add_candidate(ready=True)

    def naive(u: User) -> None:
        u.profile_session, u.profile_session_started = "uuid-1", started

    env.app.users.update(ALICE, naive)
    assert not env.app.profile.is_active(ALICE)
    env.app.users.update(ALICE, naive)
    env.message(ALICE, "oi")  # must not raise
    env.run_queue()
    assert env.claude.calls == []
    env.app.users.update(ALICE, naive)
    env.message(ADMIN, "/saude")
    env.message(ADMIN, "/usuarios")
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_ready


def test_fim_waits_for_pending_turn_and_final_profile_has_last_answer(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    env.message(ALICE, "/perfil")
    env.run_queue()
    env.claude.on_run = lambda prompt, cwd: write_profile(workspace) if prompt == "ultima resposta" else None
    env.message(ALICE, "ultima resposta")
    env.message(ALICE, "/fim")
    assert env.telegram.last(ALICE) == messages.PROFILE_FINISH_QUEUED
    user = env.app.users.get(ALICE)
    assert user is not None and not user.profile_ready and user.profile_session is not None
    env.run_queue()
    assert env.claude.calls[-1]["prompt"] == "ultima resposta"
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_ready and user.profile_session is None
    assert "Perfil pronto" in env.telegram.last(ALICE)


def test_fim_without_session_keeps_ready_profile_and_does_not_notify_admin(env: Env) -> None:
    workspace = env.add_candidate(ready=True)
    write_profile(workspace, placeholder="# [YOUR_NAME]")
    before = len(env.texts(ADMIN))
    env.message(ALICE, "/fim")
    env.run_queue()
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_ready is True
    assert env.telegram.last(ALICE) == messages.NO_ACTIVE_PROFILE
    assert len(env.texts(ADMIN)) == before


def test_queued_turn_of_replaced_session_does_nothing(env: Env) -> None:
    env.add_candidate(ready=False)
    env.message(ALICE, "/perfil")
    env.message(ALICE, "/perfil")  # first queued turn now belongs to a replaced session
    sessions = [env.app.profile.current_session(ALICE)]
    env.run_queue()
    assert len(env.claude.calls) == 1
    assert env.claude.calls[0]["session"] == sessions[0] and env.claude.calls[0]["resume"] is False
    assert not any(messages.profile_failed_admin("Alice") in t for t in env.texts(ADMIN))


def test_queued_turn_of_closed_session_does_nothing(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "/perfil")
    env.run_queue()
    env.message(ALICE, "mais uma")
    env.app.profile.discard(ALICE)  # session closed before the queued turn runs
    calls = len(env.claude.calls)
    env.run_queue()
    assert len(env.claude.calls) == calls
    assert not any(messages.profile_failed_admin("Alice") in t for t in env.texts(ADMIN))


def test_queued_fim_does_not_close_a_newer_profile_session(env: Env) -> None:
    workspace = env.add_candidate(ready=False)
    write_profile(workspace)
    env.message(ALICE, "/perfil")
    env.message(ALICE, "/fim")  # queued for the first conversation
    env.message(ALICE, "/perfil")  # a new conversation opens before the worker runs the /fim
    newer = env.app.profile.current_session(ALICE)
    env.run_queue()
    user = env.app.users.get(ALICE)
    assert user is not None and user.profile_session == newer and not user.profile_ready
    assert "Perfil pronto" not in env.telegram.last(ALICE)
    assert env.claude.calls[-1]["session"] == newer
