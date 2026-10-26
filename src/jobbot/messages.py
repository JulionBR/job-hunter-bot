"""Every text the Telegram user sees (Portuguese), kept apart from the logic."""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence

from jobbot.models import Job

Keyboard = dict[str, list[list[dict[str, str]]]]

ADMIN_CMDS: list[tuple[str, str]] = [
    ("usuarios", "candidatos e vagas de cada um"),
    ("pendentes", "pedidos de acesso"),
    ("buscar", "buscar vagas agora (todos, ou /buscar ID)"),
    ("log", "últimas linhas do log (/log 50, /log erros)"),
    ("saude", "estado do bot, fila e próxima busca"),
    ("remover", "remover candidato: /remover ID"),
]
USER_CMDS: list[tuple[str, str]] = [
    ("perfil", "montar ou atualizar seu perfil"),
    ("fim", "encerrar a conversa de perfil"),
    ("buscar", "buscar vagas agora (1x por dia)"),
    ("status", "resumo das suas vagas"),
    ("ajuda", "como o bot funciona"),
]


def esc(value: object) -> str:
    """HTML-escape any value (``None`` and falsy values become an empty string)."""
    return html.escape(str(value or ""))


def command_list(cmds: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"/{c} — {d}" for c, d in cmds)


def how_it_works(delivery_hour: int) -> str:
    return (
        "<b>Como funciona</b>\n"
        "1️⃣ Mande aqui seu currículo (PDF ou Word) ou o PDF do seu perfil do LinkedIn.\n"
        "2️⃣ Mande /perfil: vou fazer algumas perguntas, uma por vez, para entender o que você procura "
        "(uns 20–30 min, pode pausar e voltar depois). No final, mande /fim.\n"  # noqa: RUF001
        f"3️⃣ Todo dia, de madrugada, eu procuro vagas na Gupy e no LinkedIn e às {delivery_hour}h te mando "
        "as melhores (até 5), com uma nota de aderência, os pontos fortes e as lacunas.\n"
        "4️⃣ Gostou de uma? Toque em 📝 <b>Gerar candidatura</b>: em uns 15 min chegam o currículo e a carta "
        'sob medida em PDF e o texto para o campo "Apresente-se" da Gupy. Não gostou? ⏭️ <b>Pular</b>.\n'
        "5️⃣ A candidatura é enviada por você, pelo link da vaga, com a sua conta. "
        "Eu nunca peço senha. Depois toque em 📨 <b>Enviei</b>.\n\n"
        "Comandos: /perfil · /fim · /buscar (busca extra, 1x por dia) · /status · /ajuda"
    )


def help_text(delivery_hour: int, is_admin: bool) -> str:
    extra = f"\n\n<b>Admin:</b>\n{command_list(ADMIN_CMDS)}" if is_admin else ""
    return how_it_works(delivery_hour) + extra


# ---------- access ----------
ADMIN_ONLY_ANSWER = "Só o administrador pode fazer isso."
APPROVING_ANSWER = "Aprovando… aviso quando a pasta estiver pronta."
REFUSED_ANSWER = "Recusado."
NO_ACCESS_ANSWER = "Acesso não liberado."
JOB_NOT_FOUND_ANSWER = "Vaga não encontrada."
ACCESS_REFUSED = "Seu acesso a este bot não foi liberado."
ACCESS_REQUESTED = "Olá! 👋 Pedi ao administrador para liberar seu acesso. Aviso aqui quando for aprovado."
ADMIN_HELP = "Comandos de admin:\n" + command_list(ADMIN_CMDS)
NO_PENDING = "Nenhum pedido pendente."
NO_USERS = "Nenhum candidato."
REMOVE_USAGE = "Uso: /remover ID (veja os IDs em /usuarios)."


def approval_keyboard(chat: int | str) -> Keyboard:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Aprovar", "callback_data": f"ok:{chat}"},
                {"text": "🚫 Recusar", "callback_data": f"no:{chat}"},
            ]
        ]
    }


