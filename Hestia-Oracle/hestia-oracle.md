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
- **Use-case model config** via `MODEL_USECASE_*` env vars: `generic` (chat, classify, tools, memory, format), `reasoning` (deep thinking, loaded on demand), `code` (code generation), `embedding` (vectors). Each use case has primary + fallback provider/model pair. Mode (quick/auto/thinking) controls orchestration process; use case controls which brain.
- If primary (Ollama) is unavailable, falls back to the assigned Gemini model automatically at runtime.
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
- **Selective memory (Claude-like)**: `memory_intent.is_memory_worthy()` gates the background extractor — greetings,
  tests, acknowledgements and plain questions never reach it; only "ricorda / d'ora in poi", removals, notification
  requests and first-person durable facts/preferences do. The extractor prompt (`memory_preferences_template`)
  keeps only durable, user-stated facts. Each save/removal is announced with a `notice`.
- The "no action executed" contract is injected into quick answers only when the message has write intent
  (`has_write_intent`), so "test" / "ciao" no longer get "Non risulta eseguita alcuna azione".

### Domain Routing
- Oracle inspects context to determine relevant domains.
- Oracle discovers module tools via Hub discovery endpoint.
- Oracle queries module tools via generic contract, then falls back to Archive generic search.
- Oracle contains no domain-specific branches.
- **System domain structural invariant:** `domain=system` always implies `domain_query` mode regardless of classifier confidence — system introspection requires live tool calls to answer factually.

### Proactive Subscription Compiler
- Oracle infers notification intent/preferences from natural language.
- Oracle writes generic subscriptions to Archive.
- Hermes consumes subscriptions from Archive and performs event matching + dispatch.
- Oracle never dispatches notifications directly.

### Multimodal Document Understanding
- Oracle accepts file attachments (images and PDFs) via `POST /api/chat/document` (multipart/form-data).
- `POST /api/chat/document/json` — same, JSON body `{message, session_id, notify_target, client_instructions,
  filename, mime_type, content_base64 | data_uri}` for Hub clients (Hub envelopes cannot carry multipart; used by the WebUI).
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
- **Ollama models**: To enable reasoning content in the stream, the `think` parameter must be set to `true` in the API payload. This is automatically handled by the UniversalAgent when `thinking=True`.

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
| `POST` | `/api/llm/generate` | Raw LLM call for internal service use — primary/fallback chain follows `MODEL_USECASE_GENERIC_{PROVIDER,MODEL}` + `MODEL_USECASE_GENERIC_FALLBACK_{PROVIDER,MODEL}` env vars (same source of truth as AgentFactory) |
| `POST` | `/api/athena/hints` | Ingest Athena advisory hint payload |
| `GET` | `/api/athena/hints` | List non-expired Athena hints (optional `session_id`) |
| `DELETE` | `/api/chat/{session_id}` | Clear a session |
| `GET` | `/api/chat/context?session_id=` | Context-window stats (token breakdown, compaction availability) |
| `POST` | `/api/chat/compact?session_id=` | Force-compact conversation history via LLM summarisation |
| `GET` | `/api/sessions` | Global Oracle state (models, uptime, Hub URL) |
| `GET` | `/health` | Service health |

### MCP Tools (Plan P3c)

Exposed via `/mcp` endpoint, registered with Hestia-MCP:

| Tool | Description |
|------|-------------|
| `memory.save` | Save a durable user preference |
| `memory.search` | Search saved preferences |
| `documents.search` | Search uploaded documents |
| `oracle.context_stats` | Session context breakdown |
| `oracle.compact` | Force context compaction |
| `oracle.session_info` | Global Oracle state |
| `oracle.logs_query` | Query in-memory log buffer (default level: WARNING) |

### Execution Modes (Plan P1-3)

| Mode | think | Classify | Description |
|------|-------|----------|-------------|
| `quick` | False | No | Single ask, no tools. <2s latency |
| `auto` | True (agent loop) | Yes | Classify → quick_chat (no think) or agent loop (with think). Default |
| `thinking` | True | Yes | Full agent loop with visible chain-of-thought |

Mode and model are independent — any mode works with any model (`generic`/`reasoning`/`code`).
Model names come from env vars (`MODEL_USECASE_GENERIC_MODEL`, etc.) — no hardcoded models.

### `POST /chat` payload
```json
{
  "session_id": "telegram_main",
  "message": "Hai trovato nuove case oggi?",
  "notify_target": "123456789"
}
```

### `POST /chat` stream contract (NDJSON)

All interfaces consume the same event schema from Oracle:

- `{"type":"status","content":"..."}` — progress messages (shown as live status updates).
- `{"type":"thinking","action":"reasoning|tool_call|tool_result","content":"...","turn":N,"tool":"...","metadata":{...}}` — agent loop visibility events.
- `{"type":"token","text":"..."}` — incremental LLM output tokens.
- `{"type":"final","reply":"...","domain":"..."}` — terminal answer event.
- `{"type":"signal","event":"memory.preference.added|...|tool.summary|...","content":"...","data":{...}}` — side-channel events including tool-call summary (machine/audit).
- `{"type":"notice","kind":"memory.saved","level":"success","icon":"memory","emoji":"💾","title":"Ricordato","detail":"..."}` — **standard system message** for the user (memory saved/removed, write actions done/failed, subscriptions, documents). Every user-facing signal also emits its notice twin; write tools (`ToolDefinition.writes`) emit `action.done|failed`. Background-memory notices arrive after `final` (waits up to `ORACLE_MEMORY_NOTICE_WAIT_SECONDS`, default 8). Spec: `Hestia-Shared/hestia-shared.md` § Response packets.
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

