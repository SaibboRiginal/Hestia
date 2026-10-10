# SPEC — Central settings registry, control panel, Oracle/Athena access

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User request · channel: external chat (Claude Code cloud session, project thread) · 2026-10-10 |
| **Status** | Draft — waiting for user approval; no code yet |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): put **all** settings of every module in one central
place, env variables included; a control panel to change them by hand; the same settings reachable via
API/MCP so Oracle can read and change them. Centralized means **any client** (WebUI, Telegram, a future
client) can show and change them — Telegram editing is designed in another thread. Must be user friendly,
easy and organized, same WebUI style, reuse what exists, with a search. The panel can double as a small
dashboard of module state. Restart-only settings are fine as long as a **state** is always visible to all
clients. Secrets and infrastructure stay in `.env`. Existing settings move here too; chat defaults saved
once and copied into each new session (like Claude/Codex). Settings usable from other points of a client
(e.g. chat options in the chat page). Light history with undo, mostly so the model can undo its own changes.
Oracle knows itself **on demand** (tools), not via permanent context. Oracle may change settings **only
with the user's confirmation**; Athena may **propose** a change to the user. Dropped: JSON export/import,
"test" buttons.

---

## 1. Goal

One registry that every module declares its settings into, one store (Archive), one API (via Hub) used by
every client and by Oracle. The WebUI gets a searchable control panel with module status.

## 2. Scope

### In
- Settings schema declared by each module (`hestia_common`), published at startup.
- Store + API in Archive: values, scopes, light history, pending proposals, global revision.
- Standard per-service endpoints (from `hestia_common`): effective values + reload.
- WebUI: new "Impostazioni" layout (personal + system per module), search, module status cards,
  inline settings reused in other pages (chat quick menu).
- Unified chat settings (Telegram + WebUI share one schema) with profile defaults → session copy.
- Oracle MCP tools: search / get / propose (never direct write); confirmation by the user.
- Athena candidate kind `setting` → proposal → user notified (owner) → approve/reject.
- Migration of existing runtime islands and, module by module, of the tunable env variables.

### Out
- **Secrets** (tokens, API keys, OAuth, DB password): stay in `.env`; panel shows only "configurato sì/no".
- **Infrastructure/bootstrap** (ports, `HUB_API_URL`, DB URLs, paths, `SERVICE_NAME`…): stay env.
- Telegram UI for editing (other thread; the API here must be enough for it).
- JSON export/import, "test" buttons. Editing the `.env` file itself (rule: never touch `.env`).

## 3. Design

### 3.1 Setting definition (declared by the owning module)
```
key          "oracle.models.generic"  (module.group.name, stable)
module       "oracle"
group        "Modelli"                 (UI section)
label, help  Italian, user friendly; help = what it does in plain words
type         enum | bool | int | float | string | text | model | time | duration | list
options      for enum (value + label), min/max for numbers
default      code default
env          "MODEL_USECASE_GENERIC_MODEL" (optional legacy env name)
scope        system | profile | client | session
apply        live | restart
depends_on   {"key": "argus.remediate.enabled", "equals": true}   (else shown grey/collapsed)
oracle       read | propose | none     (what Oracle may do; default read)
advanced     bool (hidden behind "Mostra avanzate")
```
Declared in code next to the module's other knobs (like Telegram `chat_settings.py` today), registered
with the same startup helper that registers MCP tools / agenda rules.

### 3.2 Value resolution
`code default → env (.env/compose) → stored override`. The panel shows the source of the current value
("predefinito", "da .env", "modificato"). "Ripristina" removes the override (falls back to env/default).
Scopes for user-facing options: `profile` (your defaults) → `client` (webui/telegram) → `session`.
New session = copy of profile (+client) values; changes in a session stay in that session unless
"Salva come predefinito". Pure device rendering (theme, diff mode, calendar view) stays local in the browser.

### 3.3 State visible to every client
- Each service exposes `GET /api/settings/effective` (values it is really using) and
  `POST /api/settings/reload` (re-read; `live` settings apply immediately).
- Archive keeps a global **revision** (+1 on every change). Clients read `GET /api/settings/revision`
  (cheap) and refetch when it changes; WebUI can push via SignalR.
- Per setting status: `ok` · `riavvio necessario` (stored ≠ effective, `apply=restart`) ·
  `modulo offline` · `proposta in attesa`.
