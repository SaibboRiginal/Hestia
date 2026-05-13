# Project Hestia 🏛️

Project Hestia is a containerized, service-oriented assistant platform built with strict engineering rules:
- **Separation of Concerns (SoC)**
- **Core Genericity** (core services never contain domain logic)
- **Modular Expandability** (new capability = new service)
- **Enterprise-grade maintainability** (clear contracts, observability, graceful degradation)

Stack baseline: Python · FastAPI · PostgreSQL + pgvector · Docker · Ollama.

---

## Core Topology

Always-on node (Raspberry Pi): `Hub`, `Archive`, `Oracle`, `Telegram`, `Hecate`, `Hermes`, `Chronos`, `Iris`

Best-effort high-power node (Main PC): domain modules (e.g. `Scout`), Ollama, local DB replica.

Host OS shared utility (Windows/Linux): `Atlas` (runs outside Docker, registers in Hub)

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

### Hestia-Oracle 🧠
Conversational reasoning layer.
- Handles chat sessions and long-term preferences.
- Uses Hub discovery + module tools for domain retrieval.
- Compiles user intents into generic subscription requests written to Archive.
- Accepts file attachments (images, PDFs) via `POST /api/chat/document` and reasons over them using multimodal LLM (Gemini vision + pypdf for Ollama path).
- LLM roles: `router` → `gemini-2.0-flash-lite`, `scribe` → `gemini-2.0-flash`, `analyst` → `gemini-2.5-flash`; Ollama primary for all roles (`gemma-4-26B-A4B-it-UD-IQ4_NL:latest`).

### Hestia-Hermes 📨
Proactive dispatch core (new).
- Consumes domain events and checks matching subscriptions.
- Deduplicates alerts and dispatches via generic channels.
- Writes delivery outcomes to Archive.

### Hestia-Hecate 📥
Gateway and connector runtime for external providers.
- Sole gateway for provider-facing APIs (calendar/email).
- Owns provider auth lifecycle and refresh orchestration.

### Hestia-Atlas 🌐
Host-side shared web fetch gateway.
- Runs directly on host OS (not in Docker) for browser-assisted retrieval.
- Provides `/api/fetch/html` for modules that need resilient page fetching.
- Registers into Hub as `atlas` so callers can route through Hub (`/api/route/atlas/...`).

### Hestia-Telegram 💬
User interface relay for chat, file attachments, and clear session commands.
- Forwards photos and documents (PDF, images) to Oracle's multimodal endpoint.
- Streams NDJSON status frames back as typing indicators while Oracle processes.

### Hestia-Chronos 📅
Bidirectional calendar integration gateway (port 8008).
- Unified CRUD API over Google Calendar and Microsoft Outlook simultaneously.
- `target_providers: []` in a request writes to all configured providers at once.
- Provider failures are isolated per-provider and returned as structured error results.
- Consumed by Oracle via Hub routing for document-to-event flows.
- See `hestia-chronos.md` for credential setup and provider details.

### Hestia-Iris ✉️
Email domain module.
- Provides inbox/message/thread domain APIs.
- Registers `email_search`, `email_send`, and `email_thread` commands to Hub discovery.

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

### Hestia-Athena 🧭
Proactive cognition and advisory strategy engine.
- Computes bounded proactive hints and priorities.
- Feeds advisory context to Oracle without overriding execution truth.
- Keeps runtime/task observability for why it suggested action or silence.

### Hestia-Dummy 🧪
Generic integration testing module.
- Provides deterministic test endpoints for routing, execution, and policy validation.
- Safe mutable/non-mutable testing via `dry_run` toggles.
- Not tied to a single organ; usable by any service that needs an integration target.

---

## Domain Modules

### Hestia-Scout 🏠
Real-estate domain module.
- **Pre-parse pipeline:** extracts property URLs from all emails first (zero LLM calls), deduplicates against Archive, then splits into an existing-entity path and a new-entity path.
- **Status update path:** keyword regex scan updates `listing_status` for known entities without LLM.
- **LLM path:** only the minimal representative email set per new URL is sent to the LLM extractor.
- Persists entities in Archive under `real_estate` with `listing_status` field (`available`, `in_negotiation`, `investment_occupied`, `sold`, `unknown`).
- If any downstream step is unavailable (content enrichment, dispatch, etc.), entities are persisted with a generic pending-step marker and retried automatically on later cycles.
- Publishes `entity.upserted` events to Hermes for proactive matching.
- Exposes generic module tools for Oracle retrieval.

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
8. **Organ Model (No functional overlap):**
   - Argus = observe and decide incidents.
   - Hephaestus = execute remediation and controlled code changes.
   - Oracle = reason and orchestrate tool/command flow.
   - Hermes = dispatch notifications.
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
2. Future target: multi-node/cluster delivery with shared Hub discovery.
3. Required for remote rollout:
   - deployment controller contract,
   - health-gated progressive rollout,
   - automatic rollback on failed SLO checks,
   - Argus verification after deploy.

