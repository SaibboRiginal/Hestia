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
| POST | `/api/webui/auth/telegram` | Mini App login: `{initData}` (Telegram's signed launch data) → Telegram verifies it via Hub (`/api/webapp/verify`, owner only, ≤ 24 h) → `{status, token, expiresInSeconds}` (12-hour session token next to the main token; no token needed to call it) |
| GET | `/api/webui/auth/status` | Token status |
| GET | `/api/webui/auth/access` | `{local, tokenRequired}` — asked by the browser at start, no token needed |
| GET | `/api/webui/plugins/catalog` | Client plugins (Hub catalog `client=webui`), 15 s cache |
| GET | `/api/webui/plugins/{module}/bundle/{file}` | Module WebUI bundle file (via Hub) |
| ANY | `/api/webui/plugins/{module}/call/{path}` | Plugin → its own module; 403 outside its `api_prefix` (the prefix without its last `/` is allowed) |
| GET | `/api/ai/widgets?q=` · `/api/ai/dashboards` | Assistant tools `webui_widgets` / `webui_dashboards` (internal, via Hub) |
| POST | `/api/ai/mcp` | Same tools as MCP JSON-RPC (`capabilities.mcp_endpoint`, domains system/settings); was `/mcp` before 2026-10-18 |
| POST | `/mcp` | **Public MCP door for external AIs** (`McpDoorController`): body + `Authorization: Bearer` → Hub → Hestia-MCP `/mcp/external` (token, scope, rate limit there); no WebUI login, always a token, also at home. GET/DELETE → 405 |
| GET | `/.well-known/oauth-protected-resource[/mcp]` · `/.well-known/oauth-authorization-server` | OAuth metadata (`OAuthDoorController` → Hub → Hestia-MCP, with `X-Hestia-Public-Base`) |
| POST | `/oauth/register` · `/oauth/token` · `/oauth/revoke` | OAuth 2.1 for claude.ai / ChatGPT connectors (form or JSON body + `Authorization` forwarded) |
| GET | `/oauth/authorize` | Parks the request on Hestia-MCP → 302 to `/p/mcp/accessi?oauth=<id>` (consent card, behind login); refused client/redirect → plain error page; other errors → 302 to the client's registered redirect |
| GET | `/api/webui/plugins/{module}/image?path=` | Module image as bytes |
| GET | `/api/webui/transfer/modules` | Modules with the `transfer` capability (Hub registry) — «Esporta e importa» |
| GET · POST | `/api/webui/transfer/{module}/describe` · `/{module}/items|export|import|files` · GET `/{module}/files/{id}` | Forwarded to the module's `/api/transfer/*` (only modules advertising `transfer`) |
| GET · POST · GET · DELETE | `/api/webui/transfer/restore-points[/{id}]` | Restore points: WebUI Archive blobs (gzip JSON, meta `kind: transfer-restore`), newest `webui.transfer.restore_points` kept |
| GET/POST | `/api/settings/effective` · `/api/settings/reload` | WebUI's own Themis settings (internal network only) |
| GET | `/api/webui/sessions/current` | Current session ID |
| POST | `/api/webui/sessions/clear` | Reset session |
| GET | `/api/webui/settings` | Get session settings |
| PUT | `/api/webui/settings` | Update settings |
| GET | `/api/webui/central-settings/{modules,items,revision,proposals}` | Impostazioni → Sistema: proxy to Themis (`items?module=&q=`). Below a module's settings the WebUI mounts that module's plugin `settings_panel` elements (catalog type `settings_panel`; e.g. Archivio → «Backup»), hidden while searching |
| GET | `/api/webui/central-settings/key/{key}/{options,history}` | choices for a setting · last changes |
| PUT/DELETE | `/api/webui/central-settings/key/{key}` | change (`{value}`) / reset to default — actor `webui` |
| POST | `/api/webui/central-settings/key/{key}/undo` · `presets/{module}/{id}/apply` | undo · apply a preset |
| POST | `/api/webui/central-settings/proposals/{id}/{approve,reject}` | answer an assistant proposal (`by: webui`, first answer wins) |
| POST | `/api/webui/feedback` | Submit feedback (`interactionId` = the turn's `trace_id` from Oracle's `final` frame, training dataset) |
| GET | `/api/webui/chat/pending` | After a reload: open questions of the assistant + messages still queued in the current chat `{session_id, questions, queued}` (oracle-offline v3 G) |
| GET | `/api/webui/chat/context` | Context gauge of the current conversation → Oracle `/api/chat/context` (provider in use, window %, this conversation's tokens) |
| POST | `/api/webui/chat/compact` | Compact the current conversation → Oracle `/api/chat/compact` |
| POST | `/api/webui/chat/document` | Upload file (multipart) → base64 JSON via Hub → Oracle `/api/chat/document/json`, NDJSON streamed back (📎 in the chat bar) |
| POST | `/api/webui/voice/transcribe` · `speak` | Voice → Echo (`VoiceController`): voice message of the chat (use `webui.vocale`, recording kept with the message `web:<session>:<msg>`) · «Ascolta» under a reply (`webui.ascolta`, mp3, kept with the reply) |
| POST | `/api/webui/voice/listen` · `say` · `{listen\|say}/{sid}/{chunk\|text\|end}` | Live mode **Parla**: mic stream (partials) and answer spoken sentence by sentence (`webui.live.*`) |
| GET | `/api/webui/voice/live` · `audio-for?ref_id=` · `audio/{id}` | Live settings (`silence_ms`) · kept audio of a message · one kept audio |
| GET | `/api/webui/agenda/feed.ics` · `feed-info` | Read-only ICS feed (→ Chronos `/api/agenda/ics`); auth = token **or** `?key=` = `WEBUI_ICS_KEY` (that path only). The rest of the agenda API moved with the page into Chronos's plugin (2026-10-19) |
| GET | `/api/webui/notifications?filter&source&before&limit` · `counts` | Inbox (→ Hermes `/api/notifications`, `client=webui`); the Notifiche page itself is Hermes' plugin |
| POST | `/api/webui/notifications/{id}/seen` · `seen-all` · `{id}/answer` | Global read state; answer (`{actionId}`, 409 = already handled elsewhere) |
| POST | `/api/notify` | Hermes notification client (`capabilities.notify_endpoint`), **internal network only** (not proxied, private IP): pushes `ReceiveNotification` on SignalR to every open browser; `retract` ignored (the inbox keeps everything); repeat chains: `update superseded` removes the old item from the Notifiche page, `repeat.text` shown as a badge on cards and in the toast |
| GET | `/health` | Health check |
| POST | `/api/webui/admin/generate-token` · `revoke-token` · GET `token-status` · GET/POST `public-url` | Admin (Telegram / tunnel script). **Guarded**: `X-WebUI-Admin-Secret` = `WEBUI_ADMIN_SECRET` when set, else only direct loopback/private-network calls not coming through Cloudflare/proxy |

### Client plugins, Home and dashboards (2026-10-17, `features/plugins/`, dossier `docs/work/2026-10-17-client-plugins/`)

- Modules declare WebUI contributions (pages, widgets, quick actions) with `hestia_common.plugin_client`; the Hub
  catalog lists them. `PluginCatalog` (.NET) caches it 15 s; `PluginsController` serves bundles and proxies each
  plugin's calls only under its own `api_prefix` (no other module, no Hub admin); the prefix without its trailing
  slash counts too (`/api/deadlines` for `/api/deadlines/`: a module's list and create calls on its API root).
- `PluginsService` (Angular): polls the catalog (60 s, on focus, on `online`), fetches each bundle with the token and
  imports it as a blob module; the bundle imports the shared SDK (`/plugins/_sdk/sdk.js`, built from
  `Hestia-Shared/webui-sdk` in the Dockerfile) through the import map in `index.html`. Elements get `host` + `ctx`.
- **Home** (`/home`, first module) = quick-action strip + dashboard grid; until edited it is composed from widgets
  marked `auto` of the domain modules. A ready-made *Sistema* dashboard (`/d/sistema`) takes the core modules' `auto`
  widgets (hidden while there is none; deleting it leaves a `removed` marker in `webui.dashboards`). Other dashboards at `/d/:id` (tabs + sidebar "Dashboard"). Edit mode: add, drag, size, configure,
  remove; Oracle-created dashboards carry `created_by: oracle`.
- Module pages at `/p/<module>/<page>` (sidebar "Moduli", core modules under "Sistema"; detail pages hidden).
  Sidebar: one scroll area between a fixed top and bottom, collapsible sections, entries pinned to "Fissati" leave
  their section; plugin pages may show a `badge` counter (DESIGN-SYSTEM §9). Ctrl/⌘+K palette: «Adesso», quick actions,
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
- Icon set (`ui/icon.component.ts`, mirrored by the SDK `hxk-icon`): 2026-10-20 added `bookmark` (Oracle page **Memoria**: what Hestia remembers, from chat or an external AI via `memory_note`); 2026-10-19 added `wallet`, `upload`, `target`,
  `mail`. New plugins that use them: **Spese** (module `plutus`, decade 60: Panoramica, Movimenti, Budget,
  Abbonamenti, Importa, Statistiche, Categorie e regole; widgets *Spese del mese* / *Ultimi movimenti*; quick action
  *Spesa veloce*) and Iris' core page **Email** (subscriptions, deliveries, «Controlla email»). No WebUI code: both
  come from the Hub plugin catalog.

### Adesso, Scopri, aspetto, Web Push (2026-10-29, dossier `docs/work/2026-10-24-tutto-brainstorm-cindy` W7)

- **Taps** (`services/metis.service.ts`): every page opened (`/p/<module>/<page>` → `<module>.<page>`, WebUI pages
  → `webui.<path>`) and every quick action or suggested tool run is a tap, sent in batches (20 s, 40 max, on tab
  hide) to `POST /api/metis/usage` `{taps:[{client: webui, kind: page|action|tool, ref, label, at}]}` through the
  Metis plugin door. Offline taps wait for the next one.
- **Adesso** (`features/plugins/adesso-row.component.ts`): Home row above the quick strip, from
  `GET /api/metis/adesso?client=webui` (up to 6, each with its reason); a tap opens the tool on the *Comandi* page
  (`/p/mcp/comandi?command=…&args=…&run=1`: run at once when nothing required is missing). Hidden when empty. The
  Ctrl/⌘+K palette lists the same items first, in the group *Adesso*.
- **Scopri** (`/scopri`, `features/scopri/`; like «Sistema», its header leaves 56 px for the phone menu button): features never or rarely used (`GET /api/metis/scopri?limit=50`),
  grouped by module, search, *Prova* opens the tool like *Adesso*.
- **Aspetto** (`services/appearance.service.ts`, `layout/appearance-layer.component.ts`): `GET /api/appearance/now`
  through the Aphrodite plugin door at start, when the catalog shows the module and when the tab comes back after
  30 min. The profile accents (`accent`, `accent2`) go over the user's own theme (`ThemeService.setPalette`:
  `--accent`, `--accent-hover`, `--accent-soft`, `--accent-2`); the light effect (snow, leaves, petals, confetti,
  hearts, stars, pumpkins, sun) is a fixed layer with no pointer events, off with *riduci movimento*; the pet sits
  in the corner (pose `idle`, `sleep` 23–7, `happy` on tap; pictures via `host.image`). No Aphrodite = standard look.
  Impostazioni → Personali → Aspetto shows the profile of now and links to the *Aspetto* page.
- **Web Push** (`services/push.service.ts`, `public/sw.js`): Impostazioni → Personali → Messaggi → *Notifiche su
  questo dispositivo*: VAPID key from `GET /api/ui/push/key` (Hermes door; no key = «Non ancora attive sul
  server»), `pushManager.subscribe`, `POST /api/ui/push/subscribe {subscription, device}` (device = browser + OS
  only); off = `DELETE` + unsubscribe. The worker shows `{title, body}` (tag per notification, pending ones stay
  until touched) and a tap opens the notification's `link` page (or *Notifiche*), focusing an open tab.

### Sidebar, conversations, chat parts, live everywhere (2026-10-29, same dossier W7 part 3b)

- **Sidebar** (`layout/shell.component.ts`): SVG logo; under «Crea con Hestia» a visible **Cerca** (opens the Ctrl+K
  palette through the window event `hestia:palette`) and **Parla**; sections *Generale* (now above) · *Fissati* ·
  *Conversazioni* (pinned conversations, else the 3 latest; *Tutte le conversazioni* opens the history) ·
  *Dashboard* · *Moduli*; the system modules' pages are behind one **Sistema** entry at the bottom (sum of their
  counters) → page `/sistema` (`features/system/`, modules with their pages, pin to *Fissati*, link to the *Sistema*
  dashboard). A pinned system page still shows in *Fissati*. Compact mode = the collapsed sidebar (icons only).
- **History** (`features/chat/chat-history.component.ts`, `services/chats.service.ts`): second sidebar, every
  conversation (pinned first), search in titles and messages, from/to dates, tag filter, *Carica altre*; per
  conversation pin, title, coloured tags (9 fixed hues) and, in the same panel, «Non usare per l'allenamento»
  (`training_off`: its turns never enter the training dataset and the saved ones are dropped). Opening one loads its messages (`/api/ui/chats/{id}/messages`,
  markdown answers rendered) and sets it as the session the next message goes to. Through the Oracle plugin door.
- **Answer parts** (`features/chat/answer-blocks.component.ts`): ```` ```hestia-ui ```` blocks (also when the answer
  arrived as HTML `<pre><code class=language-hestia-ui>`) become card, stat, table, list, checklist, chart (SVG bars or
  line) and button (sends its text as your message); tone = role colours of the theme.
- **Ho fatto** (Oracle `changes` frame, Cindy 13; .NET `OracleEvent.items`): the writes of the answer with
  «Annulla» = the inverse tool through Hestia-MCP `POST /api/mcp/ui/tools/call`; undone rows are struck through.
- **Origin** (Cindy 6; `final.origin`, .NET `OracleEvent.origin`): a small label above an answer started by a
  routine, a module or an external AI.
- **Parla everywhere** (`layout/live-overlay.component.ts`): from the sidebar, the Home header or Ctrl+Shift+Space;
  live goes on when you leave the chat, a pill at the bottom shows its state with the pet as face (happy while
  talking), *Interrompi*, *Apri la chat*, close. The Chat page keeps its own panel.
  A question of the assistant is read with its options («Puoi dire: A, B o C», `spokenOptions`); the spoken answer is
  the next message, which closes the question in Oracle (dossier `docs/work/2026-10-30-domande-nelle-notifiche`). A Hermes notification with
  `question` counts as pending in the shell toast («Rispondi»); the card is in the Hermes *Notifiche* page.
- **Detta** (chat composer): speak, the text lands in the box to read again; use case `webui.dettatura` (declared by
  `VoiceController`), nothing is kept.

### Voce (2026-10-20, dossier `docs/work/2026-10-20-modulo-voce`)

- Chat composer: with an empty field the send button is a **microphone**. Touch: hold to record, release to send,
  slide left to cancel. Mouse: click to record, then bin or send. The voice message appears at once as an audio
  bubble (play, duration) with «Trascrivo…», then its transcript; the text goes to Hestia like a typed message
  (`ChatService.sendVoice`, `services/voice.service.ts`).
- **Ascolta** (volume icon) under every reply: Echo reads it (kept, a second play is not generated again).
- **Parla** (header, waveform icon, `services/live-voice.service.ts`): live conversation by voice with the same chat.
  The browser measures the mic level: speech start opens Echo's `listen` stream (chunks every 800 ms, partial text
  shown), a pause of `echo.live.silence_ms` (1250 ms; with a voiceprint, other voices are muted by Echo first, so the
  TV does not keep the turn open) ends the turn; the answer, while it is written, goes to Echo's `say` stream
  and the sentences play in order; speaking again (or «Interrompi») stops the voice and the answer. No external live
  service. The panel shows Ti ascolto / Ti sento / Ci penso / Sto parlando.
- Hub registration declares `voice_usecases` (`webui.vocale`, `webui.ascolta`, `webui.live.ascolto`, `webui.live.voce`).
- Icons `frown`, `meh`, `laugh` (with `smile`: the five mood faces of «Umore», 2026-10-30) in the shared icon set
  (`hx-icon` and the SDK's `hxk-icon`); the chat notice `mood.saved` «Umore segnato» needs no client change.
- Icons `mic`, `mic-off`, `volume`, `waveform` in the shared icon set (`hx-icon` and the SDK's `hxk-icon`).

### Notifiche (2026-10-10; since 2026-10-19 Hermes' plugin page `/p/hermes/notifiche`, `services/notifications.service.ts`)

The page moved into Hermes (plugin, badge from its own counts); `/notifications` redirects there keeping the query.
The WebUI keeps `NotificationsService`: SignalR pushes, toasts (mode shared with the page through localStorage + the
`hestia:notification-prefs` event), seen-on-push while the plugin page is open. As before: Hermes inbox shared by
every client (Archive through Hermes); filters
*Da leggere · Da rispondere · Tutte*, module filter, toggle *Anche da altri client* (notifications that answer
a request made on another client, hidden by default); grouped by day; action buttons or outcome
("Approva · da Telegram · 10:42"). Live: SignalR `ReceiveNotification` (`notification` / `update`), refresh on
reconnect. Seen = shown on the page in a visible tab, or a toast in a focused tab (global: also seen on Telegram).
Toasts (*tutte / solo importanti / nessuno*) are a per-browser preference in the page's menu.

### Frontend structure (rewritten 2026-10-03)

Claude-like design system with themes (`src/app/core/theme`), UI kit (`src/app/ui`), shell with module registry
(`src/app/app.modules.ts`) and lazy feature pages: **Chat**, **Agenda di Hestia** (since 2026-10-19 Chronos's plugin page
`/p/chronos/agenda`, `/calendar` redirects; `Hestia-Chronos/ui/src/agenda.ts` + `ui/src/cal/`; calendar: month/week/day/list — list has an *Adesso* divider and the outcome of past items —
sidebar mini-calendar + layers + module/type filters, popover details, editor with recurrence builder, drag & drop
move/resize, skip/restore, pause, run now, cancel, "only this occurrence" vs "whole series"), **Comandi & MCP**
(tools from Hestia-MCP `tools/list` as client `webui`, run with `tools/call` — `HubClient.McpListToolsAsync` /
`McpCallToolAsync`; arguments come from each tool's JSON schema),
**Sviluppo** (Forge tasks + repository, see below), **Documenti**, **Impostazioni** (themes, tone, reasoning display, instructions, session).
Look (2026-10-29): 14 colour themes (Claude, Ardesia, Oceano, Foresta, Lavanda, Cipria, Sabbia and their dark twins,
Mezzanotte) × 3 styles (Classico, Vetro, Netto) with knobs for corners, borders, transparency/blur and animations,
per browser (`core/theme/looks.ts`); thin themed scrollbars; sidebar shows one status line (assistant state; the
connection only when it is not «Connesso»).
Rules for new UI: **`frontend/DESIGN-SYSTEM.md`**.

### Sviluppo page (2026-10-04; since 2026-10-19 Hephaestus' plugin page `/p/hephaestus/sviluppo`)

Moved into Hephaestus (`Hestia-Hephaestus/ui/src/sviluppo.ts` + `ui/src/forge/`, adds *Copia per AI*); `/forge`
redirects keeping `?task=` / `?view=`. Same behaviour as described here. Comandi & MCP (`/commands` →
`/p/mcp/comandi`) and Documenti (`/documents` → `/p/oracle/documenti`) moved the same way; their old WebUI
controllers are gone (chat upload stays in `ChatController`).
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
  the list refreshes every 15 s. Deep link `/forge?task=<id>` (Agenda Forge items: **Apri in Sviluppo** → `/p/hephaestus/sviluppo?task=`),
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
  Personalizzato* (custom = values match no preset). Settings that declare `row` + `column` render as a table.
  Filters *Solo modificate* and *Avanzate (N)*.
- Settings with `editor: places` (personal «Luoghi», `themis.personal.places`) use `<hx-places-editor>`
  (`places-editor.component.ts`): inline rows name / address / kind (Casa, Lavoro, Altro; one Casa), add/remove,
  each row shows how Hecate resolved it (options from `hecate:/api/gateway/weather/places`). Weather icons (sun,
  cloud-sun, cloud, fog, drizzle, rain, snow, storm, run) are in the shared icon set.
- `<hx-setting>` (`setting-row.component.ts`): label, help, badges *modificato · riavvio necessario · modulo
  offline · al riavvio · personale*, the control and a clock popover with the last changes, *Annulla ultima*,
  *Ripristina predefinito*. Settings whose `depends_on` is not met are greyed out with "Attiva solo con …".
- `<hx-setting-control>` (`setting-control.component.ts`) picks the input by type (toggle, segmented ≤4 short
  options else dropdown, number + unit, model name with suggestions from `options`, 24h time, text, list one per
  line, JSON). An `object` setting with an `editor` hint (`llm_providers`, `llm_chains`, `llm_usecases`: Oracle's
  providers, chains and use cases) also shows the link «Modifica in Oracle · Cervello · Modelli» to its dedicated
  editor (`/p/oracle/cervello`, tab Modelli); the JSON stays editable. Emits only complete values; Themis validates
  and its Italian error goes to a toast.
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

### Calendar view rules (2026-10-04; since 2026-10-19 in Chronos's Agenda plugin, `Hestia-Chronos/ui/src/cal/prefs.ts`)

The page asks Hestia through the plugin host (`host.assistant(...)`), logs come from Chronos
`GET /api/agenda/logs` and edits are sent with `by=user` by the plugin itself.

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
  → fields + when/repeat → review). Templates come from the modules (Chronos `GET /api/agenda/templates`);
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

## Esporta e importa (Impostazioni → Dati, dossier `docs/work/2026-10-20-import-export`)

`features/settings/transfer-settings.component.ts` (+ `transfer.api.ts`), deep link `/settings?tab=transfer`. Three
tabs: **Esporta** (tree modules → sections with counts, «Scegli» for single items, «Solo modifiche dal», «Includi
foto» → downloads `hestia-AAAA-MM-GG.hestia`, gzip JSON via `CompressionStream`), **Importa** (open/drop a file → same
tree, mode Aggiungi/Unisci/Sostituisci globally or per section, «Anteprima» = dry run with counts and item lists,
«Importa» saves a restore point first, then uploads files and imports), **Ripristino** (restore points: Ripristina =
open in Importa with Sostituisci, Elimina). Settings of each module come from Themis and show under that module.
Themis setting `webui.transfer.restore_points` (system, default 5, 1–20).

## Known Constraints

- **Hub registration**: once at startup (after Oracle discovery), then every 60 s (`PeriodicTimer` in `Program.cs`)
  like the Python services; before 2026-10-19 it registered only once, so *Mappa* showed the WebUI offline after
  3 minutes and a Hub restart forgot it (found by the cloud test bench).
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
- CSP on all responses; framing allowed only to Telegram Web/Desktop (`frame-ancestors`, Mini App) instead of
  `X-Frame-Options: DENY`
- Mini App sessions (`TokenManager.IssueMiniAppSession`): in memory, 12 h, issued only after Telegram verified the
  signed initData; revoking the main token ends them. The frontend reads `#tgWebAppData` once at start
  (`AuthService`) and logs in by itself when the server asks for a token
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
  lowercase, routing is case-insensitive); exempt: login, `auth/access`, `/api/webui/admin/*`
  (guarded by `AdminGuard`), `/health`, static files, `/hubs/chat` (auth in the hub).
