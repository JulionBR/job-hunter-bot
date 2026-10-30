"""Every text the Telegram user sees (Portuguese), kept apart from the logic."""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from jobbot.models import Job, JobStatus

Keyboard = dict[str, list[list[dict[str, str]]]]

ADMIN_CMDS: list[tuple[str, str]] = [
    ("usuarios", "candidatos e vagas de cada um"),
    ("pendentes", "pedidos de acesso"),
    ("participar", "receber vagas também (você como candidato)"),
    ("buscar", "buscar vagas agora (todos, ou /buscar ID)"),
    ("log", "últimas linhas do log (/log 50, /log erros)"),
    ("saude", "estado do bot, fila e próxima busca"),
    ("remover", "remover candidato: /remover ID"),
    ("pcd", "portais PcD: /pcd ID sim|nao"),
    ("portal", "portais por público: /portal ID tag sim|nao"),
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
        "1️⃣ Mande seu currículo (PDF ou Word) ou o PDF do seu LinkedIn.\n"
        "2️⃣ Mande /perfil: faço perguntas, uma por vez, sobre o que você procura "
        "(20 a 30 min, pode pausar). Ao terminar, mande /fim.\n"
        f"3️⃣ Todo dia às {delivery_hour}h te mando até 5 vagas da Gupy e do LinkedIn, "
        "com nota, pontos fortes e o que falta.\n"
        "4️⃣ Gostou? Toque em 📝 <b>Gerar candidatura</b>: em uns 15 min chegam currículo e carta em PDF "
        'e o texto do campo "Apresente-se" da Gupy. '
        "Não gostou? Toque em 👎 <b>Não tenho interesse</b> e eu evito vagas parecidas.\n"
        "5️⃣ Você envia pelo link da vaga, com a sua conta. Eu nunca peço senha. "
        "Depois toque em 📨 <b>Enviei</b>.\n\n"
        "Comandos: /perfil · /fim · /buscar (1x por dia) · /status · /ajuda"
    )


def help_text(delivery_hour: int, is_admin: bool) -> str:
    extra = f"\n\n<b>Admin:</b>\n{command_list(ADMIN_CMDS)}" if is_admin else ""
    return how_it_works(delivery_hour) + extra


# ---------- access ----------
ADMIN_ONLY_ANSWER = "Só o administrador pode fazer isso."
APPROVING_ANSWER = "Aprovando… aviso quando terminar."
REFUSED_ANSWER = "Recusado."
NO_ACCESS_ANSWER = "Acesso não liberado."
JOB_NOT_FOUND_ANSWER = "Vaga não encontrada."
ACCESS_REFUSED = "Seu acesso não foi liberado."
ACCESS_REQUESTED = "Olá! 👋 Pedi ao administrador para liberar seu acesso. Aviso aqui assim que for aprovado."
ADMIN_HELP = "Comandos de admin:\n" + command_list(ADMIN_CMDS)
NO_PENDING = "Nenhum pedido pendente."
NO_USERS = "Nenhum candidato."
REMOVE_USAGE = "Uso: /remover ID (veja os IDs em /usuarios)."
PORTAL_USAGE = "Uso: /portal ID tag sim|nao (tag: letras, números e hífen; IDs em /usuarios)."
PCD_USAGE = "Uso: /pcd ID sim|nao (veja os IDs em /usuarios)."


def audience_label(tag: str) -> str:
    return "PcD" if tag == "pcd" else tag


def portal_set(name: str, tag: str, on: bool, portals: int) -> str:
    label = audience_label(tag)
    answer = "sim" if on else "não"
    if not portals:
        return (
            f"{esc(name)}: {esc(label)} {answer} gravado, mas nenhum portal {esc(label)} instalado na pasta."
        )
    state = "ligados" if on else "desligados"
    return f"{esc(name)}: {esc(label)} {answer}, {portals} portal(is) {esc(label)} {state}."


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


ALREADY_CANDIDATE = "Você já é candidato. Para montar ou atualizar seu perfil, mande /perfil."


def joined_as_candidate(delivery_hour: int) -> str:
    return (
        "✅ Pronto, você também é candidato. Agora mande /perfil para montar seu perfil.\n\n"
        + how_it_works(delivery_hour)
    )


