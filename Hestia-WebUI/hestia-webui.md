# Hestia-WebUI 🌐

Web-based chat interface for Project Hestia — the second client alongside Telegram.

## Status

**Phase 1: Backend Core** — DONE
**Phase 2: Angular Frontend** — DONE
**Phase 3: File Upload** — DONE (base64 inline via Hub routing)
**Phase 4: Settings + Commands** — DONE
**Phase 5: Chain of Thought** — DONE
**Phase 6: Feedback + Documents** — DONE
**Phase 7: Polish** — PENDING
**Phase 8: Docker + Deploy** — DONE
**Phase 9: Telegram Integration** — PENDING

## Stack

- **Backend**: .NET 9 / ASP.NET Core + SignalR
- **Frontend**: Angular 19 (standalone components)
- **Real-time**: SignalR WebSocket (Oracle NDJSON → typed JSON bridge)
- **UI**: Gemini + Mistral Le Chat inspired dark theme

## Architecture

```
Browser (Angular SPA)
    ↓ SignalR WebSocket + REST
WebUI Backend (ASP.NET Core :19015)
    ├── SignalR Hub /hubs/chat  →  Hub /api/route/oracle/api/chat → Oracle (NDJSON stream)
    ├── REST /api/webui/*       →  Hub /api/route/{service}/{path}
    └── TokenAuthMiddleware on EVERY request
```

**Critical: ALL inter-service calls go through Hub routing.** The WebUI backend NEVER calls Oracle directly.
Chat messages are sent to `{HUB}/api/route/oracle/api/chat` with `stream: true`. Hub forwards the request to
Oracle and streams the NDJSON response back with proper line delimiters (Hub adds `\n` after each line since
`requests.iter_lines()` strips them).

## Key Design Decisions

1. **Backend as security gateway** — frontend NEVER talks directly to internal services
2. **SignalR for real-time** — native reconnection, typed messages, cancellation support
3. **Single-token auth** — generated via Telegram, URL-based, one active at a time
4. **Mistral-style CoT** — numbered reasoning steps, expand/collapse, tinted container
5. **Same app/ structure** — mirrors all other Hestia services
6. **OracleStreamService as typed HttpClient** — uses `AddHttpClient<T>` for managed HttpClient lifecycle (NOT singleton + manual HttpClient)

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| WS | `/hubs/chat?access_token=...` | SignalR chat streaming (Oracle NDJSON bridge). Message `context` (drawer packet) is appended to that turn's client instructions |
| POST | `/api/webui/auth/login` | Validate access token |
| GET | `/api/webui/auth/status` | Token status |
| GET | `/api/webui/sessions/current` | Current session ID |
| POST | `/api/webui/sessions/clear` | Reset session |
| GET | `/api/webui/settings` | Get session settings |
| PUT | `/api/webui/settings` | Update settings |
| GET | `/api/webui/central-settings/{modules,items,revision,proposals}` | Impostazioni → Sistema: proxy to Themis (`items?module=&q=`) |
| GET | `/api/webui/central-settings/key/{key}/{options,history}` | choices for a setting · last changes |
| PUT/DELETE | `/api/webui/central-settings/key/{key}` | change (`{value}`) / reset to default — actor `webui` |
| POST | `/api/webui/central-settings/key/{key}/undo` · `presets/{module}/{id}/apply` | undo · apply a preset |
| POST | `/api/webui/central-settings/proposals/{id}/{approve,reject}` | answer an assistant proposal (`by: webui`, first answer wins) |
| GET | `/api/webui/commands` | Discover commands |
| POST | `/api/webui/commands/execute` | Execute command |
| POST | `/api/webui/feedback` | Submit feedback |
| POST | `/api/webui/chat/document` | Upload file (multipart) → base64 JSON via Hub → Oracle `/api/chat/document/json`, NDJSON streamed back (📎 in the chat bar) |
| GET | `/api/webui/documents` | List documents |
| DELETE | `/api/webui/documents/{id}` | Delete document |
| GET | `/api/webui/agenda/occurrences?start&end` | Assistant agenda occurrences (→ Chronos `/api/agenda`) |
| GET/POST | `/api/webui/agenda/items` | Items list / create (owner user) |
| PATCH/DELETE | `/api/webui/agenda/items/{key}` | Change (by=user) / cancel |
| POST | `/api/webui/agenda/items/{key}/skip` · `unskip` · `move` · `run` | Skip/restore occurrence, move one occurrence (exception), run now |
| POST | `/api/webui/agenda/parse` | Natural-language quick add → draft (→ Chronos `/api/agenda/parse`) |
| GET | `/api/webui/agenda/logs?service&at&minutes&contains` | Logs of a service around an occurrence: `{svc}/api/logs` (in-memory buffer) filtered to `at ± minutes` |
| GET | `/api/webui/agenda/feed.ics` · `feed-info` | Read-only ICS feed (→ Chronos `/api/agenda/ics`); auth = token **or** `?key=` = `WEBUI_ICS_KEY` (that path only) |
| GET | `/api/webui/forge/status` · `tasks` · `tasks/{id}` · `tasks/{id}/transcript` · `files` · `workdoc` · `tests` · `logs` · `events` | Sviluppo page (→ Hephaestus `/api/hephaestus/forge/*`) |
| POST | `/api/webui/forge/tasks` · `tasks/{id}/approve` · `reject` · `rollback` · `retry` | New task / follow-up (`source=ui`) and actions (`by=user`) |
| GET | `/api/webui/forge/repo/branches` · `tags` · `log` · `commits/{sha}` · `compare` · `tree` · `file` · `dossiers` | Read-only repository browser (→ Hephaestus `/api/hephaestus/repo/*`) |
| GET | `/api/webui/notifications?filter&source&before&limit` · `counts` | Notifiche page (→ Hermes `/api/notifications`, `client=webui`) |
| POST | `/api/webui/notifications/{id}/seen` · `seen-all` · `{id}/answer` | Global read state; answer (`{actionId}`, 409 = already handled elsewhere) |
| POST | `/api/notify` | Hermes notification client (`capabilities.notify_endpoint`), **internal network only** (not proxied, private IP): pushes `ReceiveNotification` on SignalR to every open browser; `retract` ignored (the inbox keeps everything) |
| GET | `/health` | Health check |
| POST | `/api/webui/admin/generate-token` · `revoke-token` · GET `token-status` · GET/POST `public-url` | Admin (Telegram / tunnel script). **Guarded**: `X-WebUI-Admin-Secret` = `WEBUI_ADMIN_SECRET` when set, else only direct loopback/private-network calls not coming through Cloudflare/proxy |

