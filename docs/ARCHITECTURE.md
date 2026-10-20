# Hestia — Architecture & engineering rules 🏛️

> This is the internal reference that used to be the repository `readme.md` (moved here on 2026-10-04 so the
> README can be a public front page). It is the home of the **global rules and contracts**: when a behaviour or
> contract changes, update this file in the same change set (enforced by `tools/governance/check_docs_sync.py`).
> Entry points for AI developers: `CLAUDE.md` → `docs/AI-GUIDE.md`.

Project Hestia is a containerized, service-oriented assistant platform built with strict engineering rules:
- **Separation of Concerns (SoC)**
- **Core Genericity** (core services never contain domain logic)
- **Modular Expandability** (new capability = new service)
- **Enterprise-grade maintainability** (clear contracts, observability, graceful degradation)

Stack baseline: Python · FastAPI · PostgreSQL + pgvector · Docker · Ollama.

---

> **AI developers start from `CLAUDE.md`** (rules + mandatory work protocol) and `docs/AI-GUIDE.md` (full context).
> Hestia develops itself: ask "sviluppa …" on Telegram → Forge + Claude Code → approve → merge → restart.

## Core Topology

Always-on node (Raspberry Pi): `Hub`, `Archive`, `Oracle`, `Telegram`, `Hecate`, `Hermes`, `Chronos`, `Iris`, `MCP` (+ `WebUI` client)

Best-effort high-power node (Main PC): domain modules (e.g. `Scout`), `Metis`, Ollama, local DB replica.

Host OS shared utility (Windows/Linux): `Atlas` (runs outside Docker, registers in Hub)

Shared library: `Hestia-Shared` (common logging, startup, and lifecycle utilities consumed by all services)

---

## Quick Start

### Setup

```bash
docker network create hestia_net
```

### Suggested Startup Order

1. `Hestia-Hub`
2. `Hestia-Archive`
3. `Hestia-Hecate`
4. `Hestia-Hermes`
5. `Hestia-Oracle`
6. `Hestia-Scout`
7. `Hestia-Telegram`

### One-Command Orchestration

**Full stack (all services):**
```bash
docker compose -f docker-compose.global.yml up --build -d
```

**Raspberry Pi deployment (always-on core services):**
Set `ARCHIVE_DATABASE_URL` first (cloud DB or remote DB), then:
```bash
docker compose -f docker-compose.rpi.yml up --build -d
```

### New Service Scaffolding

Use the shared generator to create a service that already follows the Hub contract:
```bash
create-service.bat <name> [core|module|integration] [port]
```
Example:
```bash
create-service.bat Markets module 8012
```

---

## Core Services (Generic)

### Hestia-Hub 🔀
Service registry + routing gateway.
- Registers services and their capabilities.
- Exposes discovery APIs for Oracle and other services.
- Proxies internal requests by service name.

### Hestia-Archive 🗄️
Single database gateway.
- Stores records, entities, memory, sessions.
- Exposes generic search/filter/query APIs.
- Stores **subscriptions** and **dispatch logs** for proactive notifications.
- Exposes standardized maintenance reconcile routes (`/api/module/maintenance/reconcile` and alias `/api/maintenance/reconcile`) for assistant-triggered archive hygiene tasks.

