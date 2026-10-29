# Hestia-Themis ⚖️

**Role:** Central settings — the one place where Hestia's settings live
**Node:** Raspberry Pi (always-on, like Hub and Archive)
**Stack:** Python · FastAPI · Docker
**Port:** 19016

---

## Responsibility

- **Modules declare** their settings with `hestia_common.settings_client` (type, default, options, ranges,
  live/restart, who may change them). Themis keeps the declared schema (memory + `data/schema_cache.json`).
- **Every client** (WebUI, Telegram, future ones) reads and changes settings here, all through Hub.
- **Archive stores** the values (`/api/settings-store/*`: values, last 10 changes per key, proposals).
- **The assistant never changes a setting by itself**: Oracle (when asked in chat) and Athena (in autonomy)
  only *propose*; the proposal reaches the user through **Hermes** with Approva / Rifiuta; the first
  answer from any client wins.
- **State for every client**: each setting reports `ok`, `restart_required` (stored ≠ value the module
  uses) or `offline`; a global `revision` tells clients when to refetch.

Not settings (stay in env): secrets (tokens, API keys, passwords) and infrastructure (URLs, ports, paths).

## Concepts

| | |
|---|---|
| Definition | declared by the owning module: `key` (`<module>.<group>.<name>`), label, help, `type` (enum, bool, int, float, string, text, model, time, duration, list, object), default, options/min/max/unit, `apply` (live/restart), `scope` (system/user), `depends_on`, `oracle` (propose/read/none), `advanced` |
| System value | one value for Hestia (`scope=system`), pushed to the module on change (`POST /api/settings/reload`) |
| User value | layered: **profile** (your defaults) → **client** (webui/telegram) → **session**; a new session copies profile+client (`/api/settings/sessions/{id}/init`) |
| Preset | named bundle of values for one group (e.g. Economico / Qualità); editing any value → group shows `custom` |
| Proposal | assistant suggestion, pending until the user approves/rejects; expires after 24 h (closed lazily, no timers) |

Personal settings (owner Themis, group «Personali»): `themis.personal.week_start`, `themis.personal.currency`,
`themis.personal.places` (list of `{id, name, address, kind home|work|other, lat?, lon?}`, editor «Luoghi», one
Casa; options resolved by Hecate). `options_source` may name another module: `"<module>:/path"` is fetched through
Hub from that module (e.g. `hecate:/api/gateway/weather/places`).

## Flows

- **Module start**: `SettingsClient.start()` → `POST /api/settings/register` (definitions, presets, effective)
  → stored values back → applied; re-asserted hourly (restores the schema after a Themis restart).
  Themis or Archive down → defaults, `[🔄]` log, retry every 60 s.
- **User change**: `PUT /api/settings/key/{key}` → validated → Archive (history) → owner reloads → live values
  apply at once, restart values flagged `restart_required` until the module restarts.
- **Personal settings** (`themis.personal.week_start`, `themis.personal.currency`, group «Personali»): owned by
  Themis (`hestia_common.settings_client.PERSONAL`), shared by every module. A module reads them with
  `SettingsClient.follow_personal()` (register sends `follows`, the answer carries `shared`); a change reloads every
  follower. Modules never declare their own copy. `GET /api/settings/effective` answers Themis' own values.
- **Assistant proposal**: MCP tool `settings_propose` (or Athena `POST /api/settings/proposals`) → Archive
  (pending) → Hermes event `service.action_required` with payload `kind=settings.proposal`, `_message`,
  `_actions` (`{id, label, style, service: themis, method: POST, path: /api/settings/proposals/{id}/approve|reject,
  body: {by: "<client>"}}`), dedupe key `settings.proposal:<id>` → user answers from any client
  (contract shared with `docs/work/2026-10-10-hermes-global-notifications/`) → applied (history actor = proposer) → `settings.changed` notice.
  Later answers get `409 {status: already_decided}`. Closing (approved/rejected/expired) emits
  `settings.proposal_closed` with `closes: settings.proposal:<id>`, `decision`, `outcome_text`.
- **Proposal born in a chat** (client plugins, 2026-10-18): Oracle's tool call carries `X-Session-Id` +
  `X-Hestia-Client` → origin → the answer has `confirm {question_id: "themis:<id>", header, prompt, options,
  actions}` and Oracle shows it as a confirm card in that chat (answer = approve/reject action routed via Hub with
  `by: <client>`); the Hermes copy carries `_origin` + `_quiet` (inbox only, no push). A user-scope setting owned by
  a client (`webui.*`, `telegram.*`) is proposed on that client's layer (`scope=client`, `scope_id=<client>`).
- **Proposal from an external AI** (2026-10-18, Hestia-MCP door): `X-Hestia-Access: <name>` → proposer
  `external:<name>`, shown as "<name> (AI esterna) propone…", confirmed via Hermes (never a chat card). Tools open to
  external AIs: `settings_search`, `settings_get`, `settings_propose`.

