# Hestia — AI developer guide (full context)

Written so that an AI (Claude Code via Forge, or any model) can keep developing Hestia without the
original conversation. Entry point: `CLAUDE.md`. Each module's truth: `Hestia-<Name>/hestia-<name>.md`.

## 1. Services and ports

| Service | Port | Container | Role |
|---|---|---|---|
| Hub | 19001 | hestia_hub | registry + **only** router (`/api/route/{svc}/{path}`), command discovery |
| Archive | 19002 | hestia_archive | the only DB (Postgres+pgvector, `hestia_db` 5432): memory, entities, chat, calendar_items, documents, feedback |
| Hecate | 19003 | hestia_hecate | provider gateway: Google/Microsoft OAuth, Calendar, Gmail (OAuth token only, **no IMAP**), the one mailbox watcher |
| Oracle | 19004 | hestia_oracle | LLM core: chat agent loop, classifier, memory, `/api/llm/*`, Claude Code runner |
| Hermes | 19005 | hestia_hermes | events/notifications (dedupe, retries) → Telegram |
| Scout | 19006 | hestia_scout | domain: real-estate listings from emails |
| Chronos | 19007 | hestia_chronos | calendars + **assistant agenda** (Hestia's own calendar) |
| Argus | 19008 | hestia_argus | monitoring: health, logs, alerts, repair rechecks, Forge proposals |
| Athena | 19009 | hestia_athena | two tracks: Sistema (idle: observe → think → propose, improvements to Forge) and Vita (module signals → links between areas → observations for the evening recap; `signals_client`) |
| Hephaestus | 19010 | hestia_hephaestus | remediation runbooks + **Forge** (self-development) |
| Dummy | 19011 | hestia_dummy | template/test service (ignore) |
| Iris | 19012 | hestia_iris | email domain logic (search/send/threads) via Hecate + **mail dispatcher** to module subscriptions |
| MCP | 19013 | hestia_mcp | MCP gateway exposing every service tool |
| Metis | 19014 | hestia_metis | datasets from feedback, LoRA training (agenda window) |
| WebUI | 19015 | hestia_webui | .NET 9 + Angular web client (chat, commands, calendar) |
| Themis | 19016 | hestia_themis | **central settings**: modules declare, clients/assistant read-change, user confirms proposals |
| Hygieia | 19018 | hestia_hygieia | self care: products and their life, routines as goals (no fixed days), planner with active conflicts, one-tap done, history/stats, few non-stacking reminders, WebUI plugin |
| Hercules | 19019 | hestia_hercules | gym coach: exercises, templates, live sessions offline (sync), records, adaptation by conversation, WebUI plugin |
| Wardrobe | 19017 | hestia_wardrobe | wardrobe: pieces, accessories, outfits, «Cosa mi metto», laundry/status, packing lists, stats, photos in Archive blobs, WebUI plugin |
| Plutus | 19020 | hestia_plutus | expenses «Spese» (domain `finance`): PayPal mails by push, bank statement PDF (Hype) from plugin or chat, categories, budgets, recurring, PayPal↔bank linking, WebUI plugin |
| Echo | 19021 | hestia_echo | **voice core**: speech → text and text → speech, files and streams in blocks, providers/chains/uses like Oracle a blocchi, keeps audio, WebUI page «Voce» |
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

- Oracle a blocchi (dossier `docs/work/2026-10-19-oracle-a-blocchi`): named **providers** `oracle.providers`
  (type = standard: ollama | openai | anthropic | gemini | claude_cli; keys only in env `ORACLE_KEY_<NAME>`),
  reusable **chains** `oracle.chains` (ordered provider/model steps; a quota error skips that model until its reset),
  **use cases** `<module>.<task>` declared by each module in its Hub registration (`capabilities.llm_usecases` via
  `hestia_common.oracle_usecases`) and mapped to chain/mode/thinking in `oracle.usecases`. One editor: Oracle →
  Cervello → Modelli. A new module that needs an LLM declares its use cases; it never names a provider or model.
- Brain mode `oracle.brain.mode` interna (chains) | esterna (Claude Code / Codex run the loop with Hestia's tools
  through `core.services.mcp_bridge`; Archive stays the session truth). Usage rows → Archive `llm-usage`.
- `/api/llm/generate {prompt, use_case}` plain prompt; `/api/llm/chat {use_case, messages, tools}` OpenAI-compatible
  along the use case's chain (Forge: `forge.codice`).
- `/api/llm/code`: Claude Code CLI (`claude -p`) in a Forge worktree under `/forge/worktrees`, auth
  `CLAUDE_CODE_OAUTH_TOKEN` (Pro/Max, from `claude setup-token`). Only for code tasks.
- Embeddings are truncated + renormalized to 768 (`ORACLE_EMBED_DIM`) because Archive is `Vector(768)`.

## 3a. Voice (Echo only)

- Dossier `docs/work/2026-10-20-modulo-voce`. Nobody but Echo calls speech engines; Oracle has no Whisper any more.
- Callers: `hestia_common.voice_client.VoiceClient(hub).transcribe(audio, mime, use_case=, keep=)` /
  `.speak(text, use_case=, fmt=, keep=)` / `.forget(notification_id=)`; streams `/api/voice/listen*` and `/say*`.
  Every use is declared in Hub capabilities `voice_usecases` (`hestia_common.voice_usecases.usecase`).
- Providers `echo.providers` (keys only in env `ECHO_KEY_<NAME>`), chains `echo.chains` with `direction`
  ascolto|voce, uses `echo.usecases`, mode `echo.mode` interna|esterna — edited on page «Voce → Motori».
- `keep` stores audio in Archive with its message/notification (`recording` never deleted automatically). Telegram
  refs are `tg:<chat>:<msg>`, WebUI refs `web:<session>:<msg>`.
- Notifications in voice: module setting `<module>.notifiche.voce` (`reminders.voice_setting`) + `reminder_event(voice=)`
  → payload `_voice` → Hermes adds the audio as an `update`.
- Live («Parla», Telegram `/live`) = the normal Oracle chat + Echo streams. Never an external live/realtime service.

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

### 5.1 Weekly plan (coaches)
A domain module that knows what is due (workouts, routines, budget review) is a **coach**: Hub tag `coach` +
`hestia_common.coach.CoachRouter` (needs/fit/placed/review) + `CoachClient` (done/skipped/changed, pushed to Chronos).
Never schedule the user's own week inside a module: Chronos plans it (`Hestia-Chronos/app/services/coach*.py`,
endpoints `/api/agenda/coach/*`, page «La tua settimana»). Need fields are generic; Chronos must not learn domain words.
Tag `outdoor` on a need = the planner avoids rainy/dark hours at Casa (Hecate forecast).