## Documentation Governance (Mandatory)

For every behavior or contract change, update documentation in the same change set:

1. Root documentation: `readme.md`.
2. Impacted service docs: `Hestia-*/hestia-*.md`.
3. API contract docs: `Hestia-Swagger/swagger.yml` whenever endpoints, schemas, or Hub-routed command contracts change.

No code-only behavior changes are considered complete without synchronized docs.

## Capability Discovery Contract (Mandatory)

1. Assistant-executable commands must be discoverable from Hub (`/api/discovery/commands`) with complete metadata.
2. Command entries must include accurate `service`, `method`, `path`, and argument schema/templates to support deterministic execution.
3. Canonical payloads/signals remain rich at source; each client applies its own rendering policy (`minimal|compact|rich`) without mutating source semantics.

## Governance Automation (Mandatory)

1. Pull requests must run the governance checks in `tools/governance/`.
2. `check_docs_sync.py` enforces documentation synchronization for behavior changes.
3. `check_command_contracts.py` enforces command metadata quality and contract-drift safeguards.
4. Rule updates must keep policy text and automation logic aligned in the same change set.

## Messaging Contract (Global UX Rules)

Applies to every user-facing Telegram delivery path (chat replies, command outputs, proactive alerts):

1. **Human-readable first**: dedicated formatters for known commands; Oracle/LLM formatting only for unknown payloads. Never show raw JSON to users.
2. **No "n/d"**: omit fields that have no data instead of printing placeholders.
3. **Minimal emojis**: one or two per section header maximum; no emoji on every line.
4. **Link splitting**: if a message contains property blocks separated by blank lines and any block has a link, each block becomes its own Telegram message (enables Telegram link previews).
5. **HTML parse mode**: all rich user-facing output uses HTML. No markdown bold (`**`) inside HTML content.
6. **Conversational alerts**: proactive multi-alert dispatches must read as natural chat, not disconnected notifications.
7. **Message splitting logic is global** via `build_delivery_messages()` and reused by all send paths.
8. **Document replies**: when Oracle responds to a file attachment, the reply follows the same NDJSON stream contract as text chat. Status frames show as typing indicators; the `final` frame is rendered as HTML and split by `build_chat_messages()`.

## Logging Contract (Global Observability)

1. All services must log key decision points with tagged prefixes (e.g., `[ENRICH]`, `[CMD]`, `[DISPATCH]`, `[SEND]`).
2. Scout must log: fetch method used, pre/post enrichment summary state, truncation warnings, geocoding results.
3. Telegram must log: command execution, output rendering mode, message part count, dispatch buffering.
4. Logs must be actionable — include the data that helps diagnose issues (lengths, truncation status, entity IDs).
5. Routine keepalive success logs must be `DEBUG`; `INFO` is reserved for state changes (created/updated registration, forced refreshes, startup milestones).

## Startup Readiness Contract

1. Services must wait for Hub readiness before initial Hub registration.
2. If a service has strict startup dependencies (for example Scout requiring Archive/Ingest presence in Hub), it must wait for those dependencies to appear in Hub registry before entering its main processing loop.
3. `STARTUP_WAIT_TIMEOUT_SECONDS=0` means wait indefinitely (default), so transient boot ordering does not produce false failure storms.
4. Startup wait checks are generic and shared (`hestia_common.startup_utils`) rather than hardcoding peer-specific logic per service.

## Registry Propagation Contract

1. Registry change propagation is push-first through Hub events (`hub.registry.changed`) and registered webhooks.
2. Polling is fallback-only (hybrid/poll modes), never the primary update path when push webhook support exists.
3. Telegram command refresh should be webhook-driven by default (`TELEGRAM_REGISTRY_UPDATE_MODE=push`).

## Communication Policy (Hot Swap)

To support hot swapping core instances across Raspberry and Main PC:

1. Service addressing is logical (`archive`, `oracle`, `ingest`, `hermes`, modules) and resolved by Hub.
2. Cross-service HTTP calls use Hub route API or Hub discovery before direct call.
3. Hardcoded peer container URLs are fallback-only, never primary routing.
4. Services register on startup and are health-checked by Hub.
5. If one instance goes offline, callers continue through Hub to next healthy instance.
6. External host-only helpers (like `fetch`) must still be consumed via Hub route API when possible.
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