### Notifiche page (2026-10-10, `features/notifications/`, `services/notifications.service.ts`)

Hermes inbox shared by every client (Archive through Hermes). Sidebar item with unread badge; filters
*Da leggere · Da rispondere · Tutte*, module filter, toggle *Anche da altri client* (notifications that answer
a request made on another client, hidden by default); grouped by day; action buttons or outcome
("Approva · da Telegram · 10:42"). Live: SignalR `ReceiveNotification` (`notification` / `update`), refresh on
reconnect. Seen = shown on the page in a visible tab, or a toast in a focused tab (global: also seen on Telegram).
Toasts (*tutte / solo importanti / nessuno*) are a per-browser preference in the page's menu.

### Frontend structure (rewritten 2026-10-03)

Claude-like design system with themes (`src/app/core/theme`), UI kit (`src/app/ui`), shell with module registry
(`src/app/app.modules.ts`) and lazy feature pages: **Chat**, **Agenda di Hestia** (calendar: month/week/day/list,
sidebar mini-calendar + layers + module/type filters, popover details, editor with recurrence builder, drag & drop
move/resize, skip/restore, pause, run now, cancel, "only this occurrence" vs "whole series"), **Comandi & MCP**,
**Sviluppo** (Forge tasks + repository, see below), **Documenti**, **Impostazioni** (themes, tone, reasoning display, instructions, session).
Rules for new UI: **`frontend/DESIGN-SYSTEM.md`**.

### Sviluppo page (2026-10-04, `features/forge/`)