### 5.2 Weather and places
Weather lives only in Hecate (Open-Meteo): `/api/gateway/weather/*`, tools `weather_now`/`weather_forecast`.
Modules use `hestia_common.weather_client` through Hub; never call a weather API from a module. Places are the
personal setting `themis.personal.places` (one Casa; empty place = Casa). Outdoor activities live in Hercules
(`app/core/activities.py`): Hestia writes only to its own Google calendar «Allenamenti», never to Marko's events.

## 5a. Mail flow (push) — subscribe, never poll

Gmail → Hecate watcher (Chronos job `hecate.mail_watch`, default 15 min, history API; optional Gmail Pub/Sub streaming
pull via `HECATE_GMAIL_PUBSUB_*`, then the job is only a safety net) → Iris `POST /api/email/incoming` → match against
subscriptions → full mail stored in Archive as raw record under the subscriber's domain → doorbell
`POST route/<module>/<path> {owner, key, domain, count, reference_ids}`. A module declares rules with
`hestia_common.mail_client.MailClient(owner).subscribe_async(rules)`, processes `/api/archive/<domain>/unevaluated`
when rung and once at startup, may ask `backfill(key)`. Subscribers today: Scout (`scout:listings`), Plutus (PayPal).
Legacy rules a module stops declaring are retired with `AgendaClient.retire(keys)` (`POST /api/agenda/retire`).

