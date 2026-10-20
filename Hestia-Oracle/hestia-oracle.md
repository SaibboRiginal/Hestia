# Hestia-Oracle 🧠

**Role:** AI Chat Interface — Conversational Layer
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

The conversational AI brain of Hestia. Receives messages from interface services (e.g. Telegram), maintains chat sessions, routes queries to the correct data domain via Archive, and returns intelligent responses. Abstracts the underlying LLM provider behind a universal connector.

---

## Core Features

### Universal LLM Connector — providers, chains, use cases (dossier `docs/work/2026-10-19-oracle-a-blocchi`)
Three object settings (Themis, live; edited in WebUI → Oracle → **Cervello → Modelli**):
- **Providers** `oracle.providers` = `{name: {type, label, url}}`. Type = the standard it speaks: `ollama`,
  `openai` (any OpenAI-compatible server: llama-server, vLLM, DeepSeek, OpenRouter), `anthropic` (Anthropic API or a
  compatible endpoint), `gemini`, `claude_cli` (Claude subscription through the `claude` CLI). Defaults: `ollama`
  (address from infra `OLLAMA_URL`), `llamacpp` (llama-server `http://host.docker.internal:8080/v1`), `gemini`,
  `deepseek`, `claude-api`, `claude`. **Keys only in env** as `ORACLE_KEY_<NAME>` (upper-case, non-alphanumerics → `_`,
  e.g. `ORACLE_KEY_CLAUDE_API`); a cloud provider without its key, or `claude` without a login, is skipped.
  Code: `core/services/llm_providers.py`; one class per type in `app/agents/providers/`, config dict in, no env reads.
- **Chains** `oracle.chains` = `{name: {label, steps: [{provider, model, thinking?}]}}`, reusable like a CSS
  font-family: the first usable step answers; a **quota** error (429, `RESOURCE_EXHAUSTED`, «quota», «usage limit»)
  marks that provider/model pair exhausted until its reset (Retry-After, `retryDelay`, midnight Pacific for Gemini per-day
  quotas, else `oracle.quota.cooldown_minutes` = 60) and every chain skips it until then; any other error just moves
  to the next step. All steps failing → `ChainExhausted` (503 on `/api/llm/generate`). Defaults: `veloce`, `potente`,
  `codice`, `visione`, `embedding` (one model only: vectors must stay comparable). Code: `core/services/llm_chains.py`.
- **Use cases** `oracle.usecases` = `{use case: {chain, mode, thinking}}` overrides. Oracle's own: `oracle.generale`
  (chat, classify, tools, memory, format), `oracle.ragionamento`, `oracle.codice`, `oracle.documenti` (vision),
  `oracle.embedding`. Modules **declare** theirs in the Hub registration (`capabilities.llm_usecases`, helper
  `hestia_common.oracle_usecases`): `scout.annunci`, `athena.strategia`, `athena.revisione`, `argus.analisi`,
  `chronos.agenda`, `wardrobe.foto`, `forge.codice`… with a suggested chain; Marko picks chain/mode/thinking in one
  place. A use case nobody declared runs like `oracle.generale` and is listed as «non dichiarato».
- `ChainAgent` (same interface as `UniversalAgent`) walks the chain at every call, reading settings live (no restart,
  no reconfigure); `AgentFactory.create()` builds one per Oracle use case (`generic`, `reasoning`, `code`,
  `documents`, `embedding` slots). Streams fall back only before the first token.
- One-time migration: old `oracle.models.*` values (before 2026-10-19) become chains `<use case>-personale` when neither
  `oracle.chains` nor `oracle.usecases` was ever stored (`core/services/llm_migration.py`).
- Claude Code for Forge (`/api/llm/code`) uses the first `claude_cli` step of use case `forge.codice` (none → CLI default).
- `UniversalAgent.ask_with_attachment(file_bytes, mime_type, user_message)` enables multimodal reasoning over images and PDFs (see Multimodal below).

