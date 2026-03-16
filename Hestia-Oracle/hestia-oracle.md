# Hestia-Oracle 🧠

**Role:** AI Chat Interface — Conversational Layer
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

The conversational AI brain of Hestia. Receives messages from interface services (e.g. Telegram), maintains chat sessions, routes queries to the correct data domain via Archive, and returns intelligent responses. Abstracts the underlying LLM provider behind a universal connector.

---

## Core Features

### Universal LLM Connector
- Abstracts cloud LLM providers (e.g. OpenAI, Anthropic) and local Ollama behind a single interface.
- Provider is selected via environment config at deploy time.
- If Ollama (Main PC) is unavailable, falls back to cloud provider automatically.

### Session Management
- Each interface (e.g. Telegram) has one active session at a time.
- Sessions store the full conversation history.
- Sessions are persisted to and retrieved from **Archive** (`user` domain) — Oracle holds no local state.
- Sessions can be cleared via an explicit command (triggered by the interface service).

### User Preferences
- Oracle reads and writes user preferences from Archive (`user` domain).
- Preferences are injected into the system prompt to personalize every response.
- Preferences are updated by Oracle itself when the user expresses new preferences in conversation.

### Domain Routing
- Oracle inspects context to determine relevant domains.
- Oracle discovers module tools via Hub discovery endpoint.
- Oracle queries module tools via generic contract, then falls back to Archive generic search.
- Oracle contains no domain-specific branches.

### Proactive Subscription Compiler
- Oracle infers notification intent/preferences from natural language.
- Oracle writes generic subscriptions to Archive.
- Hermes consumes subscriptions from Archive and performs event matching + dispatch.
- Oracle never dispatches notifications directly.

### Retrieval Strategy
- Oracle invokes module tools via a generic endpoint (`POST /api/module-tools/query`) using domain + query + routing metadata.
- Modules interpret domain-specific filters/preferences internally.
- If no module tool responds, Oracle falls back to Archive `/api/entities/search`.
- Context sent to the analyst model is compacted to avoid context bloat.

### Internal Architecture (SoC)
- `core/oracle_engine.py`: thin orchestration layer only.
- `core/services/router_service.py`: domain routing JSON extraction.
- `core/services/module_registry.py`: Hub-based dynamic tool discovery and per-domain endpoint registry.
- `core/services/retrieval_service.py`: module-tool query + Archive fallback retrieval pipeline.
- `core/services/memory_service.py`: LLM-first preference extraction + subscription intent extraction.
- `core/services/context_builder.py`: history/entity compaction + final analyst prompt assembly.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat` | Send a message, receive a response |
| `DELETE` | `/sessions/{session_id}` | Clear a session |
| `GET` | `/sessions/{session_id}` | Retrieve session history |
| `GET` | `/health` | Service health + LLM provider status |

### `POST /chat` payload
```json
{
  "session_id": "telegram_main",
  "message": "Hai trovato nuove case oggi?",
  "notify_target": "5770661128"
}
```

### `POST /chat` stream contract (NDJSON)

All interfaces consume the same event schema from Oracle:

- `{"type":"status","content":"..."}`
- `{"type":"signal","event":"memory.preference.added|memory.preference.removed|subscription.added|subscription.changed|subscription.removed","content":"...","data":{...}}`
- `{"type":"final","reply":"...","domain":"..."}`

This makes UI behavior standardized: Telegram, web app, mobile app, or voice UI can all render the same lifecycle and user notifications.

---

## Constraints

- Oracle never accesses the database directly — all persistence goes through Archive.
- Oracle does not manage Ingest connectors or trigger data fetches — it only reads from Archive.
- No domain-specific logic is hardcoded — domain routing is driven by config, not code.
- Oracle does not know which interface is calling it — session_id is the only identity.
- Oracle does not dispatch push alerts; it only compiles user intent into generic subscriptions.
