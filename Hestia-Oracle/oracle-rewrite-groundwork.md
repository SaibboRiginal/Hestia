# Oracle Rewrite — Groundwork Analysis
*Prepared ahead of the full Oracle rewrite session.*

---

## 1. Current State — What Works & What Doesn't

### Architecture that is worth keeping
| Component | Verdict | Reason |
|---|---|---|
| `UniversalAgent` provider abstraction | **Keep, extend** | Clean enough; needs streaming + multimodal |
| Four named LLM roles (router, scribe, analyst, embedder) | **Keep** | Good separation of concerns |
| Hub-proxied Archive access | **Keep** | Required by architectural contract |
| NDJSON streaming protocol | **Keep, improve** | Right idea; actual LLM stream is missing |
| `ModuleToolRegistry` (dynamic discovery) | **Keep, refactor** | Logic is sound; TTL caching is correct |
| `MemoryService` preference/subscription extraction | **Keep, harden** | Works; grounding + dedup logic is valuable |
| `ContextBuilder` compaction | **Extend** | Good but static; needs dynamic compression |

### Tech debt to eliminate in the rewrite
1. **`database_client.py`** — dead artifact, never imported, opens direct Postgres connections in violation of the "no direct DB" contract. **Delete.**
2. **`router_service.py`** — instantiated but never called; routing logic duplicated inline in `oracle_engine.py`. **Delete; inline is fine.**
3. **`agent.complete()` bug** — `main.py` calls `agent.complete(prompt)` on `UniversalAgent` which only defines `ask()` and `embed()`. The `/api/llm/generate` endpoint will crash at runtime. **Fix in rewrite.**
4. **Blocking LLM calls** — `ask()` is fully synchronous. The NDJSON stream sends status frames but the LLM response arrives as one big chunk. Users see a spinner, then the full reply. **Replace with true async/streaming LLM calls.**
5. **Memory extraction blocks stream completion** — `MemoryService.extract_and_save_preferences()` runs synchronously after `_emit_final`, delaying the stream close by 2–8s. **Move to background task (asyncio or thread).**
6. **`_has_explicit_preference_intent` / `_has_explicit_notification_intent`** — hardcoded Italian+English keyword lists. Fragile. **Replace with a lightweight router-LLM classification call (the router is already there for this).**
7. **No auth on any endpoint** — not blocking for local use, but needs a plan for any external exposure.
8. **No retry logic** — each LLM call is `try: primary / except: fallback`. No exponential backoff, no circuit breaker.

---

## 2. The Agentic Loop — What to Build Toward

### Current Oracle loop (simplified)
```
User message
  → Router LLM (classify intent)
  → [quick_chat] Analyst LLM (direct answer)
  → [domain_query] Module Tool query → Analyst LLM (answer with context)
  → Scribe LLM (async preferences/subscriptions)
  → Done
```
Single-shot. No tool-calling. No multi-step reasoning. Oracle cannot ask a tool for more information mid-answer.

### Target: Structured Agentic Loop (ReAct/ToolCall pattern)
```
User message + tools manifest
  → LLM: reason + optionally emit tool_call
  → Tool execution (module-tools, calendar, web fetch, memory, etc.)
  → LLM: continue reasoning with tool result
  → … (up to N turns)
  → LLM: final answer
```
Each iteration is a separate streaming LLM call. The result of every tool call is fed back into the next LLM turn as a "tool result" message.

### Key design principles for the agentic loop
1. **Tool manifest is dynamic** — assembled at request time by querying Hub discovery (module-tools, calendar, etc.). Oracle never hardcodes tool names.
2. **Tool result injection** — each tool result is injected as a `role: tool` message in the chat history for the current session turn (not persisted, ephemeral scratchpad).
3. **Max-turn guard** — infinite loops are prevented by a configurable `MAX_AGENT_TURNS` (default: 6).
4. **Streaming through turns** — stream status/reasoning frames per turn; stream final answer tokens as they arrive from the LLM.
5. **Graceful degradation** — if a tool call fails, the LLM is told so and continues without it.

