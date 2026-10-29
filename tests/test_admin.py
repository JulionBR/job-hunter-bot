from pathlib import Path

from conftest import ADMIN, ALICE, BOB, Env


def test_users_summary(env: Env) -> None:
    env.message(ADMIN, "/usuarios")
    assert env.telegram.last(ADMIN) == "Nenhum candidato."
    env.add_candidate()
    env.add_candidate(BOB, "Bob", ready=False)
    env.message(BOB, "/perfil")
    env.message(ADMIN, "/usuarios")
    text = env.telegram.last(ADMIN)
    assert "Alice" in text
    assert f"<code>{ALICE}</code> — perfil ✅ · PcD: ?\n  sem vagas ainda" in text
    assert "perfil ⏳ (conversando) · PcD: ?" in text


def test_health(env: Env) -> None:
    env.add_candidate()
    env.message(ADMIN, "/saude")
    text = env.telegram.last(ADMIN)
    assert "Saúde do bot" in text
    assert "Claude: livre · trabalho atual: nenhum · fila: 0" in text
    assert "jobbot-search.timer:NextElapseUSecRealtime" in text
    assert "Candidatos: 1 (1 com perfil pronto) · pedidos pendentes: 0" in text
    assert "Último erro: <code>nenhum</code>" in text
    env.claude.busy = True
    env.message(ADMIN, "/saude")
    assert "Claude: ocupado" in env.telegram.last(ADMIN)


def test_health_shows_current_task_and_last_error(env: Env) -> None:
    env.app.worker.submit("apply_job", lambda: env.message(ADMIN, "/saude"), ALICE)
    env.app.worker.process_next()
    text = env.telegram.last(ADMIN)
    assert f"apply_job para {ALICE} há 0 min" in text
    env.app.worker.submit("boom", lambda: 1 / 0, ALICE)
    env.app.worker.process_next()
    env.message(ADMIN, "/saude")
    assert "boom erro: division by zero" in env.telegram.last(ADMIN)


def test_log_tail_and_errors(env: Env, tmp_path: Path) -> None:
    log = tmp_path / "jobbot" / "state" / "log.txt"
    log.write_text("linha 1\nlinha 2\n")
    env.message(ADMIN, "/log 5")
    assert env.telegram.messages[-1].silent
    assert "linha 2" in env.telegram.last(ADMIN)
    (log.with_suffix(".txt.1")).write_text("[old] claude ok=False: 'antigo'\n")
    env.message(ADMIN, "/log erros")
    assert "antigo" in env.telegram.last(ADMIN)
    env.message(ADMIN, "/log 2")
    assert env.telegram.last(ADMIN).startswith("<pre>")


def test_log_empty_messages(env: Env) -> None:
    import logging

    for handler in logging.getLogger("jobbot").handlers:
        handler.flush()
    log = env.home / "jobbot" / "state" / "log.txt"
    log.write_text("")
    env.message(ADMIN, "/log")
    assert env.telegram.last(ADMIN) == "Log vazio."
    env.message(ADMIN, "/log erros")
    assert env.telegram.last(ADMIN) == "Nenhum erro no log. 🎉"


def test_log_tail_caps_and_truncates(env: Env) -> None:
    log = env.home / "jobbot" / "state" / "log.txt"
    log.write_text("\n".join("x" * 400 for _ in range(500)) + "\n")
    lines = env.app.admin.log_tail("9999")
    assert len(lines) == 200
    assert all(len(line) == 300 for line in lines)
    assert len(env.app.admin.log_tail("abc")) == 30
    chunks = env.app.admin.log_chunks("200")
    assert len(chunks) > 1
    assert all(len(c) <= 3500 + 301 for c in chunks)
