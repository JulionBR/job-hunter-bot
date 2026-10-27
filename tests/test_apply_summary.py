import logging

import pytest

from conftest import ADMIN, ALICE, Env
from jobbot import messages
from jobbot.prompts import GUPY_PROMPT, SUMMARY_END, SUMMARY_START
from jobbot.services.applications import SUMMARY_LIMIT, clean_gupy_text, extract_summary
from jobbot.storage import JobRepository


def block(body: str) -> str:
    return f"{SUMMARY_START}\n{body}\n{SUMMARY_END}"


def test_extracts_a_normal_block() -> None:
    out = f"trabalho interno\n{block('Pronta!\n⭐ Combina com você: boa')}\n"
    assert extract_summary(out) == "Pronta!\n⭐ Combina com você: boa"


def test_last_block_wins() -> None:
    assert extract_summary(block("primeiro") + "\nmais coisas\n" + block("segundo")) == "segundo"


def test_block_without_end_or_without_block_is_none() -> None:
    assert extract_summary(f"{SUMMARY_START}\nsem fim") is None
    assert extract_summary("só texto solto") is None
    assert extract_summary("") is None
    assert extract_summary(block("  \n ")) is None
    # a complete old block followed by an unterminated new one: the last start has no end
    assert extract_summary(block("velho") + f"\n{SUMMARY_START}\nnovo sem fim") is None


def test_markdown_is_removed() -> None:
    text = extract_summary(block("## Título\n**Pronta** com `código`\n  # outra"))
    assert text == "Título\nPronta com código\noutra"
    assert text is not None and not any(ch in text for ch in "*`#")


def test_long_summary_is_cut() -> None:
    text = extract_summary(block("ab " * 1000))
    assert text is not None and len(text) <= SUMMARY_LIMIT
    emoji = extract_summary(block("😀" * 2000))
    assert emoji is not None and len(emoji) == SUMMARY_LIMIT and set(emoji) == {"😀"}


def test_clean_gupy_text() -> None:
    assert clean_gupy_text("**Olá**, `tudo` bem") == "Olá, tudo bem"
    assert clean_gupy_text('Texto: "Sou engenheira."') == "Sou engenheira."
    assert clean_gupy_text("“Sou engenheira.”") == "Sou engenheira."
    assert clean_gupy_text("Resposta:\nSou engenheira.") == "Sou engenheira."
    assert clean_gupy_text('Dizem "oi" e tchau') == 'Dizem "oi" e tchau'


def prepare(env: Env) -> str:
    env.add_candidate()
    env.app.search.run()
    return JobRepository(env.app.store, ALICE).all()[0].job_id


def test_only_the_block_reaches_the_candidate_and_gupy_is_two_messages(env: Env) -> None:
    job_id = prepare(env)
    raw = (
        "Aguardando o revisor... rodei verify_layout.py\n"
        + block("✅ Pronta!\n⭐ Combina com você: boa")
        + "\ntexto depois do bloco"
    )
    env.claude.reply = lambda prompt: '**Texto:** "Sou engenheira."' if prompt == GUPY_PROMPT else raw
    env.app.applications.apply_job(ALICE, job_id)
    plain = [m.text for m in env.telegram.plain]
    assert plain == [
        "✅ Pronta!\n⭐ Combina com você: boa",
        messages.GUPY_INTRO,
        "Sou engenheira.",
    ]
    everything = " ".join(m.text for m in env.telegram.messages + env.telegram.plain)
    for leaked in ("Aguardando o revisor", "verify_layout.py", "texto depois do bloco"):
        assert leaked not in everything


def test_missing_block_sends_fallback_never_the_raw_output(env: Env) -> None:
    job_id = prepare(env)
    env.claude.reply = lambda prompt: "log bruto verify_layout.py" if prompt != GUPY_PROMPT else "texto"
    env.app.applications.apply_job(ALICE, job_id)
    assert env.telegram.plain[0].text == messages.APPLY_SUMMARY_FALLBACK
    assert all("verify_layout" not in m.text for m in env.telegram.plain)


def test_full_apply_output_goes_to_the_log(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    job_id = prepare(env)
    env.claude.reply = lambda prompt: "ETAPA-INTERNA verify_layout ok" if prompt != GUPY_PROMPT else "texto"
    with caplog.at_level(logging.INFO, logger="jobbot"):
        env.app.applications.apply_job(ALICE, job_id)
    assert any("ETAPA-INTERNA verify_layout ok" in r.getMessage() for r in caplog.records)


def test_stderr_never_reaches_the_candidate(env: Env) -> None:
    job_id = prepare(env)
    warning = "WARNING: ferramenta lenta, aguardando revisor"
    env.claude.stderr = warning
    env.claude.reply = lambda prompt: "Sou engenheira." if prompt == GUPY_PROMPT else block("✅ Pronta!")
    env.app.applications.apply_job(ALICE, job_id)
    everything = " ".join(m.text for m in env.telegram.messages + env.telegram.plain)
    assert "WARNING" not in everything and "revisor" not in everything
    assert [m.text for m in env.telegram.plain] == ["✅ Pronta!", messages.GUPY_INTRO, "Sou engenheira."]


def test_summary_block_only_in_stderr_is_not_used(env: Env) -> None:
    job_id = prepare(env)
    env.claude.reply = lambda prompt: "texto" if prompt == GUPY_PROMPT else "sem bloco"
    env.claude.stderr = block("vazou pelo stderr")
    env.app.applications.apply_job(ALICE, job_id)
    assert env.telegram.plain[0].text == messages.APPLY_SUMMARY_FALLBACK


def test_empty_gupy_text_sends_nothing_and_logs(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    job_id = prepare(env)
    env.claude.reply = lambda prompt: '**""**' if prompt == GUPY_PROMPT else block("✅ Pronta!")
    with caplog.at_level(logging.INFO, logger="jobbot"):
        env.app.applications.apply_job(ALICE, job_id)
    texts = [m.text for m in env.telegram.plain]
    assert texts == ["✅ Pronta!"]
    assert any("texto vazio" in r.getMessage() for r in caplog.records)


def test_successful_apply_output_with_the_word_erro_is_not_an_error(env: Env) -> None:
    job_id = prepare(env)
    env.claude.reply = lambda prompt: (
        "texto" if prompt == GUPY_PROMPT else "corrigi um erro de layout\n" + block("ok")
    )
    env.app.applications.apply_job(ALICE, job_id)
    log_text = (env.home / "jobbot" / "state" / "log.txt").read_text()
    assert "apply-saida[Alice]" in log_text and "erro de layout" in log_text
    assert env.app.admin.log_tail("erros") == []
    env.message(ADMIN, "/log erros")
    assert env.telegram.last(ADMIN) == messages.LOG_NO_ERRORS
    env.message(ADMIN, "/saude")
    assert "Último erro: <code>nenhum</code>" in env.telegram.last(ADMIN)
    env.message(ADMIN, "/log 3")
    assert "apply-saida" in env.telegram.last(ADMIN)
