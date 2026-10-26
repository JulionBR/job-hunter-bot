import json
from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import ADMIN, ALICE, BOB, Env, FixedClock, MakeEnv
from jobbot.models import Job, JobStatus
from jobbot.storage import JobRepository


def alice_jobs(env: Env) -> list:  # type: ignore[type-arg]
    return JobRepository(env.app.store, ALICE).all()


def test_search_delivers_card_and_summarises_to_admin(env: Env) -> None:
    workspace = env.add_candidate()
    env.app.search.run()
    texts = env.texts(ALICE)
    assert "1 vaga(s) nova(s)" in texts[0]
    assert "<b>Analista</b>" in texts[1]
    assert "⭐ Aderência: 8/10" in texts[1]
    card = [m for m in env.telegram.messages if m.chat == ALICE][-1]
    assert card.markup is not None
    job = alice_jobs(env)[0]
    assert [b["callback_data"] for b in card.markup["inline_keyboard"][0]] == [
        f"a:{job.job_id}",
        f"s:{job.job_id}",
    ]
    assert job.status is JobStatus.NEW
    assert "Busca concluída" in env.telegram.last(ADMIN)
    assert "Alice: 1" in env.telegram.last(ADMIN)
    assert "envio às" not in env.telegram.last(ADMIN)
    call = env.claude.calls[0]
    assert call["cwd"] == workspace and call["timeout"] == 5400
    assert "até 5 melhores" in call["prompt"]


def test_duplicate_search_says_nothing_new(env: Env) -> None:
    env.add_candidate()
    env.app.search.run()
    env.app.search.run()
    assert "nenhuma vaga nova" in env.telegram.last(ALICE)
    assert len(alice_jobs(env)) == 1


def test_failed_search_tells_user(env: Env) -> None:
    env.add_candidate()
    env.claude.items = None
    env.app.search.run()
    assert "A busca de vagas de hoje falhou" in env.telegram.last(ALICE)
    assert "Alice: falhou" in env.telegram.last(ADMIN)


def test_legacy_portuguese_shortlist_keys_are_accepted(env: Env) -> None:
    env.add_candidate()
    env.claude.items = [
        {"titulo": "Dev", "empresa": "Y", "local": "RJ", "url": "https://b/2", "nota": "9/10"}
    ]
    env.app.search.run()
    assert "<b>Dev</b>" in env.texts(ALICE)[1]


def test_item_without_url_is_ignored(env: Env) -> None:
    env.add_candidate()
    env.claude.items = [{"title": "Sem link"}]
    env.app.search.run()
    assert "nenhuma vaga nova" in env.telegram.last(ALICE)


def test_error_in_one_candidate_does_not_stop_others(env: Env) -> None:
    env.add_candidate()
    env.add_candidate(BOB, "Bob")
    env.claude.on_run = lambda prompt, cwd: (cwd / ".jobbot-shortlist.json").write_text(json.dumps([1]))
    env.app.search.run()
    assert "Alice: erro; Bob: erro" in env.telegram.last(ADMIN)


def test_summary_without_ready_candidates(env: Env) -> None:
    env.add_candidate(ready=False)
    env.app.search.run()
    assert "nenhum candidato com perfil pronto" in env.telegram.last(ADMIN)
    assert env.claude.calls == []


def test_summary_is_skipped_only_when_requester_is_admin(env: Env) -> None:
    env.add_candidate()
    env.add_candidate(ADMIN, "Root")
    env.app.search.run(ALICE, True)
    assert "1 vaga(s) nova(s)" in env.texts(ALICE)[0]
    assert sum("Busca concluída" in t for t in env.texts(ADMIN)) == 1
    env.app.search.run(ADMIN, True)
    assert sum("Busca concluída" in t for t in env.texts(ADMIN)) == 1