- On change Archive (via Hub) calls the owner's `/api/settings/reload`; no polling loops in services.

### 3.4 Storage (Archive, only DB owner)
- `settings_values` (key, scope, scope_id, value json, updated_by, updated_at)
- `settings_history` — last **10** changes per key (old, new, actor user/oracle/athena/client, when). Light.
- `settings_proposals` (key, value, reason, proposer oracle|athena, status pending/approved/rejected/expired,
  ttl) — approve applies it, reject logs it.
- `settings_schema` cache of the declared definitions (so the panel works when a module is offline).

### 3.5 API (Archive, reached through Hub; swagger updated)
`GET /api/settings/schema?module=&q=` · `GET /api/settings?scope=&module=` · `PUT /api/settings/{key}` ·
`DELETE /api/settings/{key}` (reset) · `GET /api/settings/{key}/history` · `POST /api/settings/{key}/undo` ·
`GET|POST /api/settings/proposals` · `POST /api/settings/proposals/{id}/approve|reject` ·
`GET /api/settings/revision`. Search covers label, help, key, env name, module.

### 3.6 Oracle and Athena
- MCP tools (on demand, nothing in the permanent prompt): `settings_search`, `settings_get`,
  `settings_propose`, `settings_undo` (undo = a proposal too).
- `settings_propose` creates a proposal and asks the user in the chat with the existing high-impact approval
  flow (`/api/actions/approval/respond`); outside a chat the owner is notified (`owner` target) with
  approve/reject. Only keys with `oracle=propose`.
- Athena: new candidate kind `setting` → `settings_propose` with reason → owner notified. Deduplicated,
  max per day like the Forge hand-off.

### 3.7 WebUI (same style, reuse `hx-page-header`, `hx-field`, `hx-segmented`, `hx-toggle`, `hx-textarea`)
- **Impostazioni** = two areas: *Personali* (aspect, assistant/chat defaults, notices, session) and
  *Sistema* (modules). Left list of modules with status dot; top search (also `Ctrl+K`); filter
  "Solo modificate"; "Mostra avanzate".
- Module header card = mini dashboard: online/offline, version, last activity, what it is doing (Forge
  tasks, running agenda jobs, Argus state), "riavvio necessario" badge. Data: Hub `/api/registry/services`,
  `/api/status`, Argus `/api/argus/status`, Chronos/Forge existing endpoints.
- Form generated from the schema by one `hx-setting` component (renders a definition by type), reused
  anywhere: chat page quick menu (tone, reasoning), calendar Vista, Sviluppo (Forge engine).
- Pending proposals banner with approve/reject; per-setting history popover with undo.

### 3.8 First settings to migrate
1. Oracle models per use case + **preset** (`economico` = local, `qualita` = cloud, `personalizzato`).
2. Forge default engine (replaces Hephaestus `settings.json`), auto-merge, auto-rollback, max turns.
3. Chat settings: one schema for Telegram + WebUI (tone, reasoning, streaming, notices, custom prompt).
4. `LOG_LEVEL` for every module.
Then module by module: Argus thresholds/remediation, Athena windows/thresholds, Chronos sync/tz, Scout
polling/filters, Telegram locale/style, Oracle agent limits/timeouts/timezone. Estimated 120–150 of ~225
env vars are tunable; the rest are secrets/infrastructure.

## 4. Acceptance criteria
- A module declaring a new setting makes it appear in the panel with no WebUI change.
- Change a `live` setting in the WebUI → module uses it without restart; Telegram/other clients see the
  new revision.
- Change a `restart` setting → "riavvio necessario" everywhere until the module restarts with it.
- Search finds a setting by Italian label, key or old env name.
- Oracle can explain any setting via tools and can only change one after the user's confirmation;
  undo restores the previous value.
- Athena proposal reaches the user and is applied only on approval.
- New chat session starts from profile defaults; changing it does not change the defaults.
- Secrets never appear in API responses (only configured yes/no). No personal data in tracked files.

## 5. Open points (to confirm at approval)
- Store/API location: **Archive** (proposed: it owns the DB and already hosts memory/subscriptions APIs)
  vs a new small core service.
- Exact list of `oracle=propose` keys (proposal: models/preset, chat defaults, notice options, Athena/Argus
  thresholds; never Forge auto-merge or approval gates).
