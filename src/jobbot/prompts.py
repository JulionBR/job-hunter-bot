"""Prompts sent to Claude Code. User-facing language is Portuguese; the JSON keys are English."""

# ruff: noqa: E501
from __future__ import annotations

# In -p mode Claude Code never writes under .claude/ (protected folder; allow rules do not help).
# It writes to .jobbot-staging/claude/... (no ".claude" in the path, or it is protected too) and the bot
# copies only the profile files listed in STAGING_ALLOWED.
STAGING_NOTE = (
    "Arquivos dentro de .claude/ são protegidos neste ambiente e a escrita direta será recusada. "
    "Para criar ou alterar .claude/<caminho>, leia o original e grave a versão completa em "
    ".jobbot-staging/claude/<caminho> (sem o ponto); o sistema aplica depois. Não tente outro contorno."
)
STAGING_ALLOWED = (
    "skills/job-application-assistant/0*.md",
    "skills/job-scraper/search-queries.md",
    "skills/upskill/*.md",
)

# Rules for the no-approver mode (audit of real transcripts). Sent on every call.
BASE_NOTE = (
    "Ambiente sem ninguém para aprovar: comando que precisaria de aprovação é recusado. Regras:\n"
    "- O diretório atual já é a raiz do candidato. Nunca comece comandos com `cd`; use caminhos relativos à raiz.\n"
    "- Um comando simples por chamada Bash (faça várias chamadas em paralelo se precisar). Pipe `|` para filtrar saída pode. Proibido: variáveis de shell ($VAR, ${...}), for/while, $(...), $((...)), chaves {a,b}, espaço escapado com \\, `python3 -c`, heredoc com script próprio, redirecionar para fora da pasta.\n"
    "- Arquivos temporários só em .jobbot-tmp/ (mkdir -p .jobbot-tmp), com caminho literal. Não existe scratchpad; /tmp e ~/ são recusados.\n"
    "- A ferramenta Glob não existe: use `find <pasta> -type f` ou `ls`.\n"
    "- Não instale nada (pip, bun install, apt) e não rode git nem gh. pypdf não existe; tools/verify_pdf.py usa pdftotext sozinho.\n"
    "- Arquivos de .claude/: leia com Read e grave a versão completa com Write em .jobbot-staging/claude/<caminho>. Nunca use cp, mv, sed nem Bash neles.\n"
    "- Compilar LaTeX sempre com `python3 tools/jobbot_tex.py cv/<arquivo>.tex` ou `python3 tools/jobbot_tex.py cover_letters/<arquivo>.tex` (limpeza: acrescente --clean). Nunca `cd pasta && lualatex`.\n"
    "- Nunca use AskUserQuestion.\n"
    "- Ao despachar subagentes (Agent), copie estas regras no prompt deles: eles NÃO recebem esta nota. Diga também: Glob não existe (use find/ls); fetch_page.py sempre com `--out .jobbot-tmp/<n>.html` e depois `python3 tools/posting_guard.py --in .jobbot-tmp/<n>.html --html --json`."
)

# The ai-job-search /apply stops after the evaluation and asks "Should I proceed?"; through the bot
# nobody can answer, so tapping "Gerar candidatura" is the confirmation.
APPLY_NOTE = "Execução automática pelo bot do Telegram: não há ninguém para responder. A pessoa já decidiu se candidatar ao tocar em 'Gerar candidatura', então a resposta à pergunta 'Should I proceed with drafting the CV and cover letter for this role?' é SIM: faça a avaliação de aderência e siga direto pelo fluxo completo do /apply até os PDFs compilados, sem fazer perguntas nem pedir confirmação. Lacunas e informações que faltam: reconheça com honestidade nos documentos, nunca invente. Também é SIM para 'Continue with this posting?' (alerta do posting_guard) e para host não verificado: registre o alerta no resumo final e siga. Siga até os PDFs mesmo com aderência baixa. Onde o perfil ou os templates mandam perguntar ou confirmar com a pessoa (números, lacunas, nível de Excel etc.), NÃO pergunte: use só o que está nas fontes e omita o resto. Step 5e: use `python3 tools/jobbot_tex.py --clean <arquivo>.tex`. Não ofereça campos extras de formulário. Termine em português, em poucas linhas: nota de aderência, 2-3 lacunas e qualquer alerta (posting_guard, host, compilação)."

SETUP_NOTE = "Pule a verificação de git/GitHub do Step 0 do setup.md: não rode git nem gh (o bot nunca publica nada). Para listar documentos use `find documents -type f`. Se for testar o CV: `python3 tools/jobbot_tex.py cv/main_example.tex`. Toda resposta termina com UMA pergunta ou com o aviso de que acabou e que a pessoa deve mandar /fim."

GUPY_NOTE = "Sem perguntas. Use só fatos do perfil e da vaga já lidos; se faltar algo, omita. Não grave arquivos nem rode comandos: responda só com o texto."

SHORTLIST_FILE = ".jobbot-shortlist.json"

# Format with ``top_n``.
SEARCH_PROMPT = """Rodada automática, sem ninguém para responder: não faça perguntas nem peça confirmação.
1. Rode o skill /scrape (.claude/skills/job-scraper/SKILL.md) para buscar vagas novas em todos os portais habilitados.
2. Rode /rank (.claude/commands/rank.md) para pontuar as vagas novas.
3. Grave em .jobbot-shortlist.json um array JSON (apenas o JSON) com as até {top_n} melhores vagas
   novas desta rodada, da maior para a menor aderência, excluindo as vetadas por deal-breakers.
   Cada item: {{"title","company","location","url","score","strengths","gaps","deadline"}}.
   Textos curtos em português; "score" como texto (ex.: "8/10"); "deadline" vazio se não houver.
   Se o perfil disser que a pessoa aceita vagas afirmativas PcD, conte isso a favor, sem filtrar só elas.
   Se não houver vagas novas, grave []. Se a busca não rodar direito (permissão negada, portal fora do ar,
   nenhuma consulta concluída), NÃO grave o arquivo: assim o sistema registra a falha em vez de "0 vagas".
4. Não rode /apply.
5. Cada busca de portal é uma chamada separada: `bun run .agents/skills/<portal>/cli/src/cli.ts search ... --format json` (paralelas), sem laço e sem redirecionar para fora da pasta.
6. JSONs intermediários (resultados, candidatos, notas do rank) vão em .jobbot-tmp/. Em cada item passado a `python3 tools/scrape_state.py store`, inclua "first_seen": "<hoje AAAA-MM-DD>".
7. Não ofereça desabilitar portais nem pergunte quais vagas avaliar: só registre no resumo final."""

GUPY_PROMPT = (
    "Com base na vaga e na candidatura que você acabou de preparar, escreva o texto para o campo "
    "'Apresente-se' / 'Sobre você' da Gupy: português, no máximo 1.500 caracteres, só fatos do perfil. "
    "Responda apenas com o texto."
)

SETUP_PROMPT = """Siga .claude/commands/setup.md para montar o perfil do(a) candidato(a).
A pessoa está conversando com você pelo Telegram, no celular: escreva em português, mensagens curtas,
UMA pergunta por vez, sem tabelas nem markdown pesado. Mercado brasileiro; currículo e cartas em português.
Se houver currículo em documents/cv/, use-o como ponto de partida. Comece se apresentando em uma frase
e fazendo a primeira pergunta."""


def search_prompt(top_n: int) -> str:
    return SEARCH_PROMPT.format(top_n=top_n)