def folder_failed(name: str, error: object) -> str:
    return f"❌ Não consegui criar a pasta de {esc(name)}: {esc(error)}"


def approved_admin(name: str, folder: object) -> str:
    return f"✅ {esc(name)} aprovado(a). Pasta: <code>{esc(folder)}</code>"


def removed(name: str, folder: object) -> str:
    return f"Removido: {esc(name)}. A pasta foi mantida em <code>{esc(folder)}</code>."


# ---------- profile ----------
CV_FORMAT = "Mande o currículo em PDF ou Word (.docx), por favor."
PROFILE_FIRST = "Antes, vamos montar seu perfil: mande /perfil."
PROFILE_INTRO = (
    "👋 Vamos montar seu perfil! Responda as perguntas aqui mesmo. Leva uns 20 a 30 min "
    "e você pode pausar quando quiser. Para terminar, mande /fim."
)
PROFILE_ERROR = "❌ Algo deu errado. Mande a resposta de novo ou use /fim e depois /perfil."
NO_ACTIVE_PROFILE = "Não há conversa de perfil aberta agora. Se quiser revisar o perfil, mande /perfil."
PROFILE_FINISH_QUEUED = (
    "Recebi o /fim. Vou fechar seu perfil assim que eu terminar de processar a sua última resposta."
)
PROFILE_INCOMPLETE = (
    "Conversa encerrada, mas faltou terminar o perfil. Mande /perfil para continuar de onde parou."
)


def cv_saved(name: str) -> str:
    return f"📄 Currículo recebido ({esc(name)}). Agora mande /perfil."


def profile_done(delivery_hour: int) -> str:
    return f"✅ Perfil pronto! Amanhã às {delivery_hour}h chegam suas primeiras vagas."


def profile_done_admin(name: str) -> str:
    return f"✅ Perfil de {esc(name)} pronto — entra na busca diária."


# ---------- search ----------
SEARCH_RUNNING = "⏳ Já estou buscando vagas. Elas chegam aqui quando terminar."
SEARCH_FAILED = "⚠️ A busca de hoje não funcionou. O administrador já foi avisado."
MANUAL_SEARCH_DONE = "Você já usou a busca extra de hoje. Amanhã de madrugada eu busco de novo."
MANUAL_SEARCH_STARTED = "🔎 Buscando vagas agora. Pode levar mais de meia hora; aviso quando terminar."


def admin_search_started(arg: str) -> str:
    return "🔎 Buscando vagas agora" + (f" para {arg}" if arg else " para todos") + ". Aviso quando terminar."


def no_new_jobs(today: str) -> str:
    return f"🔎 {today}: hoje não achei vagas novas que combinem com você."


def new_jobs_header(count: int, today: str) -> str:
    return f"🔎 <b>{count} vaga(s) nova(s) — {today}</b>"


def _credit(job: Job) -> str:
    """`` · via <portal>``; Himalayas' terms require a link back to himalayas.app."""
    try:
        host = (urlsplit(job.url).hostname or "").lower()
    except ValueError:  # the url comes from Claude's shortlist: a malformed one must not break delivery
        host = ""
    if host == "himalayas.app" or host.endswith(".himalayas.app") or "himalayas" in job.source.lower():
        return ' · via <a href="https://himalayas.app">Himalayas</a>'
    return f" · via {esc(job.source)}" if job.source else ""


def job_card(job: Job) -> str:
    deadline = f"\n⏰ Prazo: {esc(job.deadline)}" if job.deadline else ""
    source = _credit(job)
    return (
        f"<b>{esc(job.title)}</b>\n🏢 {esc(job.company)} · 📍 {esc(job.location)}\n"
        f"⭐ Combina com você: {esc(job.score)}\n✅ {esc(job.strengths)}\n⚠️ {esc(job.gaps)}{deadline}\n"
        f'🔗 <a href="{esc(job.url)}">Abrir vaga</a>{source}'
    )