---

## 3. Context Management — Patterns to Adopt

### Problem: context windows fill up fast
- Chat history grows unbounded per session.
- Long entity lists eat tokens.
- Tool results can be verbose.

### Techniques to implement

#### 3a. Sliding-window + summarisation (priority)
Instead of dropping old messages at a hard cutoff, periodically summarise the oldest segment of the conversation into a "memory snapshot" message that stays in context.
- Trigger: when `len(history_tokens) > CONTEXT_COMPRESS_THRESHOLD`
- Action: Scribe LLM produces a short bullet summary of the oldest N messages → replaces them with a single `role: system` snapshot message.
- Persist the snapshot in Archive as a session artefact so it survives restarts.

#### 3b. Hierarchical entity compaction (already partially in `ContextBuilder`)
- Full entity → compact representation (title, price, address, status) for initial context.
- If user references a specific entity → fetch full payload and inject only that one.
- Never dump all entities at full verbosity.

#### 3c. Tool result truncation with pointer
- If a tool result exceeds N tokens, truncate and add a pointer: `[…full result available on request via entity_id=X]`.
- LLM can emit a follow-up tool call to fetch the full record if needed.

#### 3d. Preference injection (already done)
- Active preferences are loaded once per session turn and injected as a system block.
- Keep this; add a token budget guard.

---

## 4. True Streaming — What Needs to Change

### Current: pseudo-streaming
`UniversalAgent.ask()` does a blocking call (`client.models.generate_content(...)`) and returns the full text at once. The NDJSON frames are synthesised status updates, not real token streams.

### Target: token-level streaming
**Gemini SDK**: `client.models.generate_content_stream(...)` returns an iterator of `GenerateContentResponse` chunks. Each chunk has `.text` with incremental tokens.

**Ollama HTTP**: `/api/generate` with `"stream": true` returns NDJSON where each line is a token chunk. Parse with `response.iter_lines()`.

### Required refactor in `UniversalAgent`
- Add `ask_stream(user_message) → Iterator[str]` method that yields token strings.
- `ask()` becomes a convenience wrapper that joins the stream.
- `oracle_engine.py` uses `ask_stream()` for the analyst, yielding each chunk as an NDJSON `token` frame to the Telegram/client consumer.

---

## 5. Multimodal Input — Required for Calendar Feature

Oracle needs to accept and reason over attached documents (PDF, images) — specifically for the "extract event from attached document" use case.

### Plan
1. **API layer** (`main.py`): accept `multipart/form-data` with optional `file` field alongside the `message` text.
2. **UniversalAgent**: new `ask_with_attachment(user_message, file_bytes, mime_type) → str` method.
   - Gemini: use `types.Part.from_bytes(data=file_bytes, mime_type=mime_type)` in the content list.
   - Ollama: use models with vision capability (e.g. `llava`, or gemma4 with vision); pass image as base64 in the `images` field. PDFs must be pre-converted to text (via `pypdf`) or rendered to images first.
3. **PDF handling**: extract text with `pypdf` (pure Python, no system deps). If text extraction yields < 100 chars (scanned PDF), fall back to rendering page 1 as a PNG and using the vision path.
4. **MIME routing**: `application/pdf` → pypdf text extraction → LLM; `image/*` → direct vision; everything else → reject with a clear error.

---

## 6. Tool Protocol — Formalising What Oracle Calls

Currently, module-tool calls are done ad hoc in `ModuleToolRegistry.query()` with a custom JSON schema. The agentic loop needs a formal tool definition protocol.

### Proposed tool definition format (internal to Oracle)
```python
@dataclass
class ToolDefinition:
    name: str               # e.g. "real_estate.search"
    description: str        # shown to LLM in tool manifest
    parameters: dict        # JSON Schema for LLM to fill
    handler: Callable       # async function that executes the tool
```