### Brain mode: interna / esterna (§D)
- `oracle.brain.mode` = `interna` (default: classifier, Rapida/Pensata/CoT, agent loop, chains) or `esterna`: an agent
  CLI runs the tool loop — `oracle.brain.agent` = `claude` (Claude Code, subscription login `CLAUDE_CODE_OAUTH_TOKEN`)
  or `codex` (Codex, `codex login`, image built with `ORACLE_INSTALL_CODEX=1`, login mounted in `/root/.codex`),
  `oracle.brain.model` (e.g. `sonnet`), `oracle.brain.fallback` = `interna` (redo the turn with the chains) or `nessuno`.
  A use case can override the mode (Modelli).
- In esterna Oracle keeps the door work: history, classification (domain filter), context, tools, saving to Archive,
  memory, usage rows; quick shortcuts are skipped (the agent answers every turn). Code: `core/services/external_agent.py`.
- Tools: the CLI starts `python -m core.services.mcp_bridge` (stdio MCP, standard library only), which forwards
  `tools/list` / `tools/call` to Oracle's loopback `/api/agent-bridge/<token>` (one random token per turn, loopback only):
  the same tool handlers, approval gate, logs and Hub routing as the internal loop. Built-in file/shell tools stay off.
- Sessions: Archive is the source of truth; the agent session id is an in-memory cache keyed by (session, agent, model),
  dropped when a turn of that session is answered in interna. A new agent session is primed with Oracle's context.
- `/api/llm/generate` of a use case in esterna asks the agent one shot without tools.

### Usage rows (§E)
Every LLM call (chain step, Forge chat, external agent, Claude Code) becomes one row pushed to Archive store
`llm-usage` (one background worker started by the first row, batches of 200, a failed send is dropped): time, module
(prefix of the use case), client and session, use case, chain, step, provider, model, tokens in/cached/out, context window,
duration, cost and kind (`api` reported or from `oracle.pricing`, `abbonamento`, `locale`, `sconosciuto`), outcome
(`ok`/`quota`/`error`). Archive deletes rows older than `oracle.usage.retention_days` (90) on each write.
`GET /api/llm/usage` sums them. Code: `core/services/llm_usage.py`; `llm_stats` keeps the in-memory live gauge.

### Personal chat settings (Themis, scope user)
- `oracle.chat.tone` (warm · neutral · direct · formal) and `oracle.chat.instructions` (text) are declared by
  Oracle and shared by every client. Resolution: session → client → profile (your defaults) → default.
- Clients send `"client": "<name>"` in `/api/chat`, `/api/chat/document[/json]` and `/api/format`; Oracle appends
  the resolved sentences to the client instructions (`main._with_personal_settings`, values cached 20 s by
  `SettingsClient.user_values`; Themis down → defaults). Clients no longer send tone lines themselves.
- `oracle.chat.mode` (auto · quick «Rapida» · thinking «Pensata» · cot «CoT») is the conversation mode, same
  layers. `/api/chat` with an empty `mode` uses it (`oracle_settings.chat_mode`); an explicit mode wins
  (WebUI composer sends it and saves it for the conversation; Telegram `/settings` → Modalità).

### Session Management
- Each interface (e.g. Telegram) has one active session at a time.
- Sessions store the full conversation history.
- Sessions are persisted to and retrieved from **Archive** (`user` domain) — Oracle holds no local state.
- Sessions can be cleared via an explicit command (triggered by the interface service).

### Temporal Context Awareness
- Every chat turn injects explicit current date/time context (timezone-aware) into routing and analysis prompts.
- Relative temporal expressions such as "oggi", "domani", and "la prossima settimana" are resolved against that context before planning/tool reasoning.
- Timezone = container `TZ` (infrastructure, same as every module; default `Europe/Rome`).
- Today's agenda from Chronos is added to the context when `oracle.context.today_agenda` is on (default).

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

### Chat attachment hand-off to modules (`core/document/handoff.py`, 2026-10-19)
Generic: Oracle knows no domain. A module declares in its Hub capabilities
`attachment_handlers: [{mime: [...], match: [...], min_hits (default 2), path, label}]` (Plutus: bank statement PDFs).
In `analyser.py`, before the normal analysis (not for audio/video), Oracle extracts the text (PDF/text) and picks
the first handler whose `mime` fits and whose `match` words appear in the user's message (any) or in the text
(≥ `min_hits`). On a match it stores the file in Archive blobs (`owner_module=chat`, meta name/session/for) and calls
`POST route/<module>/<path> {blob_id, filename, mime, message, session_id}`. The module answers `{handled, text, …}`:
that text is the chat reply (saved in history, so a following «sì» reaches the module's tools with the ids it
carries), plus signal `attachment_handled`; the file is not copied into the RAG archive. No match, module declines
or any error → `[🔄]` and the usual document analysis (nothing lost). Handlers list cached 60 s.

