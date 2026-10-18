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
3. **Single-token auth** — generated via Telegram, URL-based, one active at a time; **not asked on the home
   network** (LAN/localhost), always asked through the Cloudflare tunnel (see Security → Local access)
4. **Mistral-style CoT** — numbered reasoning steps, expand/collapse, tinted container
5. **Same app/ structure** — mirrors all other Hestia services
6. **OracleStreamService as typed HttpClient** — uses `AddHttpClient<T>` for managed HttpClient lifecycle (NOT singleton + manual HttpClient)

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| WS | `/hubs/chat?access_token=...` | SignalR chat streaming (Oracle NDJSON bridge). Message `context` (drawer packet) is appended to that turn's client instructions |
| POST | `/api/webui/auth/login` | Validate access token |
| GET | `/api/webui/auth/status` | Token status |
| GET | `/api/webui/auth/access` | `{local, tokenRequired}` — asked by the browser at start, no token needed |
| GET | `/api/webui/plugins/catalog` | Client plugins (Hub catalog `client=webui`), 15 s cache |
| GET | `/api/webui/plugins/{module}/bundle/{file}` | Module WebUI bundle file (via Hub) |
| ANY | `/api/webui/plugins/{module}/call/{path}` | Plugin → its own module; 403 outside its `api_prefix` |
| GET | `/api/ai/widgets?q=` · `/api/ai/dashboards` | Assistant tools `webui_widgets` / `webui_dashboards` (internal, via Hub) |
| POST | `/api/ai/mcp` | Same tools as MCP JSON-RPC (`capabilities.mcp_endpoint`, domains system/settings); was `/mcp` before 2026-10-18 |
| POST | `/mcp` | **Public MCP door for external AIs** (`McpDoorController`): body + `Authorization: Bearer` → Hub → Hestia-MCP `/mcp/external` (token, scope, rate limit there); no WebUI login, always a token, also at home. GET/DELETE → 405 |
| GET | `/api/webui/plugins/{module}/image?path=` | Module image as bytes |
| GET/POST | `/api/settings/effective` · `/api/settings/reload` | WebUI's own Themis settings (internal network only) |
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
| GET | `/api/webui/chat/context` | Context gauge of the current conversation → Oracle `/api/chat/context` (provider in use, window %, this conversation's tokens) |
| POST | `/api/webui/chat/compact` | Compact the current conversation → Oracle `/api/chat/compact` |
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
| POST | `/api/webui/forge/pause` | `{paused}` — manual pause of autonomous development (→ Hephaestus `/api/hephaestus/forge/pause`, `by=user`) |
| GET | `/api/webui/forge/repo/branches` · `tags` · `log` · `commits/{sha}` · `compare` · `tree` · `file` · `dossiers` | Read-only repository browser (→ Hephaestus `/api/hephaestus/repo/*`) |
| GET | `/api/webui/notifications?filter&source&before&limit` · `counts` | Notifiche page (→ Hermes `/api/notifications`, `client=webui`) |
| POST | `/api/webui/notifications/{id}/seen` · `seen-all` · `{id}/answer` | Global read state; answer (`{actionId}`, 409 = already handled elsewhere) |
| POST | `/api/notify` | Hermes notification client (`capabilities.notify_endpoint`), **internal network only** (not proxied, private IP): pushes `ReceiveNotification` on SignalR to every open browser; `retract` ignored (the inbox keeps everything); repeat chains: `update superseded` removes the old item from the Notifiche page, `repeat.text` shown as a badge on cards and in the toast |
| GET | `/health` | Health check |
| POST | `/api/webui/admin/generate-token` · `revoke-token` · GET `token-status` · GET/POST `public-url` | Admin (Telegram / tunnel script). **Guarded**: `X-WebUI-Admin-Secret` = `WEBUI_ADMIN_SECRET` when set, else only direct loopback/private-network calls not coming through Cloudflare/proxy |

### Client plugins, Home and dashboards (2026-10-17, `features/plugins/`, dossier `docs/work/2026-10-17-client-plugins/`)

- Modules declare WebUI contributions (pages, widgets, quick actions) with `hestia_common.plugin_client`; the Hub
  catalog lists them. `PluginCatalog` (.NET) caches it 15 s; `PluginsController` serves bundles and proxies each
  plugin's calls only under its own `api_prefix` (no other module, no Hub admin).
- `PluginsService` (Angular): polls the catalog (60 s, on focus, on `online`), fetches each bundle with the token and
  imports it as a blob module; the bundle imports the shared SDK (`/plugins/_sdk/sdk.js`, built from
  `Hestia-Shared/webui-sdk` in the Dockerfile) through the import map in `index.html`. Elements get `host` + `ctx`.
- **Home** (`/home`, first module) = quick-action strip + dashboard grid; until edited it is composed from widgets
  marked `auto` of the domain modules. A ready-made *Sistema* dashboard (`/d/sistema`) takes the core modules' `auto`
  widgets (hidden while there is none; deleting it leaves a `removed` marker in `webui.dashboards`). Other dashboards at `/d/:id` (tabs + sidebar "Dashboard"). Edit mode: add, drag, size, configure,
  remove; Oracle-created dashboards carry `created_by: oracle`.
- Module pages at `/p/<module>/<page>` (sidebar "Moduli", core modules under "Sistema"; detail pages hidden).
  Sidebar: one scroll area between a fixed top and bottom, collapsible sections, entries pinned to "Fissati" leave
  their section; plugin pages may show a `badge` counter (DESIGN-SYSTEM §9). Ctrl/⌘+K palette: quick actions,
  module pages, dashboards, WebUI pages.
- Client config (Themis, scope user, layer `client`): `webui.plugins.hidden`, `webui.plugins.order`,
  `webui.home.quick` (pinned chips), `webui.dashboards` (`{dashboards: [...]}`), `webui.plugins.prefs`,
  `webui.sidebar.pinned` (pinned sidebar entries, in order), `webui.sidebar.collapsed` (closed sidebar sections).
  Impostazioni → Personali → "Moduli e Home" toggles each module/contribution.
- PWA: `public/manifest.webmanifest` + `public/sw.js` (registered in production only). Offline the shell, catalog,
  settings and plugin bundles come from cache; plugin calls reject with `offline`; sidebar shows an "offline" badge.
  The home-network "no token" answer is remembered for offline starts. Logout clears the data cache.
- Dashboards from the chat: Hestia reads `webui_widgets` / `webui_dashboards` and proposes `webui.dashboards`
  (Themis, layer `client:webui`); the confirm card appears in the same chat (ChatHub sends the answer with
  `client: webui`, shows the outcome as a notice) and the WebUI reloads its config (also every 60 s).
- CSP: `script-src … blob:` (plugin modules) and `img-src … https:` (module photos).

### Notifiche page (2026-10-10, `features/notifications/`, `services/notifications.service.ts`)

Hermes inbox shared by every client (Archive through Hermes). Sidebar item with unread badge; filters
*Da leggere · Da rispondere · Tutte*, module filter, toggle *Anche da altri client* (notifications that answer
a request made on another client, hidden by default); grouped by day; action buttons or outcome
("Approva · da Telegram · 10:42"). Live: SignalR `ReceiveNotification` (`notification` / `update`), refresh on
reconnect. Seen = shown on the page in a visible tab, or a toast in a focused tab (global: also seen on Telegram).
Toasts (*tutte / solo importanti / nessuno*) are a per-browser preference in the page's menu.

### Frontend structure (rewritten 2026-10-03)

Claude-like design system with themes (`src/app/core/theme`), UI kit (`src/app/ui`), shell with module registry
(`src/app/app.modules.ts`) and lazy feature pages: **Chat**, **Agenda di Hestia** (calendar: month/week/day/list — list has an *Adesso* divider and the outcome of past items —
sidebar mini-calendar + layers + module/type filters, popover details, editor with recurrence builder, drag & drop
move/resize, skip/restore, pause, run now, cancel, "only this occurrence" vs "whole series"), **Comandi & MCP**
(tools from Hestia-MCP `tools/list` as client `webui`, run with `tools/call` — `HubClient.McpListToolsAsync` /
`McpCallToolAsync`; arguments come from each tool's JSON schema),
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
- Page header **Pausa / Riprendi** (2026-10-11): manual pause of Forge (`hephaestus.forge.paused`); while paused a
  banner over the task list says nothing starts on its own; resuming asks confirmation and restarts nothing held.
- Who proposed each task: list rows show *Tu* or the module (Athena, Argus, Riparazioni) and the filter **Dai moduli**;
  the task header says "proposto da …". Proposed/scheduled tasks have an engine picker next to **Avvia**.
- **Repository** mode (`repo-browser`): commit log with branch graph (all branches toggle, file history),
  commit detail (files + diff), file browser at any ref (markdown preview), branches with ahead/behind and Forge
  task links, compare, tags, `docs/work` dossiers with version/status/progress, root CHANGELOG.
- Live: while a task works the page polls every 4 s (task + new transcript events), files every ~12 s;
  the list refreshes every 15 s. Deep link `/forge?task=<id>` (calendar Forge items: **Apri in Sviluppo**),
  `/forge?view=repo`.
- Width: ≥1280 px three columns; 861–1279 list + centre with *Conversazione / Dettagli*; ≤860 px one column
  (list → task with back button).

### Impostazioni (2026-10-10, VS Code-like since 2026-10-11, `features/settings/`)

- One page, no tabs: a search box in the header (Ctrl/⌘+F, Esc clears) over **every** setting, personal and
  system, filtered locally and instantly (all words must appear in label, help, key, group or module); a
  resizable sidebar (drag the edge, double-click resets, width kept per browser) with *Personali* (Aspetto,
  Assistente, Messaggi di sistema, Sessione) and *Sistema* (Panoramica + modules with health dot and settings
  count; while searching every entry shows its number of matches, the others are dimmed).
  Deep links `/settings?section=assistente`, `/settings?tab=system`, `/settings?tab=system&module=oracle`.
- Personali use the same rows as Sistema (`<hx-setting-shell>`); tone and instructions are the profile values in
  Themis (WebUI settings API), any other `scope: user` setting a module declares appears under *Assistente*
  as a normal `<hx-setting>`. User-scope settings are not repeated in the module pages.
- Sistema: *Panoramica* +
  modules with a health dot and pending proposals; *Panoramica* = module cards (health from Hub, version, settings count, proposals) and the
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
- `central-settings.store.ts`: loads every setting once (`items` without filters), reloads what Themis answers after every change (toast with *Annulla*) and polls
  `revision` every 15 s while visible, so changes from Telegram, another browser or an approved proposal show up.
  Pending proposals appear as a banner with *Approva / Rifiuta*.

### Personal chat settings (2026-10-10)
- *Personali → Tono / Istruzioni personali* = your profile defaults in Themis (`oracle.chat.*`, every client);
  `SettingsController` proxies them, only *Ragionamento nelle risposte* stays in the WebUI.
- Chat header ⚙ (`<hx-chat-quick-settings>`): tone and instructions for **this conversation** (scope session,
  id chosen by the backend); *Come predefinito* drops the override. Oracle applies them (`client: "webui"`).

### Mode, reasoning display, context gauge (2026-10-11, `docs/work/2026-10-11-chat-modalita-contesto/`)
- Composer `<hx-chat-mode>`: Auto · Rapida · Pensata · CoT (Oracle `oracle.chat.mode`). Loads the value of this
  conversation from Themis, a pick is saved with scope session and sent with every message; ChatHub passes
  `auto|quick|thinking|cot`, anything else as "" (= Oracle uses the setting; retry uses it too). Default in
  Personali → Assistente (generic Themis row). The drawer keeps `auto`.
- Reasoning display (WebUI presentation, `thinking_display` in the WebUI session store): hidden · **compact** ·
  detailed · live — default compact (was hidden, so nothing showed). `<chat-thinking [display]>`: compact closed,
  detailed open with full reasoning and tool results, live open while working and closed when the answer comes;
  a click wins. Editable from the chat ⚙ popover and Personali; the drawer follows it too.
- Header `<hx-chat-context>`: ring with the % of the context window of the provider in use; popover with
  provider/model and billing kind, context breakdown, this conversation's tokens (input / cache / output,
  calls, API-equivalent cost for Claude CLI) and *Compatta*. Refreshed when an answer ends or the conversation
  changes.

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
- `TokenAuthMiddleware` protects `/api/webui/*` (header `X-Access-Token` or `?token=`; path compared
  lowercase, routing is case-insensitive); exempt: login, `auth/access`, command list, `/api/webui/admin/*`
  (guarded by `AdminGuard`), `/health`, static files, `/hubs/chat` (auth in the hub).
- **MCP door** `POST /mcp` (2026-10-18, `McpDoorController`): outside `/api/webui/`, so neither the WebUI token
  nor local access applies; it needs `Authorization: Bearer <access token>` always (also at home) and Hestia-MCP
  checks it (401 / 403 / 429). Only the header and the JSON body are forwarded (max 1 MB). The WebUI's own module
  MCP moved to `/api/ai/mcp` to free the path.
- **Local access without token** (`Services/LocalAccess.cs`, SPEC `docs/work/2026-10-11-webui-local-access`):
  the middleware and the hub skip the token only when ALL hold — Themis `webui.auth.local_without_token`
  on (default; the assistant cannot propose it), no Cloudflare/proxy header (`Cf-Connecting-Ip`, `Cf-Ray`,
  `Cdn-Loop`, `Cf-Warp-Tag-Id`, `X-Forwarded-*`, `X-Real-Ip`, `Forwarded`…), Host not under
  `WEBUI_PUBLIC_HOST_SUFFIXES` nor the public URL host, TCP peer loopback/private. Cloudflare always adds its
  headers and a client cannot remove them, so only their absence opens: a forged header only adds the token.
  No forwarded-headers middleware runs, so the peer address is the real socket. **Never port-forward 19015
  on the router** (Docker Desktop shows every published-port client as a private gateway address): outside
  access goes through the tunnel only. The Angular app asks `GET /api/webui/auth/access` at start: local →
  no login page and no "Esci" button.
- WebUI declares its own Themis settings (`Services/WebUISettings.cs`, the .NET counterpart of
  `hestia_common.settings_client`): register via Hub at start (retry 60 s, re-assert hourly), live reload.

## Assistant presence

Backend: `PresencePinger` (60 s debounce) pings Chronos on authenticated non-GET `/api/webui/*` actions (setting `chronos.presence.count_ui_actions`); `PresenceController` exposes `GET /api/webui/presence`, `GET /api/webui/presence/history`, `POST`/`DELETE /api/webui/presence/dnd`. Frontend: presence badge in the shell sidebar (polled every 60 s and on tab focus) with a popover: state and its plain explanation, last interaction, activities, tab «Cosa cambia» (effects in plain words), tab «Storico» (last 15 state changes with the reason), Non disturbare on/off with what it does, link to Impostazioni. The popover is `position: fixed` (computed from the badge) because the sidebar clips its overflow; Esc or a window resize closes it.