Codex / Claude Code style page for Forge, Hestia's self-development engine:
- **Task** mode: left = task list (search, filters Tutti/Aperti/Applicati/Non riusciti, live state dot);
  centre = the engine **conversation** (`forge-transcript`: messages, collapsible reasoning, every tool call with
  input/output, Edit shown as a mini diff, Bash as a command, final result with turns/cost) + engine summary +
  composer **"Chiedi una modifica"** (new task with `parent_task`: same dossier, outcome as context);
  right = context panel **Panoramica · File · Diff · Dossier · Test · Log · Ramo** (timeline, deploy plan,
  cost/turns, file list → diff, dossier markdown, full pytest output, engine/deploy logs, branch/compare).
  Header actions follow the state: Avvia / Avvia ora / Approva e applica / Rifiuta / Rollback / Riprova.
- **Repository** mode (`repo-browser`): commit log with branch graph (all branches toggle, file history),
  commit detail (files + diff), file browser at any ref (markdown preview), branches with ahead/behind and Forge
  task links, compare, tags, `docs/work` dossiers with version/status/progress, root CHANGELOG.
- Live: while a task works the page polls every 4 s (task + new transcript events), files every ~12 s;
  the list refreshes every 15 s. Deep link `/forge?task=<id>` (calendar Forge items: **Apri in Sviluppo**),
  `/forge?view=repo`.
- Width: ≥1280 px three columns; 861–1279 list + centre with *Conversazione / Dettagli*; ≤860 px one column
  (list → task with back button).

### Impostazioni → Sistema (2026-10-10, `features/settings/`)

- Tabs *Personali* (this client: theme, tone, notices, session) and *Sistema* (central settings, Themis).
  Deep link `/settings?tab=system&module=oracle`.
- Sistema: left = search (across all modules, done by Themis) + *Panoramica* + modules with a health dot and
  pending proposals; *Panoramica* = module cards (health from Hub, version, settings count, proposals) and the
  services without settings yet. A module = its groups; a group with presets shows *Economico / … /
  Personalizzato* (custom = values match no preset). Settings that declare `row` + `column` render as a table
  (Oracle: use case × fornitore / modello / riserva). Filters *Solo modificate* and *Avanzate (N)*.
- `<hx-setting>` (`setting-row.component.ts`): label, help, badges *modificato · riavvio necessario · modulo
  offline · al riavvio · personale*, the control and a clock popover with the last changes, *Annulla ultima*,
  *Ripristina predefinito*. Settings whose `depends_on` is not met are greyed out with "Attiva solo con …".
- `<hx-setting-control>` (`setting-control.component.ts`) picks the input by type (toggle, segmented ≤4 short
  options else dropdown, number + unit, model name with suggestions from `options`, 24h time, text, list one per
  line, JSON). Emits only complete values; Themis validates and its Italian error goes to a toast.
  Reusable outside the page (chat quick menu, P4).
- `central-settings.store.ts`: reloads what Themis answers after every change (toast with *Annulla*) and polls
  `revision` every 15 s while visible, so changes from Telegram, another browser or an approved proposal show up.
  Pending proposals appear as a banner with *Approva / Rifiuta*.

### Personal chat settings (2026-10-10)
- *Personali → Tono / Istruzioni personali* = your profile defaults in Themis (`oracle.chat.*`, every client);
  `SettingsController` proxies them, only *Ragionamento nelle risposte* stays in the WebUI.
- Chat header ⚙ (`<hx-chat-quick-settings>`): tone and instructions for **this conversation** (scope session,
  id chosen by the backend); *Come predefinito* drops the override. Oracle applies them (`client: "webui"`).

### "Crea con Hestia" drawer (2026-10-04, `features/assistant/`, `services/assistant.service.ts`)

- Right-side assistant panel (full screen ≤720 px), lazy (`@defer` in the shell). Open from anywhere: sidebar
  **Crea con Hestia**, **Ctrl/⌘+J**, or a page with a context packet `AssistantService.open({page, intent, label,
  hints, suggestions, prompt})` — calendar (*Nuovo → Crea con Hestia…*, editor *Chiedi a Hestia*, event details
  *Chiedi a Hestia*), Sviluppo (header, with the selected task), Comandi (header, with the selected command).
- Same Oracle stream (SignalR) and packets as the chat (reasoning, questions, notices), but its own `ChatService`
  instance on channel `assistant` and its own session id. ChatHub runs one stream per connection: the chat that
  sends last owns the events (`SignalRService.claim`), the other one stops its placeholder.
