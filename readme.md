# Project Hestia 🏛️

Project Hestia is a containerized, service-oriented assistant platform built with strict engineering rules:
- **Separation of Concerns (SoC)**
- **Core Genericity** (core services never contain domain logic)
- **Modular Expandability** (new capability = new service)
- **Enterprise-grade maintainability** (clear contracts, observability, graceful degradation)

Stack baseline: Python · FastAPI · PostgreSQL + pgvector · Docker · Ollama.

---

## Core Topology

Always-on node (Raspberry Pi): `Hub`, `Archive`, `Oracle`, `Telegram`, `Ingest`, `Hermes`

Best-effort high-power node (Main PC): domain modules (e.g. `Scout`), Ollama, local DB replica.

Host OS shared utility (Windows/Linux): `Fetch` (runs outside Docker, registers in Hub)

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
User interface relay for chat + clear session commands.

---

## Domain Modules

### Hestia-Scout 🏠
Real-estate domain module.
- Fetches and extracts entities.
- Persists entities in Archive under `real_estate`.
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

## Messaging Contract (Global UX Rules)

Applies to every user-facing Telegram delivery path (chat replies, command outputs, proactive alerts):

1. **Human-readable first**: dedicated formatters for known commands; Oracle/LLM formatting only for unknown payloads. Never show raw JSON to users.
2. **No "n/d"**: omit fields that have no data instead of printing placeholders.
3. **Minimal emojis**: one or two per section header maximum; no emoji on every line.
4. **Link splitting**: if a message contains property blocks separated by blank lines and any block has a link, each block becomes its own Telegram message (enables Telegram link previews).
5. **HTML parse mode**: all rich user-facing output uses HTML. No markdown bold (`**`) inside HTML content.
6. **Conversational alerts**: proactive multi-alert dispatches must read as natural chat, not disconnected notifications.
7. **Message splitting logic is global** via `build_delivery_messages()` and reused by all send paths.

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