- **MCP door** `POST /mcp` (2026-10-18, `McpDoorController`): outside `/api/webui/`, so neither the WebUI token
  nor local access applies; it needs `Authorization: Bearer <access token>` always (also at home) and Hestia-MCP
  checks it (401 / 403 / 429). Only the header and the JSON body are forwarded (max 1 MB). The WebUI's own module
  MCP moved to `/api/ai/mcp` to free the path. Its 401 says `WWW-Authenticate: Bearer resource_metadata="…"`.
- **OAuth door** (2026-10-19, `OAuthDoorController`): `/.well-known/oauth-*` and `/oauth/*` are public too, but never
  issue anything by themselves: a code exists only after **Consenti** on the consent card (Accessi AI, behind the
  login, which now returns to the page it came from via `returnUrl`, same-origin paths only).
  `X-Hestia-Public-Base` is sent only for a tunnel host (`IsPublicHost`) or a local one, so a forged Host cannot put
  another domain in the OAuth metadata.
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

Backend: `PresencePinger` (60 s debounce) pings Chronos on authenticated non-GET `/api/webui/*` actions (setting `chronos.presence.count_ui_actions`); chat messages travel on the SignalR socket, so they count through Oracle, which pings presence for every chat that carries `client` (the WebUI sends `client="webui"`); `PresenceController` exposes `GET /api/webui/presence`, `GET /api/webui/presence/history`, `POST`/`DELETE /api/webui/presence/dnd`. Frontend: presence badge in the shell sidebar (polled every 60 s and on tab focus) with a popover: state and its plain explanation, last interaction, activities, tab «Cosa cambia» (effects in plain words), tab «Storico» (last 15 state changes with the reason), Non disturbare on/off with what it does, link to Impostazioni. The popover is `position: fixed` (computed from the badge) because the sidebar clips its overflow; Esc or a window resize closes it.

