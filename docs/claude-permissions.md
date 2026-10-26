# Permissões do Claude Code na pasta de referência

O bot executa o Claude Code de forma não interativa: `claude -p --permission-mode acceptEdits`.
Não há ninguém para aprovar um pedido de permissão, então tudo o que o fluxo precisa executar
tem de estar liberado de antemão. O `.claude/settings.json` do ai-job-search já traz as regras dos
scripts dele (`scrape_state.py`, `rank_state.py`, `posting_guard.py`, `verify_pdf.py`, `pdftotext` etc.) e
dos portais que vêm com ele. Na pasta de referência (por padrão `/home/jobbot/ai-job-search`), acrescente
**em cima delas** estas regras em `permissions.allow`:

```json
{
  "permissions": {
    "allow": [
      "Bash(bun --version)",
      "WebSearch",
      "WebFetch",
      "Bash(lualatex:*)",
      "Bash(xelatex:*)",
      "Bash(pdfinfo:*)",
      "Bash(python3 tools/jobbot_tex.py:*)",
      "Bash(python tools/jobbot_tex.py:*)",
      "Bash(bun run .agents/skills/gupy-search/cli/src/cli.ts:*)"
    ]
  }
}
```

Cada candidato novo recebe uma cópia desse `settings.json` quando é aprovado.

| Regra | Uso |
|-------|-----|
| `Bash(bun --version)` | Checagem do runtime dos CLIs de portais |
| `WebSearch`, `WebFetch` | Pesquisa de vagas e de empresas |
| `Bash(lualatex:*)`, `Bash(xelatex:*)` | Compilar currículo e carta em PDF |
| `Bash(pdfinfo:*)` | Conferir o número de páginas dos PDFs |
| `Bash(python3 tools/jobbot_tex.py:*)`, `Bash(python tools/jobbot_tex.py:*)` | Compila currículo e carta a partir da raiz, sem `cd` (veja abaixo) |
| `Bash(bun run .agents/skills/gupy-search/cli/src/cli.ts:*)` | Busca no portal Gupy |

Se você adicionar outros portais (`/add-portal`), libere do mesmo jeito só o comando exato do CLI deles.

## Por que não usar `bypassPermissions` nem `Bash` amplo

- O Claude lê páginas de vagas e documentos da internet, que são entrada não confiável e podem conter
  instruções maliciosas (prompt injection). Com `bypassPermissions` ou `Bash(*)`, uma vaga manipulada
  poderia executar comandos arbitrários na máquina, ler o token do bot ou os dados de outros candidatos.
- Com regras estreitas, o pior caso fica limitado aos comandos listados.
- `acceptEdits` já cobre a edição de arquivos dentro da pasta de trabalho.

## O que mais trava no modo `-p`, e como o bot contorna

Tudo isto foi observado em execuções reais e é tratado com instruções que o bot acrescenta a cada chamada
(`--append-system-prompt`, em `src/jobbot/prompts.py`):

| Trava | Contorno |
|---|---|
| `cd pasta && comando` pede aprovação | Comandos sempre a partir da raiz; LaTeX via `tools/jobbot_tex.py`, que compila a carta dentro de `cover_letters/` (o `cover.cls` procura as fontes por caminho relativo) |
| Variáveis, laços, `$(...)`, `{a,b}`, `python3 -c` | Um comando simples por chamada |
| `/tmp` e scratchpad não existem ou são recusados | Temporários em `.jobbot-tmp/`, apagada pelo bot depois de cada execução |
| Perguntas do fluxo ("Should I proceed?", alertas, "confirme com a pessoa") | Tocar em "Gerar candidatura" já é a confirmação: o Claude segue até os PDFs e registra os alertas no resumo |
| Subagentes não recebem o `--append-system-prompt` | O orquestrador é instruído a repassar as regras no prompt de cada subagente |
| Checagem de git no início do `/setup` | Instruída a ser pulada (o bot nunca publica nada) |

## Por que `.claude/` precisa de staging

No modo `-p`, a pasta `.claude/` é protegida: o Claude não consegue gravar nela, mesmo com `acceptEdits`
e mesmo com regras de allow. O Claude grava a versão completa do arquivo em `.jobbot-staging/claude/<caminho>`,
e o bot a copia para `.claude/` depois de cada execução. Só entram os arquivos de perfil de uma lista permitida
(`skills/job-application-assistant/0*.md`, `skills/job-scraper/search-queries.md`, `skills/upskill/*.md`),
e links simbólicos são ignorados. Os arquivos `.jobbot-*` ficam fora do git via `.git/info/exclude`
(o `deploy/install.sh` cuida disso na pasta de referência, e o bot nas pastas novas).
