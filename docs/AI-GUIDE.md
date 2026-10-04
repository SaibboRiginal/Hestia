# Hestia — AI developer guide (full context)

Written so that an AI (Claude Code via Forge, or any model) can keep developing Hestia without the
original conversation. Entry point: `CLAUDE.md`. Each module's truth: `Hestia-<Name>/hestia-<name>.md`.

## 1. Services and ports

| Service | Port | Container | Role |
|---|---|---|---|
| Hub | 19001 | hestia_hub | registry + **only** router (`/api/route/{svc}/{path}`), command discovery |
| Archive | 19002 | hestia_archive | the only DB (Postgres+pgvector, `hestia_db` 5432): memory, entities, chat, calendar_items, documents, feedback |
| Hecate | 19003 | hestia_hecate | provider gateway: Google/Microsoft OAuth, Calendar, Gmail (OAuth token only, **no IMAP**) |
| Oracle | 19004 | hestia_oracle | LLM core: chat agent loop, classifier, memory, `/api/llm/*`, Claude Code runner |
| Hermes | 19005 | hestia_hermes | events/notifications (dedupe, retries) → Telegram |
| Scout | 19006 | hestia_scout | domain: real-estate listings from emails |
| Chronos | 19007 | hestia_chronos | calendars + **assistant agenda** (Hestia's own calendar) |
| Argus | 19008 | hestia_argus | monitoring: health, logs, alerts, repair rechecks, Forge proposals |
| Athena | 19009 | hestia_athena | idle cognition: observe → think → propose (improvements to Forge) |
| Hephaestus | 19010 | hestia_hephaestus | remediation runbooks + **Forge** (self-development) |
| Dummy | 19011 | hestia_dummy | template/test service (ignore) |
| Iris | 19012 | hestia_iris | email domain logic (search/send/threads) via Hecate |
| MCP | 19013 | hestia_mcp | MCP gateway exposing every service tool |
| Metis | 19014 | hestia_metis | datasets from feedback, LoRA training (agenda window) |
| WebUI | 19015 | hestia_webui | .NET 9 + Angular web client (chat, commands, calendar) |
| Swagger | 19000 | hestia_swagger | API docs (`Hestia-Swagger/swagger.yml`) |
| Telegram | — | hestia_telegram | main client (bot) |
| Atlas | host | — | HTML fetch/scrape, runs on the host (`run_host.bat`) |

## 2. Request flow (chat)

Client (Telegram/WebUI) → Hub → Oracle `/api/chat` (NDJSON stream: `status`, `thinking`, `token`,
`question`, `final`, `notice`, `error`) → classifier picks domain → agent loop calls tools (MCP tools of
services, discovered via Hub) → answer formatted (HTML subset for Telegram) → memory extraction
(selective) → session summary to Archive.

Tools: every service declares `MCPTool(name, description, parameters, method, path, clients,
response_mode, response_prompt, telegram_visible, telegram_group)` (`hestia_common.mcp_helpers`).
Hub turns them into commands (`/api/discovery/commands?client=telegram|ui`). Paths may contain
`{name}`/`$name` placeholders, filled by Oracle/Telegram/WebUI/MCP. `mount_missing_rest_routes`
serves the declared REST path of handler-only tools — call it after the app's own routes.

## 3. LLM access (Oracle only)

- Use cases in Oracle `.env`: `MODEL_USECASE_<GENERIC|REASONING|CODE|EMBEDDING>_{PROVIDER,MODEL,
  FALLBACK_PROVIDER,FALLBACK_MODEL}` (ollama | gemini).
- `/api/llm/generate` plain prompt; `/api/llm/chat` OpenAI-compatible with profiles: `local` (Ollama +
  CODE model) and `cloud` (Gemini OpenAI-compat + CODE fallback model + `GEMINI_API_KEY`), both derived
  automatically; `ORACLE_LLM_PROFILE_<NAME>_*` only to add/override.
- `/api/llm/code`: Claude Code CLI (`claude -p`) in a Forge worktree under `/forge/worktrees`, auth
  `CLAUDE_CODE_OAUTH_TOKEN` (Pro/Max, from `claude setup-token`). Only for code tasks.
- Embeddings are truncated + renormalized to 768 (`ORACLE_EMBED_DIM`) because Archive is `Vector(768)`.

## 4. Forge (self-development) — how a change ships

1. `POST /api/hephaestus/forge/tasks {request, services?, engine?, workdoc?}` (Telegram tool
   `forge_develop`, "sviluppa …"). Athena/Argus also propose tasks.
2. Permission modes per engine group: `ask` (wait for user) / `auto` (start, merge needs approval) /
   `full_auto`. Defaults: cloud = ask, local = auto. Claude tasks from autonomous sources are
   **budgeted**: run only in agenda windows `forge.claude_nights` / `forge.claude_final` before the
   weekly Pro reset; user requests run any time.
3. Worktree `/forge/worktrees/<id>` on branch `auto/forge/<id>` (repo mounted at `/repo` in both
   Hephaestus and Oracle). Engine edits files following the work protocol (`docs/work/<WORKDOC>/`).
4. Forge commits, runs `HEPHAESTUS_FORGE_TEST_CMD` on touched services' tests, state
   `awaiting_review` → user approves (`forge_approve`) → `merge --no-ff` into the checked-out branch.
5. Deploy (`HEPHAESTUS_FORGE_DEPLOY_CMD=builtin`): `forge/deployer.py` plans restarts of
   `hestia_<svc>` via Docker socket (code is volume-mounted, a restart activates it); Dockerfile /
   requirements / WebUI changes need a manual `up-all.bat --build <svc>` (user is told). Shared lib
   change → all Python services restart. Hephaestus restarts itself last.
6. Health check via Hub; failure → automatic revert (rollback) + restart.

Every Forge task is mirrored in the agenda (`forge.task.<id>`). States: proposed, scheduled, queued,
running, awaiting_review, approved, merging, merged, deployed, rolled_back, rejected, failed, no_changes.

## 5. Assistant agenda (Chronos) — scheduling is data

Item types: `event`, `task` (one-off action), `job` (recurring action, RRULE), `window` (period when
work is allowed). Actions `{service, method, path, body}` are fired through Hub by Chronos' worker.
Modules register defaults (idempotent by key) with `hestia_common.agenda_client.AgendaClient`
(`register_async`, `is_open(key, fallback)`, `should_self_run(key, interval)`, `plan`, `show`, `done`).
Registered keys: see `Hestia-Chronos/hestia-chronos.md` ("Who plans what").

## 6. Clients

- Telegram: `Hestia-Telegram/app` — routing, streaming, commands from Hub discovery, OAuth paste.
  Access is fail-closed on `ALLOWED_USER_ID`.
- WebUI: `Hestia-WebUI` — backend proxies everything via Hub; token from Telegram `/webui_token`;
  admin API guarded (`WEBUI_ADMIN_SECRET` or internal network only). Frontend rules:
  `Hestia-WebUI/frontend/DESIGN-SYSTEM.md`.
- Response packets: clients render the standard packets — spec in `Hestia-Shared/hestia-shared.md`
  § Response packets. System messages = `notice` (never styled like chat). Telegram: `ReplyRenderer` +
  `chat_settings.SETTINGS` (one schema → `/settings` panel). WebUI: `.hx-notice` + `NoticePrefsService`.
- Never send the answer twice: `final` is rendered exactly once (Telegram edits the status message into it).

## 7. Gotchas learned the hard way

- Windows host: git inside containers needs `safe.directory '*'` (already in Dockerfiles); files may
  have CRLF; `.bat` scripts: escape `(` `)` inside `if` blocks as `^(` `^)`.
- `.gitignore` must not use broad patterns like `token*` (hid `TokenManager.cs` on Windows).
- PowerShell 5 writes UTF-8 **with BOM** → read text files with `utf-8-sig`.
- Hub returns HTTP 200 even when the target failed: always check `status_code` in the envelope.
- Google OAuth: consent screen "In production" (Testing kills tokens in 7 days); OOB redirect is dead;
  tunnel redirect URI changes at every quick-tunnel start.
- Embedding size must match Archive (768) — mismatched vectors are silently dropped.
- SignalR (WebUI): long-running hub methods block other invocations unless
  `MaximumParallelInvocationsPerClient > 1`.
- Never block FastAPI startup (e.g. waiting for another service): do it in a background thread.
- WebUI Docker build has no internet for Angular font inlining → fonts via `<link>` + `fonts.inline=false`.
  The WebUI image bakes the frontend: after a pull, `docker compose ... up -d --build webui` (no volume mount).
- Telegram HTML parse mode supports only a small tag subset (b, i, u, s, code, pre, a, blockquote).

## 8. Where to look

| Need | File |
|---|---|
| Global rules/contracts | `docs/ARCHITECTURE.md` (public front page: `readme.md`) |
| Dependency graph + flows | `architecture-and-flow-map.md` |
| Test plans | `TESTING.md`, `Hestia-*/tests/TESTING.md` |
| Task history | `CHANGELOG.md`, `docs/work/*/` |
