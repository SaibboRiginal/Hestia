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

## Flows

- **Module start**: `SettingsClient.start()` → `POST /api/settings/register` (definitions, presets, effective)
  → stored values back → applied; re-asserted hourly (restores the schema after a Themis restart).
  Themis or Archive down → defaults, `[🔄]` log, retry every 60 s.
- **User change**: `PUT /api/settings/key/{key}` → validated → Archive (history) → owner reloads → live values
  apply at once, restart values flagged `restart_required` until the module restarts.
- **Assistant proposal**: MCP tool `settings_propose` (or Athena `POST /api/settings/proposals`) → Archive
  (pending) → Hermes event `service.action_required` with payload `kind=settings.proposal`, `_message`,
  `_actions` (`{id, label, style, service: themis, method: POST, path: /api/settings/proposals/{id}/approve|reject,
  body: {by: "<client>"}}`), dedupe key `settings.proposal:<id>` → user answers from any client
  (contract shared with `docs/work/2026-10-10-hermes-global-notifications/`) → applied (history actor = proposer) → `settings.changed` notice.
  Later answers get `409 {status: already_decided}`. Closing (approved/rejected/expired) emits
  `settings.proposal_closed` with `closes: settings.proposal:<id>`, `decision`, `outcome_text`.

## API (via Hub `/route/themis/...`)

| Method | Path | |
|---|---|---|
| POST | `/api/settings/register` | module declares settings, gets stored values |
| GET | `/api/settings/revision` | change marker |
| GET | `/api/settings/modules` | modules with settings + health/version (Hub) + pending proposals |
| GET | `/api/settings` | `module, q, client, session, status` → items with value, source, status + preset state |
| GET | `/api/settings/search` | compact search (assistant) |
| GET/PUT/DELETE | `/api/settings/key/{key}` | read / change / reset |
| GET | `/api/settings/key/{key}/history` | last changes |
| POST | `/api/settings/key/{key}/undo` | user undo |
| POST | `/api/settings/key/{key}/undo-propose` | assistant undo (a proposal) |
| POST | `/api/settings/presets/{module}/{preset}/apply` | apply a preset |
| POST | `/api/settings/sessions/{session}/init` | new session from profile defaults |
| GET/POST | `/api/settings/proposals` | list / propose |
| POST | `/api/settings/proposals/{id}/approve` · `/reject` | user's answer |

MCP tools (Hestia-MCP, domains `system`, `settings`): `settings_search`, `settings_get`, `settings_propose`,
`settings_undo`. There is deliberately **no** approve tool: only the user answers.

## Configuration (infrastructure only)

| Env | Default | |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub |
| `SERVICE_BASE_URL` | `http://hestia_themis:19016` | advertised URL |
| `THEMIS_DATA_DIR` | `/code/data` | schema cache |

Design dossier: `docs/work/2026-10-10-central-settings/`.