def access_request(name: str, username: str, chat: int, text: str) -> str:
    return (
        f"🙋 Pedido de acesso: <b>{esc(name)}</b> {esc(username)} "
        f"(<code>{chat}</code>)\nMensagem: {esc(text[:200])}"
    )


def pending_line(name: str, username: str, chat: int, requested_at: str) -> str:
    return f"🙋 {esc(name)} {esc(username)} <code>{chat}</code> — {esc(requested_at)}"


def access_granted(delivery_hour: int) -> str:
    return "✅ <b>Acesso liberado!</b>\n\n" + how_it_works(delivery_hour)


def folder_failed(name: str, error: object) -> str:
    return f"❌ Não consegui criar a pasta de {esc(name)}: {esc(error)}"


def approved_admin(name: str, folder: object) -> str:
    return f"✅ {esc(name)} aprovado(a). Pasta: <code>{esc(folder)}</code>"


def removed(name: str, folder: object) -> str:
    return f"Removido: {esc(name)}. A pasta foi mantida em <code>{esc(folder)}</code>."


# ---------- profile ----------
CV_FORMAT = "Mande o currículo em PDF ou Word (.docx)."
PROFILE_FIRST = "Primeiro monte seu perfil com /perfil."
PROFILE_INTRO = (
    "👋 Vamos montar seu perfil. Responda as perguntas aqui mesmo; leva uns 20–30 min, "  # noqa: RUF001
    "pode pausar quando quiser. Mande /fim para encerrar."
)
PROFILE_ERROR = "❌ Deu erro. Tente de novo ou mande /fim e depois /perfil."
PROFILE_INCOMPLETE = "Conversa encerrada, mas o perfil ainda está incompleto. Mande /perfil para continuar."


def cv_saved(name: str) -> str:
    return f"📄 Currículo salvo ({esc(name)}). Agora mande /perfil para montar o perfil."


def profile_done(delivery_hour: int) -> str:
    return f"✅ Perfil pronto! A partir de amanhã você recebe vagas todo dia às {delivery_hour}h."


def profile_done_admin(name: str) -> str:
    return f"✅ Perfil de {esc(name)} pronto — entra na busca diária."


# ---------- search ----------
SEARCH_RUNNING = "⏳ Já tem uma busca rodando. As vagas chegam quando ela terminar."
SEARCH_FAILED = "⚠️ A busca de vagas de hoje falhou. O administrador já foi avisado."
MANUAL_SEARCH_DONE = "Você já fez uma busca manual hoje. A próxima busca automática roda de madrugada."
MANUAL_SEARCH_STARTED = "🔎 Buscando vagas agora. Aviso quando terminar (pode levar mais de meia hora)."


def admin_search_started(arg: str) -> str:
    return "🔎 Buscando vagas agora" + (f" para {arg}" if arg else " para todos") + ". Aviso quando terminar."


def no_new_jobs(today: str) -> str:
    return f"🔎 {today}: nenhuma vaga nova com boa aderência hoje."


def new_jobs_header(count: int, today: str) -> str:
    return f"🔎 <b>{count} vaga(s) nova(s) — {today}</b>"


def job_card(job: Job) -> str:
    deadline = f"\n⏰ Prazo: {esc(job.deadline)}" if job.deadline else ""
    return (
        f"<b>{esc(job.title)}</b>\n🏢 {esc(job.company)} · 📍 {esc(job.location)}\n"
        f"⭐ Aderência: {esc(job.score)}\n✅ {esc(job.strengths)}\n⚠️ {esc(job.gaps)}{deadline}\n"
        f'🔗 <a href="{esc(job.url)}">Abrir vaga</a>'
    )


def job_keyboard(job_id: str) -> Keyboard:
    return {
        "inline_keyboard": [
            [
                {"text": "📝 Gerar candidatura", "callback_data": f"a:{job_id}"},
                {"text": "⏭️ Pular", "callback_data": f"s:{job_id}"},
            ]
        ]
    }


