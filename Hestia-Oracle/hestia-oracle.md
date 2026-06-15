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
- Abstracts cloud LLM providers (Gemini) and local Ollama behind a single `UniversalAgent` interface.
- Provider and model are selected via environment config at deploy time.
- **LLM roles:** `router` (classification), `scribe` (extraction), `analyst` (heavy reasoning), `embedder`. Each role has a primary + fallback agent pair.
- **Ollama primary model:** `gemma-4-26B-A4B-it-UD-IQ4_NL:latest` (all roles).
- **Gemini fallbacks per role** (to spread free-tier quota): router → `gemini-2.0-flash-lite`, scribe → `gemini-2.0-flash`, analyst → `gemini-2.5-flash`, embedding → `gemini-embedding-001`.
- If Ollama (Main PC) is unavailable, falls back to the assigned Gemini model automatically.
- `UniversalAgent.ask_with_attachment(file_bytes, mime_type, user_message)` enables multimodal reasoning over images and PDFs (see Multimodal below).

### Session Management
- Each interface (e.g. Telegram) has one active session at a time.
- Sessions store the full conversation history.
- Sessions are persisted to and retrieved from **Archive** (`user` domain) — Oracle holds no local state.
- Sessions can be cleared via an explicit command (triggered by the interface service).

### Temporal Context Awareness
- Every chat turn injects explicit current date/time context (timezone-aware) into routing and analysis prompts.
- Relative temporal expressions such as "oggi", "domani", and "la prossima settimana" are resolved against that context before planning/tool reasoning.
- Timezone is configurable via environment (`ORACLE_TIMEZONE`, default `Europe/Rome`).

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

### Multimodal Document Understanding
- Oracle accepts file attachments (images and PDFs) via `POST /api/chat/document` (multipart/form-data).
- Supported types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `image/heic`, `image/heif`, `application/pdf`.
- **Gemini path:** file bytes are sent natively as `types.Part.from_bytes()` in the contents list — Gemini handles images and PDFs without preprocessing.
- **Ollama path:** images are base64-encoded and passed in the `images` field; PDFs are pre-converted to text with `pypdf` before the text prompt.
- The analyst LLM reasons over the document and the user's instruction together, then returns a streamed NDJSON reply (same protocol as `/api/chat`).
- Document turns are persisted in chat history so the session remains coherent.

### Retrieval Strategy
- Oracle invokes module tools via a generic endpoint (`POST /api/module-tools/query`) using domain + query + routing metadata.
- Modules interpret domain-specific filters/preferences internally.
- If no module tool responds, Oracle falls back to Archive `/api/entities/search`.
- Context sent to the analyst model is compacted to avoid context bloat.

### Athena Advisory Hints
- Oracle can ingest Athena advisory hints through `POST /api/athena/hints`.
- Hints are advisory-only context and do not bypass Oracle action execution contracts.
- Chat/planner prompt assembly can include relevant non-expired hints for the active session and domain.

### Prompt Variant Gating (A/B)
- Planner and alert formatter prompts support env-gated variant selection.
- Deterministic variant selection uses a stable bucketing seed (`session_id`, command/trace context, and salt).
- Selected variant IDs are logged for regression and quality comparisons.

### Agentic Tool Calling (Unified)
- All tool execution flows through a single ReAct-style agent loop (`core/agent_loop.py`).
- A single tool manifest is built per turn: domain search tools + all Hub-discovered commands + memory tools.
- The LLM decides which tools to call and in what order — no separate pre-check or heuristic routing.
- **Max agent turns:** configurable via `ORACLE_MAX_AGENT_TURNS` (default 25). Complex multi-step tasks can use many turns; simple tasks exit early (1-2 turns).
- **Early exit:** when the LLM produces text without tool calls for 2 consecutive turns after having already called tools, the loop terminates.

### Visible Thinking
- The agent loop emits **thinking** NDJSON events (`type: "thinking"`) for real-time visibility:
  - `action: "reasoning"` — LLM reasoning before a tool call
  - `action: "tool_call"` — about to execute a named tool
  - `action: "tool_result"` — tool execution completed (with result count, duration)
- A **tool summary** signal (`event: "tool.summary"`) is emitted after the final answer, carrying a compact log of every tool invocation with parameters, results, and timing.
- Clients (e.g. Telegram) render tool activity as status updates during the loop and a compact summary card after the answer.

### Memory as First-Class Tools
- `memory.save` — agent loop tool to persist a durable user fact immediately.
- `memory.search` — agent loop tool to recall saved preferences/memories during conversation.
- Background memory extraction still runs as a safety net, but the primary memory path is tool-driven.
- Memory taxonomy (P1-8): `conversational_history`, `durable_user_preference`, `task_goal_state`, `domain_fact_entity`, `assistant_commitment`.

### Internal Architecture (SoC)
- `core/oracle_engine.py`: thin orchestration layer — wires services, runs the chat phases.
- `core/agent_loop.py`: ReAct-style multi-turn tool execution loop with thinking emission.
- `core/services/chat_classifier.py`: single LLM call for mode + domain + action_intent.
- `core/services/module_registry.py`: Hub-based dynamic tool discovery and per-domain endpoint registry.
- `core/services/retrieval_service.py`: module-tool query + Archive fallback retrieval pipeline.
- `core/services/memory_service.py`: LLM-first preference extraction + subscription intent extraction + agent-loop memory tools.
- `core/services/context_builder.py`: history/entity compaction + final analyst prompt assembly.
- `core/services/prompt_config.py`: centralized prompt management with A/B variant gating.
- `core/services/stream_emitter.py`: NDJSON event formatting for all stream types.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Send a message, receive NDJSON stream |
| `POST` | `/api/chat/document` | Send a file + optional message, receive NDJSON stream |
| `POST` | `/api/format` | Format a structured payload into human-readable text |
| `POST` | `/api/subscriptions/compile` | Compile a notification subscription from natural language |
| `POST` | `/api/llm/generate` | Raw LLM call for internal service use |
| `POST` | `/api/athena/hints` | Ingest Athena advisory hint payload |
| `GET` | `/api/athena/hints` | List non-expired Athena hints (optional `session_id`) |
| `DELETE` | `/api/chat/{session_id}` | Clear a session |
| `GET` | `/health` | Service health |

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

- `{"type":"status","content":"..."}` — progress messages (shown as live status updates).
- `{"type":"thinking","action":"reasoning|tool_call|tool_result","content":"...","turn":N,"tool":"...","metadata":{...}}` — agent loop visibility events.
- `{"type":"token","text":"..."}` — incremental LLM output tokens.
- `{"type":"final","reply":"...","domain":"..."}` — terminal answer event.
- `{"type":"signal","event":"memory.preference.added|...|tool.summary|...","content":"...","data":{...}}` — side-channel events including tool-call summary.
- `{"type":"question","question_id":"...","header":"...","prompt":"...","kind":"...","options":[...]}` — interactive approval prompts.

This makes UI behavior standardized: Telegram, web app, mobile app, or voice UI can all render the same lifecycle and user notifications.

---

## Constraints

- Oracle never accesses the database directly — all persistence goes through Archive.
- Oracle does not manage Hecate connectors or trigger data fetches — it only reads from Archive.
- No domain-specific logic is hardcoded — domain routing is driven by config, not code.
- Oracle does not know which interface is calling it — session_id is the only identity.
- Oracle does not dispatch push alerts; it only compiles user intent into generic subscriptions.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