**Oracle offline** (SPEC `docs/work/2026-10-19-oracle-offline`): `OracleStreamService` yields `oracle_unavailable`
when the Hub answers 404/502/503/504 or is unreachable before the stream starts; `ChatHub` queues the Chat-page message
in Archive (`ChatQueueService`, client `webui`, with mode/model/instructions in `meta`) and sends `queued` (bubble
«🕒 In coda»). `POST /api/chat-queue/drain` (internal network only, capability `chat_queue_drain`, called by Chronos
when Oracle is back) and startup replay the queue server-side (no browser needed; Oracle saves the history) and
push `queued_answer` to every tab, which replaces the bubble. The Chat page shows a strip «⏳ Non disponibile» while
the presence effect `chat.reply` is `queued`; the badge popover lists the overlay. The «Crea con Hestia» drawer does
not queue (it answers «riprova appena torna»).

**v3** (same SPEC): the drain sends all the queued messages of one chat to Oracle in one turn (`queued`), the
assistant decides how to answer (each, merged, or asks); `queued_answer` carries `queue_ids` and the reply goes under
the last bubble. Questions of the assistant (`question` frames with `ask_…` ids, also during a drain) are drawn by
`hx-question-card` (Chat page and «Crea con Hestia» drawer): confirm, single choice, multiple choice (toggles +
«Invia»), «Altro…», free text, «Salta». `ChatHub` answers via Oracle `question-answer` and sends `resume`, which the
page sends as the next message. After a reload the page asks `/api/webui/chat/pending` and shows again the hourglass
bubbles of queued messages and the open question. «Limitato» shows as a presence overlay (icon `battery-low`).

