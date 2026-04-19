# Project Hestia 🏛️

Project Hestia is a containerized, service-oriented assistant platform built with strict engineering rules:
- **Separation of Concerns (SoC)**
- **Core Genericity** (core services never contain domain logic)
- **Modular Expandability** (new capability = new service)
- **Enterprise-grade maintainability** (clear contracts, observability, graceful degradation)

Stack baseline: Python · FastAPI · PostgreSQL + pgvector · Docker · Ollama.

---

## Core Topology

Always-on node (Raspberry Pi): `Hub`, `Archive`, `Oracle`, `Telegram`, `Ingest`, `Hermes`, `Chronos`

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

### Hestia-Ingest 📥
Generic connector runtime for raw data fetching.

### Hestia-Atlas 🌐
Host-side shared web fetch gateway.
- Runs directly on host OS (not in Docker) for browser-assisted retrieval.
- Provides `/api/fetch/html` for modules that need resilient page fetching.
- Registers into Hub as `fetch` so callers can route through Hub (`/api/route/fetch/...`).

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

---

## Domain Modules

### Hestia-Scout 🏠
Real-estate domain module.
- **Pre-parse pipeline:** extracts property URLs from all emails first (zero LLM calls), deduplicates against Archive, then splits into an existing-entity path and a new-entity path.
- **Status update path:** keyword regex scan updates `listing_status` for known entities without LLM.
- **LLM path:** only the minimal representative email set per new URL is sent to the LLM extractor.
- Persists entities in Archive under `real_estate` with `listing_status` field (`available`, `in_negotiation`, `investment_occupied`, `sold`, `unknown`).
- Publishes `entity.upserted` events to Hermes for proactive matching.
- Exposes generic module tools for Oracle retrieval.

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
   - `src/` with `main.py` and modules
6. Requirement changes must be reflected in service markdown files (`hestia-*.md`) and root documentation in the same change set.
7. **Every service must be unconditionally resilient — no task is ever abandoned.**
   - If a dependency (Atlas, Hermes, Hub, Archive, geocoder, etc.) is unavailable, the work unit must be **flagged as incomplete** in a durable store (Archive entity payload or a local queue file) and **retried automatically** on every subsequent reconcile/recovery cycle.
   - Incomplete work is tracked via explicit payload flags (e.g. `atlas_enriched=False`, `hermes_notified=False`, `geo_enriched=False`). A missing flag or `True` means done; `False` means pending retry.
   - The reconcile loop (or equivalent periodic recovery pass) of every module **must** check all pending flags and resume the failed step before considering a record complete.
   - Data in Archive is never considered partial or stale as long as pending flags remain; enrichment and notification retries run until they succeed or the data expires naturally (e.g. listing sold/removed).
   - Errors are logged with `[🔄]` prefix and enough context to diagnose the failure. Silent failure is forbidden.

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

## Communication Policy (Hot Swap)

To support hot swapping core instances across Raspberry and Main PC:

1. Service addressing is logical (`archive`, `oracle`, `ingest`, `hermes`, modules) and resolved by Hub.
2. Cross-service HTTP calls use Hub route API or Hub discovery before direct call.
3. Hardcoded peer container URLs are fallback-only, never primary routing.
4. Services register on startup and are health-checked by Hub.
5. If one instance goes offline, callers continue through Hub to next healthy instance.
6. External host-only helpers (like `fetch`) must still be consumed via Hub route API when possible.

## Service Template Generator

Use the root generator to scaffold new services with the same object-oriented registration contract:

```bash
create-service.bat <name> [core|module|integration] [port]
```

This creates:
- `Hestia-<Name>/app/main.py` with `HestiaServiceBase`
- `Dockerfile`, `docker-compose.yml`, `requirements.txt`
- `.env` prefilled with standardized `SERVICE_TYPE`, `SERVICE_TAGS`, and Hub URL