### Retrieval Strategy
- Oracle invokes module tools via a generic endpoint (`POST /api/module-tools/query`) using domain + query + routing metadata.
- Modules interpret domain-specific filters/preferences internally.
- If no module tool responds, Oracle falls back to Archive `/api/entities/search`.
- Context sent to the analyst model is compacted to avoid context bloat.

### Athena Advisory Hints
- Oracle can ingest Athena advisory hints through `POST /api/athena/hints`.
- Hints are advisory-only context and do not bypass Oracle action execution contracts.
- Chat/planner prompt assembly can include relevant non-expired hints for the active session and domain.
- Settings `oracle.hints.enabled` (on), `oracle.hints.ttl` (7200 s), `oracle.hints.max` (300).

### Prompt Variant Gating (A/B)
- Planner and alert formatter prompts support settings-gated variant selection:
  `oracle.prompt_ab.{alert,planner}.{enabled,variants,default,force}` (off, `control,experimental`, `control`, "").
- Deterministic variant selection uses a stable bucketing seed (`session_id`, command/trace context, fixed salt).
- Selected variant IDs are logged for regression and quality comparisons.

### Agentic Tool Calling (Unified)
- All tool execution flows through a single ReAct-style agent loop (`core/agent_loop.py`).
- A single tool manifest is built per turn: domain search tools + all Hub-discovered commands + memory tools.
- The LLM decides which tools to call and in what order — no separate pre-check or heuristic routing.
- **Max agent turns:** setting `oracle.agent.max_turns` (default 25; CoT uses at least 50). Complex multi-step tasks can use many turns; simple tasks exit early (1-2 turns).
- **Early exit:** when the LLM produces text without tool calls for `oracle.agent.early_exit_no_tool_turns` (2) consecutive turns after having already called tools, the loop terminates.

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
- `core/document/analyser.py` + `handoff.py`: document chat path; attachment hand-off to modules (above).

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Send a message, receive NDJSON stream |
| `POST` | `/api/chat/document` | Send a file + optional message, receive NDJSON stream |
| `POST` | `/api/format` | Format a structured payload into human-readable text |
| `POST` | `/api/subscriptions/compile` | Compile a notification subscription from natural language |
| `POST` | `/api/llm/generate` | Plain generation for services `{prompt, use_case?}` — the use case's chain (default `oracle.generale`; esterna → external agent one shot) → `{response, model, provider, use_case, chain}`; every step failing → 503 |
| `GET` | `/api/llm/models?provider=` | Model choices of a named provider (Ollama installed models, Gemini curated list, Anthropic Models API, OpenAI-compatible `/models`, Claude CLI haiku/sonnet/opus) → `{options:[{value,label}]}` |
| `GET` | `/api/llm/providers` | Named providers: type, address, `key_env`, `key_set`, available, exhausted models (never a key) |
| `GET` | `/api/llm/chains` | Chains with each step's state (available, out of quota until) |
| `GET` | `/api/llm/usecases` · `/api/llm/usecases/{id}` | Every use case (Oracle's, declared by modules, undeclared seen) with effective chain/mode/thinking · what one would use now (first usable step, window, billed) — Forge engine `oracle` |
| `GET` | `/api/llm/usage?group=module\|session\|usecase\|model\|step\|day&days=&module=&session_id=&use_case=` | Sums of the usage rows kept in Archive |
| `GET` | `/api/llm/usage/calls?session_id=&days=&limit=` | Latest single calls (detail of a session) |
| `GET` · `POST` | `/api/agent-bridge/{token}/tools` · `/call` | Loopback only: tools of the external agent's running turn (stdio MCP bridge) |
| `GET` | `/api/settings/effective` · `POST /api/settings/reload` | Central settings: effective values / reload (called by Themis) |
| `POST` | `/api/athena/hints` | Ingest Athena advisory hint payload |
| `GET` | `/api/athena/hints` | List non-expired Athena hints (optional `session_id`) |
| `DELETE` | `/api/chat/{session_id}` | Clear a session |
| `GET` | `/api/chat/context?session_id=` | Context-window stats (token breakdown, compaction availability) |
| `POST` | `/api/chat/compact?session_id=` | Force-compact conversation history via LLM summarisation |
| `GET` | `/api/sessions` | Global Oracle state (models, uptime, Hub URL) |
| `GET` | `/api/ui/manifest` · `/ui/webui/oracle.js` | WebUI plugin manifest and bundle (see «WebUI plugin: Cervello») |
| `GET` | `/api/ui/activity?limit=` | Recent chat turns, newest first (route, domains, tools ok/failed, model/provider, ms, LLM usage of the turn) + last user activity |
| `GET` | `/api/ui/stats?days=` | LLM use: tokens/cost per day (≤31), today per use case × provider × model, rolling averages per use case |
| `GET` | `/api/ui/code` | Claude Code status (`/api/llm/code/status`) + recent runs (`running`, `runs[]`: task folder, state, ok, ms, turns, cost) |
| `GET` | `/api/ui/models` · `/api/ui/models/list?provider=` | Tab Modelli: providers (no keys), standards, chains with step state, use cases, overrides, modes · model names of a provider |
| `PUT` | `/api/ui/models/{providers\|chains\|usecases}` | `{value}` → stored through Themis (actor user); 400 invalid, 502 Themis refused |
| `POST` | `/api/ui/models/quota/reset?provider=&model=` | «Riprova adesso»: forget a quota state |
| `GET` | `/api/ui/usage` · `/api/ui/usage/calls` | Tab Uso: same as `/api/llm/usage` · `/api/llm/usage/calls` |
| `GET` | `/api/ui/documents?limit=&domain=&permanent=` | Documenti page: documents from Archive (via Hub) `{documents, count, domains}`; Archive down → 502 |
| `GET` | `/api/ui/documents/search?query=&limit=` | Semantic search over passages (same as the chat, threshold `oracle.documents.search_threshold`) |
| `POST` | `/api/ui/documents` | Add a file `{name, mime, data_b64}` → `{status: ingesting, document_id}`; archiving (extract → chunks → embeddings → Archive) runs in background, session `webui-documenti`; 415 type, 413 too big |
| `PATCH` | `/api/ui/documents/{id}/permanent` | `{is_permanent}`: keep for good (never pruned) or temporary |
| `DELETE` | `/api/ui/documents/{id}` | Delete document and passages (404 unknown) |
| `GET` | `/health` | Service health |

### Module tools (agent loop)

Oracle is an ordinary client of Hestia's one MCP server: `_build_domain_tools` lists tools with
`hestia_common.mcp_client.MCPClient(client="oracle")` (it sees all and keeps only the domain owners' tools) and every
call goes through `tools/call` (session id, notify target, trace id; the session's client as `X-Hestia-Client`, timeout
`action_service_route`). Hestia-MCP fills templates and routes through Hub; Oracle no longer has its own resolver.
Oracle's own tools (memory, documents, session info, logs) stay in-process.

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
| `thinking` (Pensata) | True | Yes, no quick-chat shortcut | Always agent loop, model reasoning on |
| `cot` (CoT) | "deep" | Yes, no quick-chat shortcut | Deep reasoning, ≥50 turns, prompt line asking a step-by-step plan and a «Passi:» recap |
| `""` | — | — | Use the setting `oracle.chat.mode` (session → client → profile) |

Mode and model are independent — any mode works with any use case (`generic`/`reasoning`/`code` slots).
Model names come from the chains (`oracle.chains`) — no hardcoded models outside the declared defaults. In brain mode
esterna the external agent answers every turn (no quick shortcut).

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
- `{"type":"notice","kind":"memory.saved","level":"success","icon":"memory","emoji":"💾","title":"Ricordato","detail":"..."}` — **standard system message** for the user (memory saved/removed, write actions done/failed, subscriptions, documents). Every user-facing signal also emits its notice twin; write tools (`ToolDefinition.writes`) emit `action.done|failed` (successful `agenda_assistente*` writes → `agenda.planned`, `forge_develop` → `forge.task`, so WebUI pages reload live). Analyst rule 8: no tool can do it → propose a Forge task (new MCP tool / agenda template), ask, then `forge_develop` with `agenda_parent` when an agenda item is involved. Background-memory notices arrive after `final` (waits up to setting `oracle.memory.notice_wait`, default 8 s). Spec: `Hestia-Shared/hestia-shared.md` § Response packets.
- `{"type":"question","question_id":"...","header":"...","prompt":"...","kind":"...","options":[...]}` — interactive approval prompts. A module tool result with `confirm {question_id, header, prompt, options, actions}` (Themis proposal made in this chat) is emitted as a `kind: confirm` question after `final`; `POST /api/chat/question-answer` then routes `actions[answer]` through Hub (`"<client>"` in the body → answering client) and returns `{resolved, action: {ok, result}}`. Oracle sends `X-Hestia-Client` (the session's client from `ChatRequest.client`) with `X-Session-Id` on every tool call.

This makes UI behavior standardized: Telegram, web app, mobile app, or voice UI can all render the same lifecycle and user notifications.

---

## Settings (Themis, all live)

Declared in `app/core/services/oracle_settings.py`, read at use time (no restart). Env keeps only infrastructure:
endpoints/keys (`OLLAMA_URL`, provider keys `ORACLE_KEY_<NAME>`, `CLAUDE_CODE_OAUTH_TOKEN`), binaries/paths
(`ORACLE_CLAUDE_BIN`, `ORACLE_CODEX_BIN`, `ORACLE_CODE_WORKDIR_ROOT`, `ORACLE_PROMPTS_FILE`, `ORACLE_UI_DIST` — WebUI bundle, set in the Dockerfile),
`ORACLE_EMBED_DIM` (tied to Archive `Vector(768)`), `TZ`, Hub/Archive URLs, `MODULE_TOOLS_URL(S)`, version,
`ORACLE_NOTIFY_DEFAULT_TARGET` (identity of the owner). Prompt text (persona, action-tool policy) is in the prompt
map (`agent_action_tool_policy`, overridable in the prompts file), not env.

| Group | Keys (default) |
|---|---|
| Modelli | `oracle.providers`, `oracle.chains`, `oracle.usecases` (object, editor Cervello → Modelli), `oracle.quota.cooldown_minutes` (60), `oracle.brain.mode` (interna), `.agent` (claude), `.model` (sonnet), `.fallback` (interna) |
| Uso | `oracle.usage.retention_days` (90), `oracle.pricing` (`{"provider/model": {in, out, cached}}` $ per Mtok, `{}`) |
| Agente | `oracle.agent.max_turns` (25), `.max_tokens` (0 = no limit), `.tool_result_max_chars` (2000), `.early_exit_no_tool_turns` (2), `.max_parallel_tools` (8) |
| Contesto | `oracle.context.history_messages` (6), `.history_message_chars` (500), `.entities` (12), `.entity_field_chars` (280), `.compact_trigger_messages` (20), `.compact_keep_recent` (6), `.today_agenda` (on); `oracle.provider.ollama.tool_call_mode` (auto/native/text), `.thinking_families` (gemma4, gemma3, qwen3…) |
| Tempi | `oracle.timeouts.{foreground_chat 8, action_selection 12, action_service_route 25, memory_extraction 10, background_compaction 8, notification_formatting 12, gateway_chat 600}` s; `oracle.provider.ollama.timeout` (120 s), `.embed_timeout` (60 s); `oracle.provider.retries` (3), `.retry_delay` (1.0 s, doubles) |
| Memoria | `oracle.memory.notice_wait` (8 s), `.domain_threshold` (0.55), `.preference_domains` (name → description, re-embedded on change), `.force_owner_target` (on); `oracle.hints.*` |
| Conferme | `oracle.approval.enabled` (on), `.ttl` (600 s), `.bulk_min_count` (2), `.methods` (DELETE, PUT, PATCH), `.commands` ([]) — the assistant may only read them |
| Documenti | `oracle.documents.max_archive_mb` (10), `.search_threshold` (1.2), `.whisper_model` (base, reloaded on change), `.vision_models`, `.audio_models` (prefix lists) |
| Esperimenti | `oracle.prompt_ab.*` (above) |
| Diagnostica | `oracle.cache.schemas_ttl` (30 s), `.tool_registry_ttl` (120 s), `oracle.tasks.max_kept` (500), `oracle.log.level` |

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
| POST | `/api/llm/chat` | OpenAI-compatible chat along a use case's chain: `{use_case?, messages, tools?, temperature?, max_tokens?, tool_choice?}` (default `forge.codice`) → provider JSON + `hestia_step` (use case, chain, step, provider, model) |
| POST | `/api/llm/generate` | Plain prompt `{prompt, use_case?}` → `{response, model, provider, use_case, chain}` (Athena, Scout, Argus, Chronos, Metis) |
| GET | `/api/llm/usecases/{id}` | What a chat on that use case would use now: first usable step, `context_window`, `billed` (Forge engine `oracle`) |
| GET | `/api/llm/code/status` | Claude Code ready? (CLI installed, token, worktree root mounted) |
| POST | `/api/llm/code` | "code" use case: run Claude Code (Pro/Max) in a Forge worktree `{workdir, prompt, append_system_prompt, max_turns, timeout_seconds}` → `{ok, summary, turns, cost_usd, transcript_path}`. Runs `claude -p --output-format stream-json --verbose`; every line is written live to `<ORACLE_CODE_WORKDIR_ROOT>/.transcripts/<task>.jsonl` (outside the worktree) for the WebUI Sviluppo page |

`/api/llm/chat` walks the chain like every other call (quota skip, next step on error). An Ollama step is served
through Ollama's native `/api/chat` with the same `num_ctx` + `keep_alive` as every other Oracle call (Ollama's `/v1`
ignores `num_ctx`: long Forge prompts were cut silently); request/response are translated to the OpenAI shape
(`reasoning_content`, `tool_calls`, `finish_reason=length` when the window is full). Other steps go to the provider's
OpenAI-compatible endpoint (Gemini `…/v1beta/openai`, Anthropic `…/v1`, any `openai` provider) with its
`ORACLE_KEY_<NAME>`. Timeout per call: setting `oracle.timeouts.gateway_chat` (600 s). Used by Forge engine `oracle`.

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
  your PC, sign in with the Pro account) in `Hestia-Oracle/app/.env`. Model: the first `claude_cli` step of use
  case `forge.codice` (none = CLI default).
- Code tasks run inside `ORACLE_CODE_WORKDIR_ROOT` (`/forge/worktrees`, shared with Hephaestus). The CLI never sees
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or any `ORACLE_KEY_*` (`agents.llm_config.cli_env`).

### Claude for chat (provider types `anthropic` and `claude_cli`)

Put them as steps of a chain (Cervello → Modelli); skipped while not configured.
- **`anthropic` — default provider `claude-api` "Claude (chiave API)"**: official `anthropic` SDK, key
  `ORACLE_KEY_CLAUDE_API` (never `ANTHROPIC_API_KEY`, which would switch Forge's Claude Code to paid API billing); its
  address can point at any Anthropic-compatible endpoint (e.g. DeepSeek's).
  Native tools (the domain-filtered list built by Oracle), prompt caching on system prompt, tool list and the static
  part of the agent-loop prompt (`SYSTEM_PROMPT_DYNAMIC_BOUNDARY`), images/PDF natively. Log `event=anthropic_usage`
  (input/output/cache_read/cache_write tokens).
- **`claude_cli` — "Claude (abbonamento)"**: the subscription through `claude -p --output-format json` (same
  `CLAUDE_CODE_OAUTH_TOKEN` as Forge; models `haiku`/`sonnet`/`opus`). One CLI start per call (slower), usage
  limits shared with Forge; Anthropic's terms meant subscription login for ordinary Claude Code use, so this is a
  personal-use grey area chosen knowingly. Claude Code's tools are off (`--tools ""`, `--strict-mcp-config`, empty
  cwd); Oracle's loop stays in charge: the filtered tools are written in the prompt and Claude answers
  `<tool_call>{"name","params"}</tool_call>` blocks, parsed into tool calls. API keys are stripped from its env.
- **Thinking**: chat mode quick → off, auto/thinking → low (CLI: medium), cot → high effort; the use-case setting
  `thinking = false` keeps it off. Claude's summarized reasoning is shown as `reasoning_content` (CoT also adds
  one prompt line asking a short «Passi:» recap). No embeddings on these providers.

### Local models: real context window, prompt cache, OpenAI-compatible servers

Dossier `docs/work/2026-10-10-oracle-local-context/`. Settings group **Contesto** (Themis, no env):
- `oracle.provider.ollama.num_ctx` (8192) and `oracle.provider.ollama.keep_alive` (`30m`, `always` = -1) are sent
  on **every** Ollama call (generate, chat/tools, stream, vision; embeddings get keep_alive only). Before, Ollama ran
  at its server default (often 4096) and silently cut the start of longer prompts. The same value drives
  `TokenCounter`, `/api/chat/context` and auto-compaction (`oracle.context.compact_threshold`, 0.8). Startup logs
  `event=ollama_context_config` and warns `ollama_context_smaller` when `/api/ps` shows a model loaded smaller.
- **Telemetry**: every call logs `event=llm_call_stats agent=<use case> prompt_tokens cached_tokens cache_hit_pct
  load_ms prompt_ms output_tokens tok_per_s`; `/api/chat/context` returns `runtime` = per-agent averages of the
  last 50 calls. Ollama reports only the tokens it had to evaluate (`prompt_eval_count`), so its cache share is an
  estimate (`cache_estimated: true`); OpenAI-compatible servers report it (`usage.prompt_tokens_details.cached_tokens`,
  llama-server `timings.cache_n`). Gemini (`usage_metadata`), Anthropic API and Claude CLI (`usage`, CLI
  `total_cost_usd` = API-equivalent cost) are recorded too.
- **Per-conversation usage** (2026-10-11, dossier `docs/work/2026-10-11-chat-modalita-contesto/`): `/api/chat`
  binds its session id around the stream (`llm_stats.bind_session`, a contextvar set at every `next()`), so each
  LLM call of the turn adds to that session's totals (in memory, last 200 conversations, reset on restart).
  `/api/chat/context` adds `active` (chat provider: label, model, billing kind, its context window —
  `CONTEXT_WINDOW`/`BILLING` on provider classes, `agents.providers.runtime_info`) and `session_usage`; the
  used % is the last real prompt of the conversation when measured, else the estimate. WebUI shows it in the
  chat header gauge.
- **Cache-friendly prompts**: the model server reuses the KV cache only for a byte-identical prefix. Agent-loop tools
  are sorted by name; the per-request ACTION INTENT hint moved after the user message (dynamic part); the history
  window grows from a fixed first message up to N + N/2 messages and then jumps to the last N
  (`ContextBuilder.stable_window`, per session, in memory) instead of sliding every turn.
- **Context editing**: when a loop prompt passes 50 % of the window, tool results older than
  `oracle.context.tool_result_stub_after_turns` (2, 0 = off) become a one-line stub (no LLM call).
- **Type `openai`** — "Compatibile OpenAI" (llama-server, vLLM, DeepSeek, OpenRouter): address in the provider
  (`…/v1`, default `llamacpp` = `http://host.docker.internal:8080/v1`), optional key `ORACLE_KEY_<NAME>`. Static prompt
  part goes in the system message; `cache_prompt` (setting `oracle.provider.openai.cache_prompt`) for llama-server;
  quick mode sends `chat_template_kwargs.enable_thinking=false`; native tools, SSE stream, images, `/embeddings`.

Host tips (Ollama env on the PC, infrastructure, not managed by Hestia): `OLLAMA_FLASH_ATTENTION=1` +
`OLLAMA_KV_CACHE_TYPE=q8_0` (about half the KV memory → bigger context in the same VRAM); `OLLAMA_NUM_PARALLEL=2`
gives the classifier/memory calls their own slot so they stop evicting the chat prefix (costs VRAM per slot);
`OLLAMA_CONTEXT_LENGTH` = the same num_ctx for any client that uses Ollama's `/v1` endpoint directly (no per-request
num_ctx there). llama-server example: `llama-server -m model.gguf -c 16384 -fa --cache-reuse 256
--port 8080` (+ `-md draft.gguf` for speculative decoding); vLLM: `vllm serve <model> --enable-prefix-caching`.