## Icons, not emoji

SPEC `docs/work/2026-10-20-icone-nei-client`. The WebUI and plugins draw `<hx-icon>` / `<hxk-icon>` (one shared set) with a
`tone` colour, never emoji. Presence popover: the `icon` + `tone` of the top overlay, else of the base state. Chat:
`ChatMessage.icon` (paperclip = file, zap = command) and `error` (alert icon, danger). Toasts and the Hermes inbox hide the
emoji that module texts carry for Telegram (`noEmoji`). Favicon `/icon.svg`.

## Guided setup «Benvenuto» (dossier `docs/work/2026-10-30-setup-un-click`)

`/benvenuto` (`features/setup/`) is a full-screen page outside the shell: one question per screen (brain recipe →
local model / cloud key with «Prova» / Claude token → result and downloads → voice (queues Echo's local models) →
Telegram token and one-time code →
backup passphrase → calendar, mail and devices → summary), recommended answer preselected, «Più tardi» on the
optional screens, the current screen remembered in the browser. `setupGuard` opens it once per browser session while
the setup is not completed (Hestia not answering → straight in); the Home shows a «Da finire» card for the steps left
for later. Backend: `SetupController` forwards only the screens' paths of `/api/webui/setup/*` to Hephaestus
`/api/setup/*` through the Hub (`telegram/claim` is the bot's, never forwarded); usual WebUI access rules (home
network, or token).

## Macchine page (`/macchine`, dossier `docs/work/2026-10-30-setup-un-click` §4.0)

`features/machines/` (button «Macchine» in Sistema; «Dispositivi» is the page of phones and watches): this machine
(role, video card, LAN address) and its satellites (address, online, what they do in plain words: voce, allenamento
dei modelli). «Collega una macchina» shows the 6-digit code (10 minutes) and the one-line command for Windows
(PowerShell) and Linux with `--join CODE --central <address>`; the list refreshes every 5 s while a code waits and
says when the machine joined. «Usa la sua scheda video» / «Riporta qui i modelli» move the brain's local models;
«Scollega» asks first (and brings the models back first when they were there). Backend: `SetupController`
whitelist `GET machines`, `POST machines/pair|revoke|brain` (→ Hephaestus `/api/setup/machines*`).
Card «Da fuori casa»: *Attiva* (asks first) / *Spegni* the Cloudflare quick tunnel (`GET|POST /api/webui/setup/tunnel`,
also the setup screen `fuori`). `PublicUrlService` reads the tunnel's address from `http://hestia_tunnel:20241/quicktunnel`
at most once a minute in the background (never blocking a request; a manual URL wins; the address is forgotten when
the tunnel is off), so the login links follow it; requests to that host always need the token.

## Download page (`/download`, dossier `docs/work/2026-10-30-setup-un-click` §4.3)

`features/downloads/` (button «Download» in Sistema): every download of every module with the `downloads`
capability (Oracle's models, Echo's voices), progress, speed, time left; Pausa · Riprendi · Riprova · Annulla ·
Elimina (to free space, asks first); «Scarica le voci» (→ Echo `/api/voice/models/prefetch`). Polls every 2 s while
something moves, every 10 s otherwise. Backend `DownloadsController`: `GET /api/webui/downloads` (asks each module
through the Hub; one not answering is listed as offline, never named to the user) and `POST
/api/webui/downloads/{module}/{op}` with body `{id}` (ids carry «:»).
