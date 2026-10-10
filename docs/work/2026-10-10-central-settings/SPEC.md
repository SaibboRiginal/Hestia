# SPEC — Central settings registry, control panel, Oracle/Athena access

| | |
|---|---|
| **Version** | 1.1 |
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

One registry that every module declares its settings into, owned by a **new core module Themis**
(`Hestia-Themis`: schemas, validation, scopes, proposals, revision, reload); values persisted in Archive
(3 small generic tables, Archive stays pure storage). One API (via Hub) used by every client and by Oracle. The WebUI gets a searchable control panel with module status.

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
             | object (fields) | list<object> | ref (id of an item in another list setting)
             | secret_ref (NAME of an env var; API shows only configured yes/no, never the value)
options      for enum (value + label), min/max for numbers
default      code default
env          "MODEL_USECASE_GENERIC_MODEL" (optional legacy env name)
scope        system | profile | client | session
apply        live | restart
depends_on   {"key": "argus.remediate.enabled", "equals": true}   (else shown grey/collapsed)
oracle       propose | read | none     (default propose; `none`/`read` only for safety keys:
             Forge auto-merge, high-impact approval gates, Oracle/Athena permissions themselves)
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
- Themis keeps a global **revision** (+1 on every change). Clients read `GET /api/settings/revision`
  (cheap) and refetch when it changes; WebUI can push via SignalR.
- Per setting status: `ok` · `riavvio necessario` (stored ≠ effective, `apply=restart`) ·
  `modulo offline` · `proposta in attesa`.
- On change Themis (via Hub) calls the owner's `/api/settings/reload`; no polling loops in services.
- Themis down → modules run on env/defaults (`[🔄]` fallback log) and keep their last loaded values.

### 3.4 Storage (Archive, only DB owner — Themis calls Archive through Hub, like every module)
- `settings_values` (key, scope, scope_id, value json, updated_by, updated_at)
- `settings_history` — last **10** changes per key (old, new, actor user/oracle/athena/client, when). Light.
- `settings_proposals` (key, value, reason, proposer oracle|athena, status pending/approved/rejected/expired,
  ttl) — approve applies it, reject logs it.
- `settings_schema` cache of the declared definitions (so the panel works when a module is offline).

### 3.5 API (Themis, reached through Hub; swagger updated)
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
- Athena (the retrospective: thinks about the user, improvements, reminders, settings; Argus is the
  self-diagnosis and feeds it errors): new candidate kind `setting` → `settings_propose` with reason → owner notified. Deduplicated,
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

### 3.9 LLM providers (Oracle) — shared with threads "Claude Haiku in Oracle" and "Contesto e cache di Oracle"
Three layers, so a new local tool or a new cloud vendor is "add an instance", not "add env vars":

1. **Provider types** (code, in Oracle — the only LLM client): `ollama`, `gemini`, `openai` (any
   OpenAI-compatible server: llama-server, vLLM, LM Studio, OpenRouter…), `anthropic`. Each type is a class
   that declares its typed config fields (`CONFIG_FIELDS`, same definition format as §3.1), its capabilities
   (`chat, tools, stream, vision, embed, thinking`) and `list_models()`; it receives its config as a dict and
   never reads `os.getenv` itself. `UniversalAgent` dispatches on the instance's type (no more if/elif chains).
2. **Provider instances** — setting `oracle.providers` (`list<object>`, scope system), e.g.
   ```
   [{"id":"ollama_pc","type":"ollama","label":"Ollama (PC)","enabled":true,
     "config":{"base_url":"http://host.docker.internal:11434","num_ctx":16384,"keep_alive":"30m"}},
    {"id":"llama_server","type":"openai","label":"llama-server","enabled":true,
     "config":{"base_url":"http://host.docker.internal:8080/v1","api_key_env":""}},
    {"id":"anthropic","type":"anthropic","label":"Anthropic","enabled":true,
     "config":{"api_key_env":"ANTHROPIC_API_KEY","thinking_by_mode":{"fast":"off","normal":"low","deep":"high"},
               "prompt_cache":true}},
    {"id":"gemini","type":"gemini","label":"Gemini","enabled":true,"config":{"api_key_env":"GEMINI_API_KEY"}}]
   ```
   Secrets are `secret_ref`: the instance stores the env var NAME, the key stays in `.env`.
   Several instances of the same type are allowed (two Ollama hosts, two OpenAI-compatible servers).
3. **Use-case mapping** — `oracle.usecases.<generic|reasoning|code|embedding>` (`object`):
   `{"provider":"<instance id>","model":"<from list_models()>","fallback":[{"provider":"gemini","model":"gemini-2.5-flash"}],
   "options":{ per-type overrides, e.g. "thinking":"low", "temperature":0.2 }}`. Forge's `local`/`cloud`
   profiles become two more use cases (`forge_local`, `forge_cloud`).
4. **Presets** — `oracle.preset` (`economico` | `qualita` | `personalizzato`) + `oracle.presets` (named
   bundles of use-case mappings). Picking a preset writes the mappings; editing any mapping → `personalizzato`.

UI: "Fornitori" list with Aggiungi (pick type → form from the type's `CONFIG_FIELDS`), status dot from a
cheap reachability check, model dropdown filled by `list_models()`.
Env bridge until Themis exists (and as fallback): instances synthesized from today's env
(`OLLAMA_URL`/`OLLAMA_API_URL`, `ORACLE_CONTEXT_LENGTH`, `ORACLE_OLLAMA_KEEP_ALIVE`, `GEMINI_API_KEY`,
`ANTHROPIC_API_KEY`, `ORACLE_LLM_PROFILE_*`, `ORACLE_OPENAI_BASE_URL`) and mappings from `MODEL_USECASE_*`.
One loader (`load_llm_config()` → instances + mappings) is the only place that reads env; it switches to
Themis in P2 without touching provider code.

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
- (decided v1.1) New module Themis, storage in Archive; Oracle/Athena may propose any key except safety ones.
- Themis node (Raspberry Pi always-on vs main PC) and port: proposal Pi, next free port.
