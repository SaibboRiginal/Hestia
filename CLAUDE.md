# CLAUDE.md — read first (Claude Code, Forge, any AI working on Hestia)

Hestia = personal AI assistant made of FastAPI microservices (+ an Angular/.NET WebUI) in Docker.
It **develops itself**: the user asks a change (Telegram/WebUI) → Hephaestus **Forge** runs a coding
engine (Claude Code inside Oracle, or a local/cloud model) in a git worktree → tests → user approves →
merge → container restart → health check → auto-rollback on failure.

Detailed knowledge (architecture, every module, gotchas, history): **`docs/AI-GUIDE.md`**.
UI work: **`Hestia-WebUI/frontend/DESIGN-SYSTEM.md`**.

## Work protocol — MANDATORY for every task (human or AI)

1. `docs/work/<YYYY-MM-DD>-<slug>[-<taskid6>]/` (Forge gives you the name as `WORKDOC`).
   If it exists, **read `PROGRESS.md` first and continue from there**.
2. `SPEC.md` — goal, scope, acceptance criteria, design decisions. Written **before** coding.
3. `PROGRESS.md` — checklist `- [ ]` / `- [x]`; update after every step. If you stop midway it must
   say exactly what is left, so the next run (or another model) can resume.
4. `CHANGELOG.md` in the same folder — every change of the spec, dated, with the reason.
5. Root `CHANGELOG.md` — one line per finished task under the date.
6. Docs follow code: behaviour change → `Hestia-<Name>/hestia-<name>.md`; endpoint change →
   `Hestia-Swagger/swagger.yml`; env change → `.env.example` + compose comments; global rule → `readme.md`.

## Non-negotiable rules

- **Hub is the only door**: service→service HTTP = `POST {HUB_API_URL}/route/<svc>/<path>` with
  envelope `{method, headers, query, body, timeout_seconds}` → `{status_code, payload}`. No direct URLs.
  (Single exception: Telegram → WebUI admin API, guarded.)
- **Oracle is the LLM core**: nobody else calls model providers. Use `/api/llm/generate` (plain),
  `/api/llm/chat` (OpenAI-compatible, profiles `local`/`cloud`), `/api/llm/code` (Claude Code).
- **Archive is the only DB owner**. Hecate owns external providers (Google/Microsoft OAuth, Gmail).
- Core services stay generic; domain logic lives in domain modules (Scout = real estate).
- Scheduling = **assistant agenda** (Chronos): register rules with `hestia_common.agenda_client`,
  never hardcode hours/loops. User edits win; paused/cancelled = user decision (no fallback).
- Never touch `.env`, tokens, `data/` folders; never commit secrets. Mail = Gmail via OAuth token only (no IMAP).
- Logs: `event=<snake_case> key=value`; recovery/fallback paths prefixed `[🔄]`. No task is abandoned.
- Prompts for local models: "caveman" style (short, dense) — every token is paid each turn.

## Repo map

```
Hestia-<Name>/            one service: app/ (code), tests/ (pytest), hestia-<name>.md, Dockerfile
Hestia-Shared/hestia_common  shared libs (logging, MCP tools, agenda client, startup)
Hestia-WebUI/             .NET 9 backend (app/) + Angular frontend (frontend/)
Hestia-Swagger/swagger.yml   API contract of every service
docker-compose.global.yml whole stack;  up-all.bat [--build] starts it
docs/                     AI-GUIDE.md, work/ (task dossiers)
```

## Run tests (inside the Hephaestus/Oracle containers all deps are installed)

```
python -m pytest -q -m "unit or api or format" Hestia-<Name>/tests
```
Markers: unit, api, format (fast, no network) · llm_live / integration (need Ollama). Fix until green;
add a regression test for every bug fixed.

## What NOT to do

- Don't add a new service-to-service URL, a new LLM client, or a DB connection outside Archive.
- Don't write timers/loops for periodic work → agenda job/window.
- Don't change public endpoints without updating swagger + callers (Telegram, WebUI, MCP).
- Don't commit/push yourself when running inside Forge (Forge commits the worktree).