def search_summary(minutes: float, summary: Iterable[str], delivery_note: str) -> str:
    return (
        f"🔎 Busca concluída em {minutes:.0f} min — "
        + ("; ".join(summary) or "nenhum candidato com perfil pronto")
        + delivery_note
    )


def delivery_note(delivery_hour: int) -> str:
    return f" · envio às {delivery_hour}h"


# ---------- applications ----------
FILES_FAILED = "❌ Não consegui gerar os PDFs desta vez. O administrador já foi avisado."


def retry_keyboard(job_id: str) -> Keyboard:
    return {"inline_keyboard": [[{"text": "🔁 Tentar de novo", "callback_data": f"a:{job_id}"}]]}


def generating(title: str, company: str) -> str:
    return f"⏳ Gerando candidatura: <b>{esc(title)}</b> ({esc(company)}). Leva uns 10–20 min."  # noqa: RUF001


def apply_failed_admin(user_name: str, title: str, company: str, output: str) -> str:
    return (
        f"❌ /apply falhou para {esc(user_name)}: {esc(title)} ({esc(company)})\n"
        f"<pre>{esc(output[-1200:])}</pre>\nMais em /log erros"
    )


def gupy_text(text: str) -> str:
    return "Texto para a Gupy (copie e cole):\n\n" + text


def application_ready(url: str) -> str:
    return f'✅ Pronto. Confira os PDFs e envie pela vaga: <a href="{esc(url)}">abrir</a>'


def sent_keyboard(job_id: str) -> Keyboard:
    return {"inline_keyboard": [[{"text": "📨 Enviei", "callback_data": f"d:{job_id}"}]]}


def queued_answer(position: int) -> str:
    return f"Na fila (posição {position})."


SKIPPED_ANSWER = "Pulada."
SENT_ANSWER = "Marcada como enviada. Boa sorte! 🍀"


def worker_error(error: object) -> str:
    return f"❌ Erro: {esc(error)}"


TOKEN_EXPIRED = (
    "⚠️ O token do Claude na VPS parece ter expirado. Gere outro com "
    "<code>claude setup-token</code> e atualize <code>~/.config/jobbot/env</code>."
)


# ---------- admin ----------
LOG_EMPTY = "Log vazio."
LOG_NO_ERRORS = "Nenhum erro no log. 🎉"


def log_block(chunk: str) -> str:
    return f"<pre>{esc(chunk)}</pre>"


def status_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in counts.items())


def status_line(counts: dict[str, int]) -> str:
    return "📊 " + (status_counts(counts) or "nenhuma vaga ainda")


def user_line(name: str, chat: int, ready: bool, chatting: bool, counts: dict[str, int]) -> str:
    return (
        f"• <b>{esc(name)}</b> <code>{chat}</code> — perfil {'✅' if ready else '⏳'}"
        f"{' (conversando)' if chatting else ''}\n  " + (status_counts(counts) or "sem vagas ainda")
    )


def health(
    uptime_hours: float,
    claude_state: str,
    current: str,
    queue_size: int,
    next_search: str,
    last_search: str,
    users: int,
    ready: int,
    pending: int,
    open_chats: int,
    last_error: str,
) -> str:
    return (
        "🩺 <b>Saúde do bot</b>\n"
        f"No ar há {uptime_hours:.1f} h\n"
        f"Claude: {claude_state} · trabalho atual: {esc(current)} · fila: {queue_size}\n"
        f"Próxima busca: {esc(next_search)}\n"
        f"Última busca: {esc(last_search)}\n"
        f"Candidatos: {users} ({ready} com perfil pronto) · pedidos pendentes: {pending}\n"
        f"Conversas de /perfil abertas: {open_chats}\n"
        f"Último erro: <code>{esc(last_error[:200]) if last_error else 'nenhum'}</code>"
    )