- The packet goes as `context` (`page=calendar; intent=create; giorno=…; ora=…; tz=…`) → ChatHub appends it to
  the client instructions with "act with the tools; if no tool can do it, propose a Forge task".
- Live refresh: `AssistantService.changed$` fires on `agenda.planned` / `action.done` / `forge.task` /
  subscription notices (from the drawer or the chat) → calendar and Sviluppo reload.

### Calendar view rules (2026-10-04, `features/calendar/calendar.prefs.ts`)

- **Navigation**: header arrows step by view (tooltip says "Giorno/Settimana/Mese precedente"); mini calendar →
  focuses that day (highlighted in every view; from month view it opens the day view, otherwise nothing visible
  would change); day headers / day numbers open the day.
- **24h only**: `fmt.time` = `HH:mm` regardless of locale; the editor uses kit `hx-date`/`hx-time`/`hx-datetime`
  (never native `datetime-local`, which shows AM/PM on en-US systems).
- **Windows** (Vista → Finestre): *corsia* (default: striped strip at the column edge spanning exactly the hours,
  label "01:00–07:00 …" that sticks to the top while scrolling, faint tint across the column, click = details with a
  plain-language explanation), *banda* (full-width band), *nascoste*.
- **Frequent rules** (≥ N runs/day from the RRULE, default 3): *compatte* (one "Ricorrenti" chip per rule per day,
  popover lists every time with ok/failed), *complete*, *nascoste*. Failed runs are never compacted.
- **Focused view** (default on, Vista popover; "N nascoste" bar with *Mostra tutto*): manual items always; the
  focused day shows everything; frequent rules next 7 days; rare rules next 3 occurrences or 7 days (first
  reached); one-off module items always; past module items only when failed, last 7 days, one per rule
  ("fallito ×N"). All thresholds editable; stored per browser with the other calendar prefs.
- **Create**: split "Nuovo" → *Evento libero* (generic editor) or *Da un modulo…* (wizard: pick a module template
  → fields + when/repeat → review). Templates come from the modules (`GET /api/webui/agenda/templates` → Chronos);
  created items are yours (`created_by=user`) and run the module action.
- **Aggiungi rapido** (sidebar, under Nuovo): "domani alle 15 dentista" → Chronos/Oracle parse → editor prefilled
  (you confirm). Failure → editor with the text as title.
- **Log del modulo** (event ⋯ menu): module logs ± 2/5/15/60 min around the occurrence (or its last run); the
  module keeps only its recent lines in memory, so old occurrences may show nothing.
- **Feed ICS (telefono)** (Nuovo menu): subscription URL when `WEBUI_ICS_KEY` is set, else download.
- **Working hours** (Vista: default 9–18 Mon–Fri): outside them the week/day grid is shaded; now line +
  auto-scroll to the current hour.
- Linked items (`parent`) show "Collegata a …" in the details.

### Chat features

- **Oracle questions**: `question` frames (free_text / single_choice / multi_choice / confirm, options as strings or
  `{label, value}`) render as a card above the input; the answer goes back via SignalR `question_answer`.
  `needs_input` frames show the missing fields.
- **Stop / answers during a stream**: SignalR `MaximumParallelInvocationsPerClient = 4` (default 1 queued `cancel`
  and question answers behind the running stream).
- **Upload**: 📎 next to the input (text in the box = instructions for the file).
- **Feedback** 👍/👎 sends `interaction_id` + the prompt/answer pair (`payload.instruction/output`, used by Metis);
  🔄 regenerates the last answer.
- **Command palette**: arguments from the command's `arguments_schema`; `oracle_natural` results are formatted by
  Oracle `/api/format` (like Telegram) and appear in the chat.
- **Settings**: tone / custom prompt become Oracle client instructions; *thinking display* is UI-only
  (hidden = no reasoning box, compact = collapsed, detailed = expanded).
- **System notices**: Oracle `notice` packets (memory saved, action done/failed, subscriptions…) render as
  `.hx-notice` pills under the answer (icon + semantic tint, never like chat text) and/or as toasts.
  Settings → *Messaggi di sistema*: where (sotto la risposta · popup · entrambi · solo importanti · nascosti),
  style (compatto · dettagliato), per-group toggles (memoria, azioni, notifiche, altro). Stored per browser
  (`NoticePrefsService`, localStorage). Notices arriving after `final` attach to the last answer.