## User activity (idle signal)

`GET /api/activity` → `{last_user_activity_ts, idle_seconds}`. Updated on `/api/chat` and `/api/chat/document`
only when `notify_target` is present (real client chats; internal callers like Argus narration are ignored).
Athena uses it to think only while the user is idle.

## LLM gateway (single owner of provider access)

Other services never hold LLM URLs/keys; they call Oracle via Hub.

| Method | Path | Description |
|---|---|---|
| GET | `/api/llm/profiles` | Profiles with model + availability (`check=false` skips probing). No secrets. |
| POST | `/api/llm/chat` | OpenAI-compatible chat on a profile: `{profile, messages, tools?, temperature?, model?}` → provider JSON |
| POST | `/api/llm/generate` | Plain prompt → `{response}` (Athena, Metis) |
| GET | `/api/llm/code/status` | Claude Code ready? (CLI installed, token, worktree root mounted) |
| POST | `/api/llm/code` | "code" use case: run Claude Code (Pro/Max) in a Forge worktree `{workdir, prompt, append_system_prompt, max_turns, timeout_seconds}` → `{ok, summary, turns, cost_usd, transcript_path}`. Runs `claude -p --output-format stream-json --verbose`; every line is written live to `<ORACLE_CODE_WORKDIR_ROOT>/.transcripts/<task>.jsonl` (outside the worktree) for the WebUI Sviluppo page |

Profiles: `ORACLE_LLM_PROFILE_<NAME>_BASE_URL` / `_MODEL` / `_API_KEY` (OpenAI-compatible base, e.g. `…/v1`).
`local` defaults to Ollama (host of `OLLAMA_API_URL` or `OLLAMA_URL` + `/v1`, model `MODEL_USECASE_CODE_MODEL` or `qwen2.5-coder:14b`).
Example cloud: `ORACLE_LLM_PROFILE_CLOUD_BASE_URL=https://openrouter.ai/api/v1`, `_MODEL=qwen/qwen3-coder`, `_API_KEY=sk-or-…`.
Timeout per call: `ORACLE_LLM_CHAT_TIMEOUT_SEC` (600). Used by Hephaestus Forge engines `local`/`cloud`.

## Prompts (caveman style, single source)

- All prompts live in `app/core/services/prompt_config.py` (`_DEFAULT_PROMPTS`). Style: short imperative lines,
  zero filler — every token is paid on every turn (small local context, billed cloud). ~40% fewer chars than before.
- `app/prompts/oracle_prompts.json` (or `ORACLE_PROMPTS_FILE`) is for **runtime overrides only** and ships empty `{}`.
  It used to duplicate the defaults with drifted content (two sources of truth); the live persona (female voice,
  premium tone) and Telegram-HTML rules were merged into the defaults.
- Removed dead prompts never referenced by code: `router_system`, `scribe_system`, `quick_chat_template`,
  `action_selector_template`, `action_intent_detector_template`, `arg_picker_scope_selector_template`.
- Classifier routes self-development requests ("aggiungi una funzione", "approva sviluppo", "usa il cloud") to `domain=system`.

## REST mirrors of MCP tools

`POST /api/memory {fact, domain}`, `GET /api/memory?query=`, `GET /api/documents/search?query=` — the MCP tool
descriptors declared these paths but Oracle did not serve them, so Hub/Telegram/MCP-gateway calls got 404.

Other fixes: session summaries written in a background thread to `POST /api/entities` (domain `session_summary`);
`HubClient.post` raises when Archive rejects a write inside the Hub envelope (was silently "successful");
agent loop no longer injects a duplicated `RESULTS_DICT` block and keeps parallel tool results in call order.

### Claude Code ("code" use case on the Pro/Max subscription)

- Build Oracle with `--build-arg INSTALL_CLAUDE_CODE=1`; put `CLAUDE_CODE_OAUTH_TOKEN` (run `claude setup-token` on
  your PC, sign in with the Pro account) in `Hestia-Oracle/app/.env`. Optional `ORACLE_CLAUDE_MODEL`.
- Only for code tasks inside `ORACLE_CODE_WORKDIR_ROOT` (`/forge/worktrees`, shared with Hephaestus); never for
  general chat (the subscription covers Claude Code for development, not an API backend).

## LLM gateway profiles (Forge engines)

Built-in profiles, no extra env: `local` = Ollama + `MODEL_USECASE_CODE_MODEL`; `cloud` = Gemini (OpenAI-compatible
endpoint) + `MODEL_USECASE_CODE_FALLBACK_MODEL` + `GEMINI_API_KEY`. `ORACLE_LLM_PROFILE_<NAME>_BASE_URL/_MODEL/_API_KEY`
only override them or add another provider. Claude Code CLI is installed by default
(`ORACLE_INSTALL_CLAUDE_CODE=0` for a slimmer image) and used only when `CLAUDE_CODE_OAUTH_TOKEN` is set.
