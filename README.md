# job-hunter-bot 🔎

Bot de Telegram que procura vagas de emprego todos os dias para várias pessoas, dá uma nota de aderência ao perfil de cada uma e, com um toque, gera **currículo e carta de apresentação sob medida em PDF**, além do texto do campo "Apresente-se" da Gupy.

Por trás do bot está o [**ai-job-search**](https://github.com/MadsLorentzen/ai-job-search), um framework open source que roda sobre o [Claude Code](https://claude.com/claude-code). Este projeto não reescreve o framework: ele o torna **multiusuário, automático e acessível pelo celular**.

> **English summary.** *job-hunter-bot* is a multi-user Telegram bot that wraps the open-source [ai-job-search](https://github.com/MadsLorentzen/ai-job-search) Claude Code framework. Every night it scrapes and ranks job postings for each approved user, delivers the best matches at 7 am, and on one tap generates a tailored CV and cover letter (LaTeX → PDF). Users always submit applications themselves; no portal credentials are stored. Pure Python 3.12 standard library, object-oriented, fully tested.

---

## O projeto original: ai-job-search

O [ai-job-search](https://github.com/MadsLorentzen/ai-job-search) foi criado por **Mads Lorentzen** (licença MIT). Ele perdeu o emprego no fim de 2025, montou esse fluxo para a própria busca e, depois de 69 candidaturas sob medida, foi contratado como engenheiro de IA. O framework é um repositório que você clona e preenche com o seu perfil. O Claude Code passa a funcionar como um assistente de carreira, com comandos como:

| Comando | O que faz |
|---|---|
| `/setup` | Entrevista você e monta o perfil (experiência, competências, preferências, deal-breakers) |
| `/scrape` | Busca vagas novas nos portais configurados (LinkedIn e outros adicionados com `/add-portal`) |
| `/rank` | Pontua as vagas contra o perfil, com subagentes que leem cada anúncio |
| `/apply` | Gera currículo (LaTeX/moderncv) e carta sob medida, que um agente revisor critica antes da versão final |
| `/interview` | Prepara a entrevista de uma candidatura |

Ele foi pensado para **uma pessoa, no terminal, interagindo com o Claude Code**.

## O que este projeto adiciona

| | ai-job-search | job-hunter-bot |
|---|---|---|
| Interface | Terminal (Claude Code interativo) | **Telegram**, no celular |
| Pessoas | Uma | **Várias**, cada uma com a sua pasta e o seu perfil |
| Acesso | Quem tem o repositório | **Aprovação pelo administrador** com um botão |
| Busca | Manual (`/scrape` + `/rank`) | **Automática às 3h**, com envio das melhores vagas **às 7h** |
| Candidatura | `/apply <url>` no terminal | Botão **📝 Gerar candidatura**: PDFs + texto da Gupy no chat |
| Operação | — | `/saude`, `/log`, `/usuarios` pelo próprio Telegram; avisos de falha ao admin |

Outros detalhes:

- **Portal da Gupy.** Na instalação de referência, um portal `gupy-search` foi gerado com o `/add-portal` do próprio framework (API pública de busca da Gupy), além do LinkedIn. Ele vive na pasta do ai-job-search, não neste repositório, e é copiado para cada candidato novo junto com `.agents/`. O ranking destaca vagas afirmativas PcD quando o perfil pede.
- **Escrita em `.claude/` sem `bypassPermissions`.** No modo não interativo (`claude -p`), o Claude Code nunca escreve na pasta `.claude/`, e regra de permissão nenhuma libera. O bot instrui o Claude a gravar em `.jobbot-staging/claude/…`. Depois de cada execução, o `StagingSync` copia **só** os arquivos de perfil de uma lista permitida e ignora links simbólicos e qualquer outra coisa.
- **Assinatura em vez de API.** O Claude roda com o token da assinatura (`claude setup-token`) e **um de cada vez** para todas as pessoas (trava global), para respeitar o limite de uso.
- **Só biblioteca padrão.** O runtime não tem nenhuma dependência: `urllib` para o Telegram, `subprocess` para o Claude Code, JSON com `flock` e escrita atômica para o estado.

## Como funciona para quem usa

1. A pessoa manda "oi" ao bot e o administrador recebe um pedido com **Aprovar / Recusar**.
2. Depois de aprovada, ela recebe uma explicação curta, manda o currículo (PDF/DOCX ou o PDF do LinkedIn) e faz o `/perfil`: o `/setup` do framework, conduzido pelo Telegram, uma pergunta por vez.
3. Toda madrugada o bot roda `/scrape` + `/rank` na pasta dela. Às 7h chegam até 5 vagas, com nota, pontos fortes, lacunas e os botões **Gerar candidatura / Não tenho interesse**.
4. **Gerar candidatura** roda o `/apply`. Em 10 a 20 minutos chegam o currículo e a carta em PDF e o texto para a Gupy.
5. **Quem se candidata é a própria pessoa**, pelo link da vaga, com a conta dela, e depois toca em **📨 Enviei**.

## Arquitetura

```
src/jobbot/
  config.py      Settings (env file + variáveis de ambiente)
  models.py      User, PendingRequest, Job, JobStatus
  storage.py     JsonStore (flock + escrita atômica) e repositórios
  telegram.py    Cliente da Bot API (long polling)
  claude.py      ClaudeRunner (claude -p, sessões, trava global) e StagingSync
  workspace.py   Cria a pasta de cada candidato a partir do ai-job-search
  services/      search · applications · profile · access · admin
  bot/           BotApp (polling + fila serial), roteamento e handlers
  prompts.py     Instruções enviadas ao Claude
  messages.py    Todos os textos em português mostrados no Telegram
deploy/          install.sh, units systemd (bot, busca 3h, envio 7h), env.example
tests/           pytest com Telegram e Claude falsos
```

Os services recebem as dependências pelo construtor (`TelegramClient`, `ClaudeRunner`, repositórios), e por isso os testes rodam sem rede e sem Claude. Detalhes e diagramas em [docs/architecture.md](docs/architecture.md).

## Instalação (VPS Linux com systemd)

Pré-requisitos: Python 3.12, [Claude Code](https://docs.claude.com/en/docs/claude-code), Bun (portais do ai-job-search), TeX Live (`lualatex`/`xelatex`) e poppler.

```bash
# 1. Usuário dedicado e framework de referência
sudo useradd -m -s /bin/bash jobbot
sudo -u jobbot git clone https://github.com/MadsLorentzen/ai-job-search ~jobbot/ai-job-search
# (renomeie o remoto para "upstream": as pastas dos candidatos são clonadas dele)

# 2. Segredos (chmod 600)
sudo -u jobbot mkdir -p ~jobbot/.config/jobbot
sudo cp deploy/env.example ~jobbot/.config/jobbot/env   # preencha os tokens e ADMIN_IDS

# 3. Instalar
sudo bash deploy/install.sh
```

A pasta de referência precisa de algumas regras de permissão no `.claude/settings.json`, porque o bot roda o Claude sem ninguém para aprovar comandos. A lista e o porquê estão em [docs/claude-permissions.md](docs/claude-permissions.md).

O token do Claude vem de `claude setup-token`, e o do Telegram, do [@BotFather](https://t.me/BotFather). O seu ID do Telegram vai em `ADMIN_IDS`. Para registrar uma pessoa que já tem pasta pronta:

```bash
cd /home/jobbot/jobbot/app && sudo -u jobbot python3 -m jobbot add-user --chat-id <ID> --name <Nome> --workspace /home/jobbot/ai-job-search
```

## Comandos

**Candidatos:** `/perfil` · `/fim` · `/buscar` (busca extra, 1 por dia) · `/status` · `/ajuda`, além de mandar o currículo em PDF/DOCX a qualquer momento.

**Administradores:** `/usuarios` · `/pendentes` · `/buscar [ID]` · `/log [N|erros]` · `/saude` · `/remover ID` · `/pcd ID sim|nao` · `/portal ID tag sim|nao`.

Portais exclusivos declaram `audience: <tag>` (ex.: `pcd`, `ti`) no frontmatter do `SKILL.md`; o bot grava `enabled: true|false` conforme `User.audiences[tag]`, definido com `/portal ID tag sim|nao` (`/pcd ID sim|nao` é atalho para a tag `pcd`) ou `add-user --pcd sim|nao` / `--portal TAG=sim|nao` (repetível). Tag ausente = não mexe; novos candidatos entram com `pcd` em `nao` e as demais tags intocadas (a pasta de referência traz os portais com `enabled: false`).

## Desenvolvimento

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --strict src
.venv/bin/pytest
```

## Uso responsável e limitações

- **Candidaturas são sempre enviadas pela própria pessoa.** O bot não guarda login ou senha de Gupy, LinkedIn ou outro portal.
- Os termos da Gupy e do LinkedIn restringem coleta automatizada. Este projeto foi feito para **uso pessoal, em volume baixo** (algumas buscas por dia). Respeite os termos de cada portal.
- Todos os candidatos rodam sob o mesmo usuário Linux, e o isolamento é por pasta. É pensado para um grupo de confiança (família, amigos), não como serviço público.
- A fila de candidaturas fica em memória: se o serviço reiniciar, basta tocar no botão de novo. A conversa do `/perfil` fica salva e sobrevive a reinícios, mas expira depois de 48 h sem `/fim`.

## Créditos e licença

- [ai-job-search](https://github.com/MadsLorentzen/ai-job-search), de Mads Lorentzen (MIT): todo o fluxo de busca, ranking e candidatura que o bot orquestra.
- Este repositório: licença MIT ([LICENSE](LICENSE)).

Projeto independente, sem afiliação com a Anthropic, a Gupy ou o LinkedIn. Claude e Claude Code são citados só para descrever as ferramentas usadas.