## API (via Hub `/route/themis/...`)

| Method | Path | |
|---|---|---|
| POST | `/api/settings/register` | module declares settings, gets stored values |
| GET | `/api/settings/revision` | change marker |
| GET | `/api/settings/modules` | modules with settings + health/version (Hub) + pending proposals |
| GET | `/api/settings` | `module, q, client, session, status` → items with value, source, status + preset state |
| GET | `/api/settings/search` | compact search (assistant) |
| GET/PUT/DELETE | `/api/settings/key/{key}` | read / change / reset |
| GET | `/api/settings/key/{key}/options` | choices: static `options`, or the owner's `options_source` with `{other.key}` filled from current values (e.g. installed Ollama models) |
| GET | `/api/settings/key/{key}/history` | last changes |
| GET | `/api/settings/history` | every change, all keys, newest first, paged (`limit` ≤200, `offset`, `module`, `actor` comma list — `external` matches every `external:<name>`, `key`, `sessions`) → `{items, total, next_offset, keep_per_key}`; each row adds `label`, `module`, `kind` (change/undo/reset/approved/preset) and `undoable` (latest change of its key/scope). Session copies hidden by default — plugin page *Registro* |
| POST | `/api/settings/key/{key}/undo` | user undo |
| POST | `/api/settings/key/{key}/undo-propose` | assistant undo (a proposal) |
| POST | `/api/settings/presets/{module}/{preset}/apply` | apply a preset |
| POST | `/api/settings/sessions/{session}/init` | new session from profile defaults |
| GET/POST | `/api/settings/proposals` | list (`status` pending default · approved · rejected · expired · `all`; with the setting `label`) / propose |
| POST | `/api/settings/proposals/{id}/approve` · `/reject` | user's answer |

MCP tools (Hestia-MCP, domains `system`, `settings`): `settings_search`, `settings_get`, `settings_propose`,
`settings_undo`. There is deliberately **no** approve tool: only the user answers.

## Export and import of settings (`/api/transfer/*`, dossier `docs/work/2026-10-20-import-export`)

Themis owns the values, so it exports every module's settings (`app/core/transfer.py`): one section per module with
settings (id = module name; `themis` = personal settings), records `<key>|<scope>|<scope_id>`. Layers system,
profile and client travel; session copies never. On import each value is validated against this Hestia's schema
(unknown key or bad value → reported problem, skipped) and written with history actor `import`; «Sostituisci»
resets the ticked keys that are only here. Hub capability `transfer.settings: true`.

## Configuration (infrastructure only)

| Env | Default | |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub |
| `SERVICE_BASE_URL` | `http://hestia_themis:19016` | advertised URL |
| `THEMIS_DATA_DIR` | `/code/data` | schema cache |
| `THEMIS_UI_DIST` | `/ui/dist` | WebUI plugin bundle (set by the Dockerfile, outside the `app/` dev mount) |

## WebUI plugin — inside view (2026-10-18, dossier `docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2)

Core module (`kind: "core"`, WebUI *Sistema* section, order 160), `api_prefix` `/api/settings/` (Themis' own
routes). No widget.
- page **Registro** (`themis-log`): every setting change — who (Tu / Tu via WebUI or Telegram, Oracle, Athena, a
  client, an external AI `external:<name>`), when, old → new, kind (annullata, predefinito, proposta approvata,
  preset), scope — filters by who and module, paged; **Annulla** on the latest change of a key = the existing
  `POST /api/settings/key/{key}/undo` (same as *Annulla ultima* in Impostazioni; the undo is logged too).
  Proposals: pending ones on top (**Approva / Rifiuta** = the existing user answer, `by: webui`), the decided ones
  in the *Proposte* tab (proposer, decision, who decided). Nothing applies an assistant proposal without the user.
- Themis down → «Themis non raggiungibile».

Bundle `ui/` → Dockerfile Node stage → `/ui/dist/webui/themis.js`; manifest keys merged into the Hub
registration at every (keepalive) register.

Design dossier: `docs/work/2026-10-10-central-settings/`.

## Telegram menus
Tool titles are plain Italian without emoji; each tool says where it goes on Telegram with `telegram_group` (area) and `telegram={section, primary, summary, label}` (docs/work/2026-10-23-telegram-da-zero §5.7, checked by `tools/governance/check_telegram.py`). Here: sistema › Impostazioni: 4 (area › section: tools).

## Module guide for the assistant (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, Cindy 30)
The Hub registration declares `capabilities.when_to_use` (one line in the assistant's «MODULI» index) and
`capabilities.manual` (short manual the assistant loads with `module_manual` only when it needs it).

## Proposals on Telegram (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, wave 3, parity F)
Tool `settings_proposals(status?)` → `GET /api/settings/proposals` (pending by default): the owner sees on Telegram
what the assistant proposed and confirms from the notification as usual.