def job_keyboard(job_id: str) -> Keyboard:
    return {
        "inline_keyboard": [
            [
                {"text": "📝 Gerar candidatura", "callback_data": f"a:{job_id}"},
                {"text": "👎 Não tenho interesse", "callback_data": f"s:{job_id}"},
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
FILES_FAILED = (
    "❌ Não consegui gerar sua candidatura. O administrador já foi avisado. Toque abaixo para tentar de novo."
)


def retry_keyboard(job_id: str) -> Keyboard:
    return {"inline_keyboard": [[{"text": "🔁 Tentar de novo", "callback_data": f"a:{job_id}"}]]}


def generating(title: str, company: str) -> str:
    return f"⏳ Gerando sua candidatura: <b>{esc(title)}</b> ({esc(company)}). Leva uns 10 a 20 min."


def apply_failed_admin(user_name: str, title: str, company: str, output: str) -> str:
    return (
        f"❌ /apply falhou para {esc(user_name)}: {esc(title)} ({esc(company)})\n"
        f"<pre>{esc(output[-1200:])}</pre>\nMais em /log erros"
    )


GUPY_INTRO = '✍️ Texto para o campo "Apresente-se" da Gupy. Toque no texto abaixo e segure para copiar 👇'
APPLY_SUMMARY_FALLBACK = "✅ Sua candidatura está pronta! Os PDFs chegam logo abaixo 👇"


def gupy_text(text: str) -> str:
    """The Gupy text alone (sent right after ``GUPY_INTRO``), so it is easy to copy on a phone."""
    return text.strip()


def application_ready(url: str) -> str:
    return f'✅ Pronto! Confira os PDFs e envie pelo link da vaga: <a href="{esc(url)}">abrir vaga</a>'


def sent_keyboard(job_id: str) -> Keyboard:
    return {"inline_keyboard": [[{"text": "📨 Enviei", "callback_data": f"d:{job_id}"}]]}


def queued_answer(position: int) -> str:
    return f"Na fila (posição {position}). Aviso quando começar."


SKIPPED_ANSWER = "Anotado. Vou evitar vagas parecidas."
IN_PROGRESS_ANSWER = "Essa vaga já foi encaminhada."
SENT_ANSWER = "Marcada como enviada. Boa sorte! 🍀"


WORKER_ERROR = "❌ Algo deu errado. O administrador já foi avisado."


def worker_error_admin(task: str, chat: int, error: object) -> str:
    return f"❌ Falha em {esc(task)} (chat <code>{chat}</code>): {esc(error)}\nMais em /log erros"


def profile_failed_admin(name: str) -> str:
    return f"⚠️ O /perfil de {esc(name)} falhou. Veja /log erros"


TOKEN_EXPIRED = (
    "⚠️ O token do Claude na VPS parece ter expirado. Gere outro com "
    "<code>claude setup-token</code> e atualize <code>~/.config/jobbot/env</code>."
)


# ---------- admin ----------
LOG_EMPTY = "Log vazio."
LOG_NO_ERRORS = "Nenhum erro no log. 🎉"


def log_block(chunk: str) -> str:
    return f"<pre>{esc(chunk)}</pre>"


STATUS_LABELS = {JobStatus.SKIPPED.value: "não tenho interesse"}


def status_counts(counts: dict[str, int]) -> str:
    """Counts per status; the persisted value ``pulada`` is shown as "não tenho interesse"."""
    return ", ".join(f"{STATUS_LABELS.get(k, k)}: {v}" for k, v in counts.items())


def status_line(counts: dict[str, int]) -> str:
    return "📊 " + (status_counts(counts) or "nenhuma vaga ainda")


def audience_summary(audiences: Mapping[str, bool]) -> str:
    """``PcD: sim · ti: não``: PcD always shown (``?`` when unknown), other tags only when set."""
    pcd = audiences.get("pcd")
    parts = [f"PcD: {'?' if pcd is None else 'sim' if pcd else 'não'}"]
    parts += [
        f"{esc(tag)}: {'sim' if on else 'não'}" for tag, on in sorted(audiences.items()) if tag != "pcd"
    ]
    return " · ".join(parts)


def user_line(
    name: str,
    chat: int,
    ready: bool,
    chatting: bool,
    counts: dict[str, int],
    audiences: Mapping[str, bool] | None = None,
) -> str:
    audiences = audiences or {}
    return (
        f"• <b>{esc(name)}</b> <code>{chat}</code> — perfil {'✅' if ready else '⏳'}"
        f"{' (conversando)' if chatting else ''}"
        f" · {audience_summary(audiences)}\n  " + (status_counts(counts) or "sem vagas ainda")
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