## Claude Code / Codex CLIs in the image

Claude Code CLI is installed by default (`ORACLE_INSTALL_CLAUDE_CODE=0` for a slimmer image) and used only when
`CLAUDE_CODE_OAUTH_TOKEN` is set; Codex only with `ORACLE_INSTALL_CODEX=1` (external brain mode, `codex login`).

## WebUI plugin: Cervello (core module, Sistema section)

Oracle ships its inside view on the client plugin contract (`hestia_common.plugin_client`, `kind="core"`; SPEC
`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2). Declared in `app/main.py`, bundle `ui/` (Lit, SDK kit) built in
the Docker image (Node stage → `/ui/dist/webui/oracle.js`, outside `/code` because of the dev mount; infra env
`ORACLE_UI_DIST`). `api_prefix` = `/api/ui/` (Oracle's routes are spread over several prefixes, so the page reads three
small `/api/ui/*` views instead of calling them directly). The Hub registration carries `ui_manifest`/`ui_version`.

| Kind | Id | What |
|---|---|---|
| page (order 120) | `cervello` → `<oracle-brain>` | Tabs **Attività** · **Uso** (`<oracle-usage>`: rows from Archive per module — calls, calls/hour, tokens, cache %, largest prompt vs window, avg time, cost, fallbacks/errors/quota —, calls per day, conversations → their calls, which chain step answered) · **Modelli** (`<oracle-models>`: use cases by module → chain/mode/thinking, chains with steps ↑↓, model picker, quota badge + «Riprova adesso», providers with standard, address and key status; saves through Themis). Attività: KPIs of today, last 40 turns (route rapida/conversazione/agente, client, domains, tools — failed in red, writes in amber —, provider · model, ms, calls/tokens/cost of the turn), tokens per day (14 d) + cost line, today per use case/model, rolling stats per use case (prompt size, cache hit, token/s, load), Claude Code (ready or why not, runs). Auto-refresh 30 s; Oracle down → «Oracle non raggiungibile» |
| widget | `uso-oggi` → `<oracle-usage-widget>` (s/m/l) | «Uso modelli oggi»: calls, tokens, cost, top models; opens Cervello |
| page (order 121) | `documenti` → `<oracle-documents>` | Ported from the built-in WebUI page (SPEC §A4). Documents in Archive (title, file, type, size, passages, uses, summary, domain, tags), domain chips, semantic search (the chat's `DocumentRAG`, passages with distance), *Aggiungi file* (SDK `host.upload`, ≤ 8 MB from the browser and ≤ `oracle.documents.max_archive_mb`; archived in background like a chat attachment, the page polls until it appears), *Tieni per sempre* / temporaneo, delete, *Chiedi a Hestia*. Oracle/Archive down → «Oracle non raggiungibile» |

Data sources of the Attività tab (all in memory, reset when Oracle restarts — an inside view, not an audit log; the
Uso tab reads the rows kept in Archive):
- `core/services/activity_log.py` — ring of the last 200 finished chat turns, written at the three `chat_done_summary`
  points of `OracleEngine.chat` (the turn's usage = delta of `llm_stats.session_usage`). Message preview ≤ 80 chars.
- `core/services/llm_stats.py` — besides the rolling window per use case, daily totals per (use case, provider, model)
  for the last 31 local days (`daily()`).
- `core/services/claude_code_runner.py` — last 20 runs (`runs()`); a finished run with `usage` also goes into the daily
  totals as use case `claude_code`.

## Assistant presence

Every chat (text and document) pings Chronos presence (`oracle`, forced) and reads the state from before the ping: if `chronos.presence.oracle_context_line` is on, the system prompt gets one line (state, last interaction, notice) and «Rispondi breve.» when `chat.style=brief`. Code: `app/core/services/oracle_presence.py`.