## Known Constraints

- **Document uploads** travel as base64 JSON through Hub (Hub envelopes cannot carry multipart) to Oracle's
  `/api/chat/document/json`, the JSON twin of `/api/chat/document` (a `document` field on `/api/chat` was ignored).
- `HubClient` raises when the routed `status_code` ≥ 400 (target errors used to look like success).
- **OracleStreamService** is transient (managed by `IHttpClientFactory`), not singleton. This means the
  `_oracleReady` flag resets per-resolution but `IsReady` is not critical for the streaming path.
- **NDJSON streaming** depends on Hub correctly adding `\n` delimiters between lines. The `iter_lines()`
  method in Python `requests` strips newlines; Hub's streaming path must re-add them.

## Environment Variables

All documented in `docker-compose.yml`. Key vars:
- `Hestia__HubApiUrl` — Hub endpoint
- `WebUI__SecretKey` — Token signing key (auto-generated; an empty value no longer replaces the random key)
- `WEBUI_ADMIN_SECRET` — optional shared secret for the admin API (set the same value for `telegram`; the tunnel
  script reads it from the environment)
- `WEBUI_PUBLIC_HOST_SUFFIXES` — hosts accepted for public-URL auto-detection (default `.trycloudflare.com`)
- `WebUI__TokenLifetimeHours` — Token expiry (default 72h)
- `WEBUI_ICS_KEY` — optional (≥16 chars): key of the read-only agenda ICS feed for phone calendars
  (`/api/webui/agenda/feed.ics?key=`); empty = feed only with the login token

## Local Development (Windows host, outside Docker)

- `appsettings.json` default `Hestia__HubApiUrl=http://hestia_hub:19001/api` is the **Docker-network** name — it only resolves inside the `hestia_net` network.
- `Properties/launchSettings.json` overrides it with `http://localhost:19001/api` (Hub's published port) so `dotnet run` / VS Code F5 works directly on the Windows host.
- Ollama must be running on the host for Oracle's primary LLM (the Oracle container reaches it via `host.docker.internal:host-gateway`, declared as `extra_hosts` in the compose files).

## Docker

```bash
docker compose -f Hestia-WebUI/docker-compose.yml up --build -d
```

Multi-stage build: Angular (node) → .NET SDK → ASP.NET runtime.
Built Angular app served as static files from `wwwroot/`.

## Security

- Single-user, single-active-token policy
- Token: 256-bit random, validated constant-time
- CSP, X-Frame-Options, XSS protection on all responses
- Public URL: set explicitly by `cloudflare-tunnel.bat` (wins); Host-header auto-detection only for real
  Cloudflare traffic (`Cf-Connecting-Ip`) on allowed suffixes — an arbitrary Host could redirect the login
  link (and the token) to another domain
- Admin API guarded (see Endpoints); Telegram mints tokens only through it (no local fallback, no token in Archive memory)
- Rate limiting TBD
- Token state = SHA-256(token + salt) with its own persisted salt in `/app/data/token_state.json`
  (`hestia_webui_data` volume, `WEBUI_TOKEN_STATE_FILE`): survives restarts. The salt used to be
  `WebUI:SecretKey`, random per start → every restart invalidated the token. Nothing is written to Archive
  memory any more (the clear token was readable by Oracle's memory tools).
- `TokenAuthMiddleware` protects `/api/webui/*` (header `X-Access-Token` or `?token=`); exempt: login,
  command list, `/api/webui/admin/*` (guarded by `AdminGuard`), `/health`, static files, `/hubs/chat` (auth in the hub).

## Assistant presence

Backend: `PresencePinger` (60 s debounce) pings Chronos on authenticated non-GET `/api/webui/*` actions (setting `chronos.presence.count_ui_actions`); `PresenceController` exposes `GET /api/webui/presence`, `GET /api/webui/presence/history`, `POST`/`DELETE /api/webui/presence/dnd`. Frontend: presence badge in the shell sidebar (polled every 60 s and on tab focus) with a popover: state, last interaction, activities, effects, Non disturbare on/off, link to Impostazioni.