## 5b. Settings (Themis) — tunables are data, not env

A new tunable is a **setting**, not an env var: declare it with `hestia_common.settings_client`
(`SettingsClient("<module>").declare([setting(...)])`, `app.include_router(settings.router())`,
`settings.start()` at startup, `settings.get(key)` where you used `os.getenv`). `apply="live"` values change
at runtime (`on_change`), `apply="restart"` ones are flagged until restart. Env keeps only secrets and
infrastructure (URLs, ports, paths). The assistant only *proposes* changes (Themis → Hermes → user).
Details: `Hestia-Themis/hestia-themis.md`.

## 5c. Export and import — every module moves its own data

`hestia_common.transfer`: a module lists its **sections** (`StoreSection` over its Archive store, or a `Section`
subclass) in `Transfer("<module>", hub, sections=[...])`, includes `transfer.router()` (`/api/transfer/*`) and adds
`transfer.capabilities()` to its Hub registration. Modes `append` · `merge` (default, newer wins) · `replace`;
import is a dry run unless `dry_run=false`; dependencies and children travel with the chosen items; files are
Archive blobs remapped on import. Themis exports the settings of every module (scopes system/profile/client, never
session); Oracle only memories (no chats); Chronos only the user's agenda rules. Never export secrets, tokens,
chats or sessions. File `.hestia` = gzip JSON, orchestrated by the WebUI page *Impostazioni → Esporta e importa*
and `tools/hestia_transfer.py`. Details: `Hestia-Shared/hestia-shared.md`, dossier `docs/work/2026-10-20-import-export/`.

## 6. Clients

- Telegram: `Hestia-Telegram/app` — routing, streaming, commands from Hub discovery, OAuth paste.
  Access is fail-closed on `ALLOWED_USER_ID`. Voice: `telegram_bot/services/voice_service.py`.
- WebUI: `Hestia-WebUI` — backend proxies everything via Hub; token from Telegram `/webui_token`;
  admin API guarded (`WEBUI_ADMIN_SECRET` or internal network only). Frontend rules:
  `Hestia-WebUI/frontend/DESIGN-SYSTEM.md`. Voice: `VoiceController.cs` (proxy to Echo), `voice.service.ts`
  (voice messages, «Ascolta»), `live-voice.service.ts` (Parla).
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
- Every service must re-register on the Hub every 60 s (keepalive), not only at startup: *Mappa* marks it offline
  after 180 s and a Hub restart forgets it.
- Mail: no module polls Gmail or keeps a mail job (Scout's `scout.email_cycle`, Hecate's `iris_email` fetcher and
  Iris `/api/email/ingest` are gone). New mail consumer = mail_client subscription. Pub/Sub is optional: without it
  the 15-min history check is the push source (Gmail can push only through Pub/Sub).
- Chat files for a module: declare `attachment_handlers` in Hub capabilities (Plutus: bank statement PDF); Oracle
  stores the file as an Archive blob (`owner_module=chat`) and hands the blob id to the module, else normal analysis.
- Open-Meteo is unreachable from the Claude cloud (403 at the proxy): weather tests use fake HTTP; a real check
  needs Marko's stack. Hermes has no «resolve» endpoint: to close a live question answered elsewhere, ingest an
  event with `payload.closes = <key>` (Wardrobe/Hercules pattern).
- No Marko PC needed for a real run: `python tools/cloud_test.py all` starts the whole stack in a Claude cloud
  session or a Codespace (fake LLM unless `GEMINI_API_KEY`), see `TESTING.md` «Banco di prova cloud».

## 8. Where to look

| Need | File |
|---|---|
| Global rules/contracts | `docs/ARCHITECTURE.md` (public front page: `readme.md`) |
| Dependency graph + flows | `architecture-and-flow-map.md` |
| Test plans | `TESTING.md`, `Hestia-*/tests/TESTING.md`; whole-stack run: `tools/cloud_test.py` |
| Task history | `CHANGELOG.md`, `docs/work/*/` |