def test_busy_lock_warns_requester(env: Env) -> None:
    import fcntl

    env.add_candidate()
    with (env.app.store.state_dir / "daily.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        env.app.search.run(ALICE, True)
        env.app.search.run()
    assert env.texts(ALICE) == ["⏳ Já tem uma busca rodando. As vagas chegam quando ela terminar."]
    assert env.claude.calls == []


def test_manual_search_limit_one_per_day_except_admin(env: Env) -> None:
    env.add_candidate()
    env.message(ALICE, "/buscar")
    assert "Buscando vagas agora" in env.texts(ALICE)[0]
    env.message(ALICE, "/buscar")
    assert "já fez uma busca" in env.telegram.last(ALICE)
    assert len(env.claude.calls) == 1


def test_admin_manual_search_has_no_limit(env: Env) -> None:
    env.add_candidate(ADMIN, "Root")
    env.message(ADMIN, "/buscar")
    env.message(ADMIN, "/buscar 2002")  # not a user: falls to the candidate branch
    env.message(ADMIN, "/buscar")
    assert len(env.claude.calls) == 3
    assert "Buscando vagas agora para todos" in env.texts(ADMIN)[0]


def test_admin_search_for_one_user(env: Env) -> None:
    env.add_candidate()
    env.add_candidate(BOB, "Bob")
    env.message(ADMIN, f"/buscar {ALICE}")
    assert f"para {ALICE}" in env.texts(ADMIN)[0]
    assert len(env.claude.calls) == 1
    assert env.texts(BOB) == []


def test_scheduled_search_before_delivery_hour_stores_then_delivers_once(make_env: MakeEnv) -> None:
    env = make_env(delivery_hour=25)
    env.add_candidate()
    env.app.search.run()
    assert env.texts(ALICE) == []
    user = env.app.users.get(ALICE)
    assert user is not None and user.pending_result == "1"
    assert alice_jobs(env)[0].status is JobStatus.WAITING
    assert "envio às 25h" in env.telegram.last(ADMIN)

    env.app.search.deliver_pending()
    assert "1 vaga(s) nova(s)" in env.texts(ALICE)[0]
    user = env.app.users.get(ALICE)
    assert user is not None and user.pending_result is None
    assert alice_jobs(env)[0].status is JobStatus.NEW

    env.app.search.run()
    env.app.search.deliver_pending()
    assert "nenhuma vaga nova" in env.telegram.last(ALICE)
    delivered = len(env.texts(ALICE))
    env.app.search.deliver_pending()
    assert len(env.texts(ALICE)) == delivered


def test_manual_search_delivers_immediately_even_before_hour(make_env: MakeEnv) -> None:
    env = make_env(delivery_hour=25)
    env.add_candidate()
    env.app.search.run(ALICE, True)
    assert "1 vaga(s) nova(s)" in env.texts(ALICE)[0]
    assert alice_jobs(env)[0].status is JobStatus.NEW
    user = env.app.users.get(ALICE)
    assert user is not None and user.pending_result is None


def test_failed_scheduled_search_is_reported_at_delivery(make_env: MakeEnv) -> None:
    env = make_env(delivery_hour=25)
    env.add_candidate()
    env.claude.items = None
    env.app.search.run()
    user = env.app.users.get(ALICE)
    assert user is not None and user.pending_result == "falhou"
    env.app.search.deliver_pending()
    assert "falhou" in env.telegram.last(ALICE)


def test_summary_is_silent_overnight_and_audible_by_day(make_env: MakeEnv) -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    for hour, silent in ((3, True), (12, False)):
        env = make_env(clock=FixedClock(tz, datetime(2026, 1, 10, hour, 0)))
        env.add_candidate()
        env.app.search.run()
        assert env.telegram.messages[-1].silent is silent
        assert "Busca concluída" in env.telegram.last(ADMIN)


def test_shortlist_cannot_inject_status_or_job_id(env: Env) -> None:
    env.add_candidate()
    env.claude.items = [
        {
            "title": "Dev",
            "url": "https://a/9",
            "status": "gerada",
            "job_id": "x" * 80,
        },
        {"title": "no url", "status": "new"},
    ]
    env.app.search.run()
    jobs = alice_jobs(env)
    assert len(jobs) == 1
    assert jobs[0].job_id == Job.id_for("https://a/9") and len(jobs[0].job_id) == 10
    assert jobs[0].status is JobStatus.NEW
    card = [m for m in env.telegram.messages if m.chat == ALICE][-1]
    assert card.markup is not None
    assert card.markup["inline_keyboard"][0][0]["callback_data"] == f"a:{jobs[0].job_id}"


def test_shortlist_status_new_does_not_break_stored_state(env: Env) -> None:
    env.add_candidate()
    env.claude.items = [{"title": "Dev", "url": "https://a/8", "status": "new"}]
    env.app.search.run()
    assert alice_jobs(env)[0].status is JobStatus.NEW
