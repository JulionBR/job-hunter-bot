import os
from pathlib import Path

from conftest import ADMIN, ALICE, Env
from jobbot.models import JobStatus
from jobbot.prompts import APPLY_NOTE, GUPY_NOTE
from jobbot.storage import JobRepository


def prepare(env: Env) -> str:
    env.add_candidate()
    env.app.search.run()
    return JobRepository(env.app.store, ALICE).all()[0].job_id


def test_apply_sends_pdfs_gupy_text_and_marks_generated(env: Env) -> None:
    job_id = prepare(env)
    env.callback(ALICE, f"a:{job_id}")
    assert env.telegram.answers[-1][1] == "Na fila (posição 1)."
    assert JobRepository(env.app.store, ALICE).get(job_id).status is JobStatus.QUEUED  # type: ignore[union-attr]
    env.run_queue()
    job = JobRepository(env.app.store, ALICE).get(job_id)
    assert job is not None and job.status is JobStatus.GENERATED
    assert [c for c, _ in env.telegram.documents] == [ALICE]
    assert env.telegram.documents[0][1].name == "a.pdf"
    summary, gupy = env.telegram.plain[-2:]
    assert summary.text == "texto"
    assert gupy.text.startswith("Texto para a Gupy (copie e cole):\n\ntexto")
    apply_call, gupy_call = env.claude.calls[-2:]
    assert apply_call["prompt"] == "/apply https://a/1"
    assert apply_call["system"] == APPLY_NOTE
    assert gupy_call["system"] == GUPY_NOTE
    assert gupy_call["resume"] is True and gupy_call["timeout"] == 600
    assert gupy_call["session"] == apply_call["session"]
    last = env.telegram.messages[-1]
    assert "Pronto. Confira os PDFs" in last.text
    assert last.markup is not None
    assert last.markup["inline_keyboard"][0][0]["callback_data"] == f"d:{job_id}"


def test_old_pdfs_are_not_resent(env: Env) -> None:
    job_id = prepare(env)
    workspace = env.app.users.get(ALICE).workspace  # type: ignore[union-attr]
    (workspace / "cv").mkdir()
    old = workspace / "cv" / "old.pdf"
    old.write_bytes(b"%PDF")

    os.utime(old, (1, 1))
    env.app.applications.apply_job(ALICE, job_id)
    assert [p.name for _, p in env.telegram.documents] == ["a.pdf"]


def test_apply_failure_marks_error_and_alerts_admin(env: Env) -> None:
    job_id = prepare(env)
    env.claude.ok = False
    env.claude.output = "falha feia"
    env.app.applications.apply_job(ALICE, job_id)
    job = JobRepository(env.app.store, ALICE).get(job_id)
    assert job is not None and job.status is JobStatus.ERROR
    assert "Não consegui gerar os PDFs" in env.telegram.last(ALICE)
    retry = env.telegram.messages[-1].markup
    assert retry is not None
    button = retry["inline_keyboard"][0][0]
    assert button == {"text": "🔁 Tentar de novo", "callback_data": f"a:{job_id}"}
    assert env.telegram.plain == [] and env.telegram.documents == []
    admin_text = env.telegram.last(ADMIN)
    assert "/apply falhou para Alice" in admin_text and "falha feia" in admin_text
    assert "Mais em /log erros" in admin_text


def test_apply_without_pdfs_counts_as_failure(env: Env) -> None:
    job_id = prepare(env)
    env.claude.on_run = lambda prompt, cwd: [f.unlink() for f in cwd.rglob("*.pdf")] and None
    env.app.applications.apply_job(ALICE, job_id)
    job = JobRepository(env.app.store, ALICE).get(job_id)
    assert job is not None and job.status is JobStatus.ERROR


def test_symlinked_and_outside_pdfs_are_not_sent(env: Env, tmp_path: Path) -> None:
    job_id = prepare(env)
    workspace = env.app.users.get(ALICE).workspace  # type: ignore[union-attr]
    secret = tmp_path / "outside" / "secret.pdf"
    secret.parent.mkdir()
    secret.write_bytes(b"%PDF-secret")
    (workspace / "cover_letters").mkdir()
    (workspace / "cover_letters" / "leak.pdf").symlink_to(secret)
    (workspace / "documents" / "applications").mkdir(parents=True)
    (workspace / "documents" / "applications" / "dir-leak").symlink_to(secret.parent)
    (workspace / "cv").mkdir()
    (workspace / "cv" / "broken.pdf").symlink_to(tmp_path / "missing.pdf")
    env.app.applications.apply_job(ALICE, job_id)
    assert [p.name for _, p in env.telegram.documents] == ["a.pdf"]


def test_skip_and_sent_callbacks(env: Env) -> None:
    job_id = prepare(env)
    env.callback(ALICE, f"s:{job_id}")
    assert env.telegram.answers[-1][1] == "Pulada."
    assert JobRepository(env.app.store, ALICE).get(job_id).status is JobStatus.SKIPPED  # type: ignore[union-attr]
    env.callback(ALICE, f"d:{job_id}")
    assert env.telegram.answers[-1][1].startswith("Marcada como enviada")
    assert JobRepository(env.app.store, ALICE).get(job_id).status is JobStatus.SENT  # type: ignore[union-attr]
    assert env.telegram.cleared == [(ALICE, 5), (ALICE, 5)]


def test_callback_unknown_job_and_unknown_user(env: Env) -> None:
    prepare(env)
    env.callback(ALICE, "a:nope")
    assert env.telegram.answers[-1][1] == "Vaga não encontrada."
    assert env.telegram.cleared == []
    env.callback(9999, "a:nope")
    assert env.telegram.answers[-1][1] == "Acesso não liberado."


def test_worker_reports_exceptions_to_the_chat(env: Env) -> None:
    env.app.worker.submit("boom", lambda: 1 / 0, ALICE)
    env.app.worker.process_next()
    assert env.telegram.last(ALICE) == "❌ Erro: division by zero"
    assert env.app.worker.current_task() is None


def test_apply_ignores_missing_job(env: Env) -> None:
    env.add_candidate()
    env.app.applications.apply_job(ALICE, "nope")
    assert env.claude.calls == []