### Hestia-Oracle 🧠
Conversational reasoning layer with unified agentic tool calling.
- **Single tool-calling path:** all Hub commands + domain tools + memory tools flow through one ReAct agent loop (no separate pre-check or heuristic routing).
- **Visible thinking:** emits `thinking` NDJSON events during the agent loop (reasoning, tool_call, tool_result) and a `tool.summary` signal after the answer.
- **Memory tools:** `memory.save` and `memory.search` are first-class agent loop tools — the LLM decides when to persist or recall facts.
- **Single classify call:** mode + domain + action_intent detected in one LLM call (no separate action intent detection).
- Handles chat sessions and long-term preferences via background memory extraction as safety net.
- Uses Hub discovery + module tools for domain retrieval. Agent loop handles up to 25 turns with early exit for simple tasks.
- Compiles user intents into generic subscription requests written to Archive.
- Injects timezone-aware current datetime context in each turn.
- Accepts file attachments (images, PDFs) via `POST /api/chat/document` with multimodal reasoning.
- **LLM gateway:** sole owner of LLM provider access. Other services use `/api/llm/generate` (prompt) or `/api/llm/chat` (OpenAI-compatible + tools) via Hub with a `use_case` `<module>.<task>` they declare in their Hub registration (`capabilities.llm_usecases`, `hestia_common.oracle_usecases`) — never provider URLs/keys/model names of their own.
- **Oracle a blocchi** (2026-10-19): named providers (`oracle.providers`, keys only in env `ORACLE_KEY_<NAME>`) → reusable chains of provider/model steps (`oracle.chains`; a quota error skips that model until its reset, any error moves to the next step) → use cases (`oracle.usecases`: chain, mode, thinking), all edited in Oracle → Cervello → Modelli. Default chain `veloce` = local Ollama first, then Gemini. Brain mode interna (chains) or esterna (Claude Code / Codex run the loop with Hestia's tools over a stdio MCP bridge; Archive stays the session truth). Every LLM call is a usage row in Archive (`llm-usage`).

### Hestia-Hermes 📨
Proactive dispatch core — the only outbound messenger to the user's clients.
- Consumes domain events and checks matching subscriptions.
- Deduplicates alerts and delivers each notification to **every client** (Hub `layer:client` +
  `capabilities.notify_endpoint`), or only to the client a request came from (others keep it in the inbox).
- Recurring nudges (reminders) never pile up: the module sends `replaces: "<key>"`; Hermes keeps one live
  notification per key on every client with the skip counter (`resolves: true` / `closes` done ends it).
- Read state is global; answers go to the module that asked, first answer wins.
- Writes delivery outcomes to Archive.

### Hestia-Hecate 📥
Gateway and connector runtime for external providers.
- Sole gateway for provider-facing APIs (calendar/email).
- Owns provider auth lifecycle and refresh orchestration.

Provider access model (single entry point):
- Google/Outlook provider runtime and OAuth ownership are centralized in Hecate.
- Domain modules do not open direct provider SDK sessions in their own runtime.
- Domain-level email business APIs are owned by Iris; Hecate can proxy/provider-orchestrate calls through Hub-routed contracts.
- **Mail watcher (one per mailbox):** Chronos job `hecate.mail_watch` (default every 15 min, Themis
  `hecate.mail.watch_interval`) → Gmail history API (`historyId` cursor in `data/mail_watch.json`; expired → `[🔄]`
  search fallback). Optional real push: Gmail `users.watch` + Pub/Sub **streaming pull** (no public URL needed, env
  `HECATE_GMAIL_PUBSUB_*`, renewed by `hecate.mail_watch_renew`); then the check slows to a safety net
  (`hecate.mail.safety_interval`). New mails go to Iris `POST /api/email/incoming`. Hecate never decides who gets a mail.
- Provider auth material (token.json, credentials.json, refresh tokens, service-account JSON) belongs in Hecate or its host-side setup flow, not in Chronos.
- Google OAuth uses loopback redirect + PKCE (the old OOB flow is blocked by Google since 2023). Setup and troubleshooting: `Hestia-Hecate/hestia-hecate.md` → *Google setup*. From the phone: ask Telegram "collega Google Calendar", open the link, paste back the final `localhost` URL.

### Hestia-Atlas 🌐
Host-side shared web fetch gateway.
- Runs directly on host OS (not in Docker) for browser-assisted retrieval.
- Provides `/api/fetch/html` for modules that need resilient page fetching.
- Registers into Hub as `atlas` so callers can route through Hub (`/api/route/atlas/...`).

### Hestia-Telegram 💬
User interface relay for chat, file attachments, and clear session commands.
- Forwards photos and documents (PDF, images) to Oracle's multimodal endpoint.
- Pasted OAuth callback URLs (`.../api/gateway/auth/callback/<provider>?code=`) go straight to Hecate, no LLM involved.
- Streams NDJSON status frames back as typing indicators while Oracle processes.

### Hestia-WebUI 🌐
Web client (.NET 9 backend + Angular frontend, port 19015).
- Shell + own pages: Home, Chat (SignalR streaming of Oracle NDJSON), Settings, "Crea con Hestia" drawer. Everything
  else is a module plugin page: Agenda (Chronos, Google-like calendar; ICS feed stays a WebUI path), Sviluppo (Hephaestus), Notifiche (Hermes),
  Comandi & MCP + Accessi AI (Hestia-MCP), Documenti (Oracle) and the core inside views; old routes redirect.
- Public doors for external AIs (outside `/api/webui/`, no WebUI login): `POST /mcp`, `/.well-known/oauth-*`, `/oauth/*`.
- Backend proxies everything through Hub routing; single-token auth minted from Telegram (`/webui_token`).
- See `Hestia-WebUI/hestia-webui.md` and `Hestia-WebUI/frontend/DESIGN-SYSTEM.md`.

### Hestia-Chronos 📅
Bidirectional calendar integration gateway (port 8008) **and the assistant's own agenda**.
- **Assistant agenda (core):** Hestia's own calendar (`source=hestia`, not synced to your calendars) where modules
  register their rules as data — `event`, `task` (one-off action), `job` (recurring action), `window` (period when
  something is allowed). You can see, move, pause, skip (dismiss), cancel or run them from Telegram; user edits are
  never overwritten. Modules ask `GET /api/agenda/windows/{key}` instead of hardcoding schedules.
  Planned there today: Hecate mail watch and calendar sync (jobs), Athena consolidation / skill curation /
  thinking and Metis training (windows), Claude Pro nights (windows), every Forge task, Hephaestus repair retries
  and Argus rechecks of a service that stays down (tasks). Shared client: `hestia_common.agenda_client`.
  A module retires default rules it no longer declares with `POST /api/agenda/retire {owner, keys}`
  (`AgendaClient.retire`): only rules the module itself created are cancelled, user items stay.
- **Assistant presence:** the assistant's general state (Sveglio, In attesa, Non disturbare, Pisolino, Sonno
  profondo + overlays Occupato, Sto mangiando, Stanco). Signals → data-defined states (Themis
  `chronos.presence.states`) → effects (`work.light`, `work.heavy`, `llm.claude`, `notify.level`, `chat.style`).
  Night = agenda window `assistant.sleep`. **Oracle offline** (Oracle down past `argus.oracle.grace`): Argus sets
  signal `oracle.offline` → overlay «⏳ Non disponibile» (`chat.reply = queued`) + one Hermes notice; chat clients
  queue what Oracle cannot take in Archive (`/api/chat-queue`) and answer it when Chronos says Oracle is back
  (`capabilities.chat_queue_drain`). SPEC `docs/work/2026-10-19-oracle-offline`. WebUI badge shows what the state changes and its history (popover drawn over the page, not clipped by the sidebar). Every user chat counts as activity (Oracle pings with the chat's `client` or `notify_target`, WebUI included). Client: `hestia_common.presence_client`; storage in Archive.
- Unified CRUD API over Google Calendar and Microsoft Outlook simultaneously.
- `target_providers: []` in a request writes to all configured providers at once.
- Provider failures are isolated per-provider and returned as structured error results.
- Consumed by Oracle via Hub routing for document-to-event flows.
- Exposes standardized maintenance reconcile routes (`/api/module/maintenance/reconcile` and alias `/api/maintenance/reconcile`) for assistant-triggered calendar maintenance ticks.
- See `hestia-chronos.md` for credential setup and provider details.

Scope boundary:
- Chronos is calendar-domain orchestration only.
- Chronos does not own provider OAuth/token lifecycle.
- Chronos routes provider-facing calendar operations through Hecate.
- If provider access fails, inspect Hecate configuration/logs before Chronos.

### Hestia-Iris ✉️
Email domain module.
- Provides inbox/message/thread domain APIs.
- Registers `email_search`, `email_send`, and `email_thread` commands to Hub discovery.
- **Mail dispatcher:** receives every new mail from Hecate (`POST /api/email/incoming`), matches it against module
  subscriptions (`/api/email/subscriptions`, declared with `hestia_common.mail_client`), stores the full mail in
  Archive as a raw record under the subscriber's domain (durable, deduped), then rings the module
  (`POST route/<module>/<path> {owner, key, domain, count, reference_ids}`). Page «Email» shows subscriptions and dispatch log.

Scope boundary:
- Iris owns email-domain business logic (search, threading, send abstractions).
- Provider gateway/runtime concerns remain in Hecate when provider mediation is required.

### Hestia-Argus 👁️
System health and log intelligence monitor.
- Sole monitoring authority for health/log anomaly detection.
- Aggregates service health and logs via Hub monitor APIs.
- Emits remediation intents when auto-fix policy allows.
- Does not mutate source code or execute code changes directly.

### Hestia-Hephaestus 🔧
Guarded remediation and coding executor.
- Executes remediation plans produced from Argus/Oracle-triggered incidents.
- Must keep full audit trail and user-visible notifications for each mutation.
- Uses source-control safety primitives: branch-based work, checkpoints, rollback path.
- May execute local build/deploy workflows according to policy tiers.
- Claude Pro budget windows are agenda windows (`forge.claude_nights`, `forge.claude_final`): skip a night to block autonomous Claude work.
- **Forge (self-development):** "aggiungi/correggi X" on Telegram → isolated git branch → coding engine (`oracle` = Oracle's chain of use case `forge.codice`, or Claude Code with a Pro/Max token) → tests → approval → merge/deploy/rollback. Permission modes `ask | auto | full_auto` per group (local/cloud), set from Telegram. Athena (idle retrospective) and Argus (recurring errors) feed it via Hub. See `Hestia-Hephaestus/hestia-hephaestus.md` → *Forge*.

### Hestia-Athena 🧭
Proactive cognition and advisory strategy engine.
- Runs periodic observe→think→score→act→archive loop.
- **Observer**: gathers system state via Hub routing (service health, entity domains, self-state).
- **Strategist**: calls Oracle LLM for reasoning, generates structured action candidates (advisory, remediation, notification, maintenance).
- **Relevance gate**: scores each candidate on urgency, usefulness, novelty, interruption_cost, confidence with retrospective boosting.
- Emits accepted actions to Hermes as `athena.focus_brief` events; publishes advisory hints to Oracle.
- Archives every thinking cycle for audit and client display (`GET /api/athena/thinking`).
- Resource-conscious: single Oracle call per cycle, compact prompts, source-level failure isolation.
- Tracks commitments (action items) with TTL, resolution, and pruning.

### Hestia-Metis 🦉
Continuous improvement organ — dataset curation, benchmark evaluation, LoRA training orchestration.
- **Fifth organ** in the Hestia organ model. Operates on the system's **trajectory over time** (are we improving?), unlike the other four organs that operate on current state.
- **Owns:** feedback aggregation → dataset building → ChatML export → benchmark runs → LoRA training orchestration.
- **Does NOT own:** runtime model inference (Oracle), raw grade storage (Archive), quality judgment (Athena), feedback UI (Telegram).
- Exposes five MCP tools: `metis_dataset_build`, `metis_dataset_export`, `metis_dataset_status`, `metis_benchmark_run`, `metis_loRA_train`.
- In-memory dataset store with configurable deduplication and quality filtering. Exports ChatML, Alpaca, and ShareGPT formats.

### Hestia-Themis ⚖️
Central settings — one place for every module's settings.
- **Owns:** the declared settings schema, validation, scopes (system; user = profile → client → session), presets,
  state (`restart_required`/`offline`), revision, light history/undo, assistant proposals.
- **Does NOT own:** storage (Archive `/api/settings-store/*`), delivery to the user (Hermes), reasoning (Oracle/Athena),
  secrets and infrastructure (env).
- MCP tools `settings_search`, `settings_get`, `settings_propose`, `settings_undo`; no approve tool (only the user answers).

### Hestia-Dummy 🧪
Generic integration testing module.
- Provides deterministic test endpoints for routing, execution, and policy validation.
- Safe mutable/non-mutable testing via `dry_run` toggles.
- Not tied to a single organ; usable by any service that needs an integration target.

### Hestia-MCP 🔌
Hestia's one MCP server (`POST /mcp`, standard MCP over Streamable HTTP).
- Every client lists and runs tools only here, the same way: Oracle, Telegram, WebUI, external AIs.
- Catalog = Hub registry discovery (modules' own `/mcp` + inline commands) as MCP tools, Hestia details in `_meta.hestia`.
- Executes with the shared rules of `hestia_common.tool_call`, always through Hub routing.
- External AIs (Claude Code, Cursor, claude.ai…) come in only through the WebUI door `POST /mcp` (the only service
  behind the tunnel) → Hub → `/mcp/external`, with an **access** (token from the *Accessi AI* page, stored hashed in
  Archive): they see only tools a module marked `"external"`, within the access's scope and tool list, rate-limited
  (`mcp.external.max_calls_per_min`), audited, and their writes leave a silent Hermes inbox entry. Approve, merge and
  rollback never leave the house: Forge stays the only deploy gate (`forge_submit_branch`).
- OAuth 2.1 (claude.ai web/mobile, ChatGPT): Hestia-MCP is the authorization server (`core/oauth.py`: registration,
  PKCE S256, single-use codes, rotating refresh tokens, replay revokes); the WebUI forwards `/.well-known/oauth-*` and
  `/oauth/*` through Hub; `/oauth/authorize` only parks the request: a code exists only after **Consenti** on the
  consent card of *Accessi AI* (behind the WebUI login). A grant is an access of kind `oauth` in the same list.
- Outbound (third-party MCP servers Hestia may use): credentials are Hecate's, in its `.env` only
  (`HECATE_MCP_<NAME>_URL/_KEY`); Hecate lists names and status, never a value.

---

## Domain Modules

### Hestia-Scout 🏠
Real-estate domain module.
- **Mail by push:** subscription `scout:listings` (mail_client); Iris rings `/api/scout/mail`. The old poll job
  `scout.email_cycle` is retired.
- **Pre-parse pipeline:** extracts property URLs from all emails first (zero LLM calls), deduplicates against Archive, then splits into an existing-entity path and a new-entity path.
- **Status update path:** keyword regex scan updates `listing_status` for known entities without LLM.
- **LLM path:** only the minimal representative email set per new URL is sent to the LLM extractor.
- Persists entities in Archive under `real_estate` with `listing_status` field (`available`, `in_negotiation`, `investment_occupied`, `sold`, `unknown`).
- If any downstream step is unavailable (content enrichment, dispatch, etc.), entities are persisted with a generic pending-step marker and retried automatically on later cycles.
- Publishes `entity.upserted` events to Hermes for proactive matching.
- Exposes generic module tools for Oracle retrieval.
- Exposes standardized maintenance reconcile routes (`/api/module/maintenance/reconcile` and alias `/api/maintenance/reconcile`) for assistant-triggered Scout data hygiene.

### Hestia-Hercules 🏋️
Gym coach module (port 19019): exercises, templates and weekly program, live sessions that work offline, records and
progress, goals «N volte a settimana», adaptation by conversation with the assistant (`fitness_*` tools). Rows in
Archive `hercules-store`; reminder through the agenda and Hermes (off by default). Details:
`Hestia-Hercules/hestia-hercules.md`.

### Hestia-Hygieia 🧴
Self care module (port 19018): products with their life (stock, expiry, price per use), routines as ordered steps
with goals, what to do today, diary per body area, stats, shopping list (`selfcare_*` tools). Rows in Archive
`selfcare-store`; reminders through the agenda and Hermes (off by default). Details: `Hestia-Hygieia/hestia-hygieia.md`.

### Hestia-Wardrobe 👕
Wardrobe domain module (port 19017): pieces, accessories, outfits, deterministic «Cosa mi metto» with reasons,
status (laundry, lent…), occasional «Indossato» marks with an optional goal, packing lists, stats. Rows in Archive
`wardrobe-store`, photo bytes in Archive `blobs`; photo recognition only through Oracle; reminders through the agenda
and Hermes (off by default). Details: `Hestia-Wardrobe/hestia-wardrobe.md`.

### Hestia-Plutus 💶
Expenses module «Spese» (port 19020, domain `finance`, `finance_*` tools): transactions, categories and learned rules,
budgets with alerts, recurring payments, monthly summary. Sources: PayPal receipt mails by push (mail_client
subscription), bank statement PDF (Hype) from the plugin *Importa* or sent in chat (Oracle `attachment_handlers`),
preview → commit, PayPal↔bank linking, quick manual entry. Rows in Archive `finance-store`; reminders through the
agenda and Hermes. Details: `Hestia-Plutus/hestia-plutus.md`.

### Hestia-Hephaestus (Module Execution Role)
Although Hephaestus has core safety responsibilities, it operates as an execution organ for remediation and controlled change workflows.
- Trigger source: Argus/Oracle/explicit user command.
- Execution scope: runbook-first, policy-gated mutations.
- Mandatory: notify before/after changes, log commit/branch references, preserve rollback path.

---

## Architectural Rules (Non-Negotiable)

1. Core services are 100% generic.
2. Domain logic stays inside domain modules only.
3. No direct DB access outside Archive.
4. No giant single-file services: modular packages only.
5. Every service must include:
   - project markdown summary
   - `Dockerfile`
   - `docker-compose.yml`
   - `requirements.txt`
   - main package (`app/` or `src/`) with `main.py` and modules
6. Requirement changes must be reflected in service markdown files (`hestia-*.md`) and root documentation in the same change set.
7. **Every service must be unconditionally resilient — no task is ever abandoned.**
   - If a dependency (Atlas, Hermes, Hub, Archive, geocoder, etc.) is unavailable, the work unit must be **flagged as incomplete** in a durable store (Archive entity payload or a local queue file) and **retried automatically** on every subsequent reconcile/recovery cycle.
   - Incomplete work is tracked via generic pending markers (for example `pending_steps.<step_name>=true` or equivalent queue metadata) instead of service-specific coupling.
   - The reconcile loop (or equivalent periodic recovery pass) of every module **must** check all pending flags and resume the failed step before considering a record complete.
   - Data in Archive is never considered partial or stale as long as pending flags remain; enrichment and notification retries run until they succeed or the data expires naturally (e.g. listing sold/removed).
   - Errors are logged with `[🔄]` prefix and enough context to diagnose the failure. Silent failure is forbidden.
8. **Settings are data (Themis):** a tunable knob is declared with `hestia_common.settings_client`, never a new
   env var. Env holds only secrets and infrastructure. The assistant never applies a setting: it proposes, the
   user confirms through Hermes. Personal facts every module needs (week start, currency) are the Themis
   settings `themis.personal.*`, read with `follow_personal()`; no module keeps its own copy. Module reminders
   use `hestia_common.reminders`: the same `<module>.reminder.enabled` (off) / `.max_per_week` settings, the
   schedule as an agenda job (Chronos), delivery through Hermes with `replaces` and `_link`.
9. **Presence is effects, not names:** modules report facts to Chronos (pings, activities, signals) and ask
   effects through `hestia_common.presence_client`; they never test a state name, so new states are data only.
   Chronos down → safe defaults, each module keeps following its own agenda windows.
10. **Organ Model (No functional overlap):**
   - Argus = observe and decide incidents.
   - Hephaestus = execute remediation and controlled code changes.
   - Oracle = reason and orchestrate tool/command flow.
   - Hermes = dispatch notifications — the only outbound messenger to the user's clients.
   - Themis = settings (declared by modules, stored by Archive, changed by the user; the assistant only proposes).
   Multiple services must not duplicate the same responsibility in parallel without an explicit contract reason.

## Autonomous Remediation Contract

1. Monitoring is centralized in Argus; Hephaestus consumes remediation requests and executes.
2. Every mutating remediation must produce:
   - pre-change notice,
   - execution trace,
   - post-change summary,
   - rollback reference.
3. Source control safety is mandatory for autonomous mutation:
   - isolated branch per remediation,
   - atomic commit set,
   - reversible deployment path.
4. Local-first execution is allowed; remote/cluster rollout must be policy-gated and observable.
5. Triggering a personal IDE Copilot session is not a runtime contract; automation must use repository/workflow APIs and service endpoints.

## Deployment Evolution Contract

1. Current default: local build/deploy orchestration.
   Test bench without the local PC: `tools/cloud_test.py` (Claude cloud session or GitHub Codespace); test
   credentials come only from the environment (Codespaces secrets) through `docker-compose.cloud-test.yml`, never files.
   In Codespaces the stack starts by itself (`cloud_test.py start`, waits for Docker, log `.cloud-test/start.log`).
2. Future target: multi-node/cluster delivery with shared Hub discovery.
3. Required for remote rollout:
   - deployment controller contract,
   - health-gated progressive rollout,
   - automatic rollback on failed SLO checks,
   - Argus verification after deploy.

## Documentation Governance (Mandatory)

For every behavior or contract change, update documentation in the same change set:

1. Global rules/contracts: `docs/ARCHITECTURE.md` (this file). Public front page: `readme.md` (update it only when the user-facing picture changes: capabilities, quick start, roadmap).
2. Impacted service docs: `Hestia-*/hestia-*.md`.
3. API contract docs: `Hestia-Swagger/swagger.yml` whenever endpoints, schemas, or Hub-routed command contracts change.

No code-only behavior changes are considered complete without synchronized docs.

## Capability Discovery Contract (Mandatory)

1. Assistant-executable commands must be discoverable from Hub (`/api/discovery/commands`) with complete metadata.
   Hub's discovery is read only by Hestia-MCP: **clients list and run tools only through Hestia-MCP `/mcp`**
   (`hestia_common.mcp_client`, WebUI `HubClient.McpListToolsAsync`), never with their own resolver
   (`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §B2).
   A tool reaches external AIs only if its module adds `"external"` to `clients` (nothing leaves by default; empty
   or `*` is not enough); the module receives `X-Hestia-Access: <access name>` on such calls.
   Tool names of domain modules are `<domain>_<verb>` in English (`fitness_log_sets`, `selfcare_today`,
   `wardrobe_suggest`): the domain the module registers, never the module's mythological name or Italian words.
2. Command entries must include accurate `service`, `method`, `path`, and argument schema/templates to support deterministic execution.
3. Canonical payloads/signals remain rich at source; each client applies its own rendering policy (`minimal|compact|rich`) without mutating source semantics.
4. **Client plugins**: a module that has a UI ships it inside the module (Web Components bundle built from
   `Hestia-<Name>/ui/` with `Hestia-Shared/webui-sdk`) and advertises it with `hestia_common.plugin_client`
   (`capabilities.ui_manifest` in its Hub registration, next to `mcp_endpoint`). Hub exposes ONE catalog organized by
   client × type (`/api/discovery/catalog`: tool, command, page, widget, quick_action). Clients load what they support
   and own their configuration (visibility, dashboards) as their own Themis settings — no central UI module. A plugin
   calls only its own module, under its `api_prefix`. Contract: `docs/work/2026-10-17-client-plugins/SPEC.md` §4.
   Each module owns one `order` decade for its pages and quick actions (Scout 20s, Hercules 30s, Hygieia 40s,
   Wardrobe 50s, Plutus 60s; a new module takes the next free one). Core/system modules declare `kind="core"` and take the
   hundreds (Hub 100, Argus 110, Oracle 120, Athena 130, Hermes 140, Chronos 150, Themis 160, Hephaestus 170,
   Metis 180, Hestia-MCP 190); the WebUI groups them under *Sistema* and builds a ready-made *Sistema* dashboard from their `auto` widgets (Home takes the domain ones); Hub, which never registers with itself, folds its own manifest into the catalog and answers its plugin routes locally (`docs/work/2026-10-18-moduli-core-e-mcp-esterno/`). Module notifications carry `_link: {module, page}` so a
   client can open the plugin page.
5. **Module context**: a domain module that can enrich the assistant's context exposes
   `GET /api/module/context?budget=<chars>` → `{module, domain, updated_at, text}` (one short caveman text, within the
   budget) and advertises it with capability `context_endpoint` and tag `context`. The module decides what is worth
   saying; Oracle decides when to include it. `?topic=<signal key>` asks for details on one of the module's signals
   (unknown topic → the normal line).
5b. **Module signals (reflection in layers)**: a domain module judges its own data deterministically and publishes
   short signals + weekly metrics with `hestia_common.signals_client` (Archive `signals-store`, on write + daily agenda
   job `<module>.signals`). Athena reads only signals (never raw data), links weekly series of different areas and
   asks details via `topic`; its life observations reach the user only in the daily recap («Da tenere d'occhio»).
   System health is a separate Athena track. `docs/work/2026-10-20-riflessione-a-livelli/`.
6. **Module files**: bytes (photos, attachments) go to Archive `/api/blobs` (`owner_module`, deduplicated by sha256);
   the module keeps the blob ids in its own rows and serves images to clients as `{mime, data_b64}`.
7. **Chat attachments for a module**: a module that can take a file sent in chat declares in its Hub capabilities
   `attachment_handlers: [{mime, match, min_hits, path, label}]`. On a match (mime + words in the file text or message)
   Oracle stores the file as an Archive blob (`owner_module=chat`) and calls `POST route/<module>/<path>` with the blob
   id; the module answers `{handled, text}` (the chat reply). No match or failure → normal document analysis.
8. **Mail is push, never poll**: a module that wants emails subscribes with `hestia_common.mail_client`
   (`MailClient(owner).subscribe_async(rules)`, idempotent by key) and exposes the `path` Iris rings. Hecate is the
   only mailbox watcher, Iris the only dispatcher; each mail is stored in Archive (subscriber's domain) **before** the
   module is rung, so a module that is down loses nothing (it processes `/api/archive/<domain>/unevaluated` at startup).
   No module polls Gmail or schedules its own mail job.

## Governance Automation (Mandatory)

1. Pull requests must run the governance checks in `tools/governance/`.
2. `check_docs_sync.py` enforces documentation synchronization for behavior changes.
3. `check_command_contracts.py` enforces command metadata quality and contract-drift safeguards.
4. Rule updates must keep policy text and automation logic aligned in the same change set.

## Messaging Contract (Global UX Rules)

- Web clients (WebUI, plugins) draw minimal stroke icons coloured by intent, never emoji; Telegram keeps emoji. Data shown by both carries `emoji` (Telegram) and `icon` + `tone` (WebUI). Check: `tools/governance/check_icons.py`.

Applies to every user-facing Telegram delivery path (chat replies, command outputs, proactive alerts):

1. **Human-readable first**: dedicated formatters for known commands; Oracle/LLM formatting only for unknown payloads. Never show raw JSON to users.
2. **No "n/d"**: omit fields that have no data instead of printing placeholders.
3. **Minimal emojis**: one or two per section header maximum; no emoji on every line.
4. **Link splitting**: if a message contains property blocks separated by blank lines and any block has a link, each block becomes its own Telegram message (enables Telegram link previews).
5. **HTML parse mode**: all rich user-facing output uses HTML. No markdown bold (`**`) inside HTML content.
6. **HTML resilience**: client renderers must normalize non-Telegram tags (for example `<em>/<strong>`) to Telegram-compatible tags before send; on Telegram parse-entity failure, retry the affected part as plain text.
7. **Conversational alerts**: proactive multi-alert dispatches must read as natural chat, not disconnected notifications.
8. **Message splitting logic is global** via `build_delivery_messages()` and reused by all send paths.
9. **Owner target**: services never hold the owner's chat id. They notify `target: "owner"`; Telegram resolves it
   to its first `ALLOWED_USER_ID`.
10. **Notifications are global**: a client receives Hermes notifications by declaring
   `capabilities.notify_endpoint` on Hub (contract `ClientNotifyRequest` in swagger). Hermes never hardcodes a
   client; nobody else sends to the user's clients.
11. **Document replies**: when Oracle responds to a file attachment, the reply follows the same NDJSON stream contract as text chat. Status frames show as typing indicators; the `final` frame is rendered as HTML and split by `build_chat_messages()`.

## Logging Contract (Global Observability)

1. All services must use `hestia_common.logging_utils.setup_service_logging(service_name)` for uniform setup.
2. Endpoint access logs (`uvicorn.access`) are downgraded to `TRACE` level (5) and reformatted to `event=http_access client=X method=X path=X status=X` — they never appear at `INFO` or `DEBUG`. Set `LOG_LEVEL=TRACE` to see them.
3. `LOG_HEALTH_ACCESS_MODE=off` by default — health-check probes do not produce access logs.
4. Every service exposes `GET /api/logs/level` and `POST /api/logs/level` for runtime log-level control (no restart needed). `POST` body: `{"level": "DEBUG"}`.
5. Logs must be actionable — include the data that helps diagnose issues (lengths, truncation status, entity IDs).
6. Routine keepalive success logs must be `DEBUG`; `INFO` is reserved for state changes (created/updated registration, forced refreshes, startup milestones).
7. Oracle: `INFO` = per-call stats (model, provider, thinking, turns, tools, tokens, answer_len, total_ms). `DEBUG` = full chat transcripts + tool call params/results.

## Startup Readiness Contract

1. Services must wait for Hub readiness before initial Hub registration.
2. If a service has strict startup dependencies (for example Scout requiring Archive/Hecate presence in Hub), it must wait for those dependencies to appear in Hub registry before entering its main processing loop.
3. `STARTUP_WAIT_TIMEOUT_SECONDS=0` means wait indefinitely (default), so transient boot ordering does not produce false failure storms.
4. Startup wait checks are generic and shared (`hestia_common.startup_utils`) rather than hardcoding peer-specific logic per service.

## Registry Propagation Contract

1. Registry change propagation is push-first through Hub events (`hub.registry.changed`) and registered webhooks.
2. Polling is fallback-only (hybrid/poll modes), never the primary update path when push webhook support exists.
3. Telegram command refresh should be webhook-driven by default (`TELEGRAM_REGISTRY_UPDATE_MODE=push`).

## Communication Policy (Hub Gateway — Mandatory)

Hub is THE single gateway for all inter-service communication. Every service knows exactly one address: `HUB_API_URL`.

1. **All inter-service HTTP calls go through Hub routing**: `{HUB_API_URL}/route/{service_name}/{path}`.
2. **No peer service URLs allowed** — env vars like `ARCHIVE_URL`, `HERMES_URL`, `ORACLE_URL`, `MCP_API_URL` are forbidden. Remove them.
3. **Hub routing modes**:
   - Unicast: `/api/route/oracle/api/chat` → one service
   - Multicast: `/api/route/oracle,argus/api/logs/level` → listed services
   - Broadcast: `/api/route/*/api/logs/level` → all registered services
4. Services register on startup and are health-checked by Hub.
5. If one instance goes offline, callers continue through Hub to next healthy instance.
6. External host-only helpers (like Atlas) must still be consumed via Hub route API.
   - Atlas route example: `/api/route/atlas/api/fetch/html`

## Service Template Generator

Use the root generator to scaffold new services with the same object-oriented registration contract:

```bash
create-service.bat <name> [core|module|integration] [port]
```

This creates:
- `Hestia-<Name>/app/main.py` with `HestiaServiceBase`
- `Dockerfile`, `docker-compose.yml`, `requirements.txt`
- `.env` prefilled with standardized `SERVICE_TYPE`, `SERVICE_TAGS`, and Hub URL

## Known Gaps (honest status)

- Hephaestus *remediation* (`/api/hephaestus/remediate*`): rollback is metadata-only (no real revert); real code
  changes go through **Forge**, which has true git branches, merge and revert.
- Metis `benchmark_run` returns `not_implemented`; LoRA training launches your external script (`Hestia-Metis/TODO.md`).
- Embedding model must produce 768-dim vectors (Archive `Vector(768)`); other sizes are stored/searched without vectors (logged).
- Iris threads are grouped by normalized subject (Gmail thread ids are matched when present).
- Hub registry is in memory: every service (Python ones, Hermes, the .NET WebUI) re-registers every 60 s, so it comes
  back after a Hub restart; the Hub shows a service offline after 180 s without a registration. Hermes and the WebUI
  missed this until 2026-10-19 (found by the cloud test bench, `docs/work/2026-10-19-banco-prova-cloud/`).

## Dependency and Flow Map

See [`architecture-and-flow-map.md`](../architecture-and-flow-map.md) for a concise dependency graph and end-to-end data flow map.