### Tool categories to wire up
| Tool | Source | Notes |
|---|---|---|
| `memory.search_preferences` | Archive via Hub | Load active prefs for domain |
| `{domain}.search` | Module-tools via Hub | Existing; wrap in ToolDefinition |
| `calendar.create_event` | Hestia-Chronos via Hub | New; see Chronos module |
| `calendar.list_events` | Hestia-Chronos via Hub | New |
| `archive.search_entities` | Archive via Hub | Fallback when no module tool |

Oracle never hard-codes tool handlers for domain specifics — tools are discovered dynamically from Hub at session start.

---

## 7. Session State Machine — Replacing the Big `chat()` Method

Current `OracleEngine.chat()` is ~300 lines with nested try/except and interleaved concerns. The rewrite should split it into clean phases.

### Proposed session phases
```
Phase 1: INIT
  - Load history, preferences, available tools manifest

Phase 2: CLASSIFY
  - Router LLM: intent classification (quick_chat vs domain_query + domains)
  - Result: SessionIntent dataclass

Phase 3: AGENT_LOOP (for domain_query; skipped for quick_chat)
  - Turn loop:
    a. Build prompt from history + preferences + context + tool_manifest
    b. Analyst LLM stream → yield token frames
    c. If tool_call emitted → execute tool → inject result → continue loop
    d. If final_answer → break

Phase 4: PERSIST
  - Save user + assistant turns to Archive
  - Background: Scribe extracts preferences + subscriptions

Phase 5: EMIT_SIGNALS
  - Emit any memory/subscription signals to client
```

Each phase is an independent method. Testable in isolation.

---

## 8. Technologies to Evaluate for the Rewrite

| Area | Current | Candidate | Notes |
|---|---|---|---|
| Async runtime | Sync `requests` calls | `httpx` async | Enables true concurrent tool calls |
| LLM streaming | None (blocking) | Gemini stream SDK / Ollama NDJSON stream | See §4 |
| Tool calling | Manual JSON parsing | Gemini native function calling or structured output | Gemini 2.5+ supports native tool use |
| Context compaction | Static `ContextBuilder` | Custom summarisation + sliding window | See §3 |
| Tracing/observability | `print()` + logger | `structlog` or OpenTelemetry traces | Low priority, but valuable |
| Agent framework | None | **Custom Python** (preferred to avoid framework lock-in) | Keep control; framework adds complexity for minimal gain at this scale |

**Recommendation on frameworks**: do NOT adopt LangChain, LlamaIndex, or LangGraph. The Hestia architecture is already well-structured; a framework would add an abstraction layer with its own conventions that conflicts with the Hub-centric design. The reference code (TS/Rust) is likely custom for the same reason — full control is worth the extra code.

---

## 9. What to Preserve Exactly as-is

- The **Hub-proxy routing contract** (never call Archive or module-tools directly).
- The **NDJSON streaming wire protocol** (Telegram bot already consumes it).
- The **four LLM role model** (router, scribe, analyst, embedder) — just modernise the implementations.
- The **preference + subscription extraction** flow — the grounding/dedup logic is correct and should survive.
- The `.env` configuration schema for provider/model pairs.

---

## 10. Files to Delete / Consolidate in the Rewrite

| File | Action |
|---|---|
| `core/database_client.py` | Delete — violates no-direct-DB rule, unused |
| `core/services/router_service.py` | Delete — dead code; routing lives inline |
| `agents/universal_agent.py` | Rewrite — add streaming, multimodal, retry backoff |
| `core/oracle_engine.py` | Rewrite — phase-based session state machine |
| `core/services/retrieval_service.py` | Refactor into tool handler registry |
| `core/services/context_builder.py` | Extend — add compaction/summarisation |
| `core/services/memory_service.py` | Keep, make async (background task) |
| `core/services/module_registry.py` | Keep, wrap in tool definition protocol |
