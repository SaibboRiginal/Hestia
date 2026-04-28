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

Preferred execution policy:
- Do not run heavy compaction inline in the latency-sensitive chat path unless absolutely required to fit the next prompt.
- Prefer background compaction during inactivity or immediately after the response has been delivered.
- Keep a hard emergency compaction path only for cases where the next turn would exceed model limits.
- Support two modes at runtime:
  - fast/interactive mode: minimal hot-path compression, defer most summarisation to idle time
  - deep/deliberate mode: allow more aggressive summarisation/planning work when latency is less important

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

#### 3e. Protected context classes (do not lossy-summarise blindly)
Not every old message should be compressed into vague prose. Before compaction, promote protected facts into structured state and keep them addressable.

Protect at minimum:
- explicit user preferences
- active subscriptions
- active commitments/promises made by Hestia
- unresolved questions / pending clarifications
- current task/branch goal
- user corrections to previous assistant misunderstandings
- pinned entities/documents currently in play

Rule:
- summarisation is allowed for narrative history
- summarisation is not allowed to silently erase structured commitments, controls, or unresolved obligations

#### 3f. Memory taxonomy (must stay separate)
To avoid prompt bloat and state confusion, keep these memory classes distinct in Archive and in retrieval:
- conversational history
- durable user preferences
- task/goal state
- domain facts/entities
- assistant commitments/reminders/questions

This is important for:
- compaction safety
- retrieval relevance
- user trust / inspectability
- cross-client continuity

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

---

## 11. Current Oracle Feature Parity Checklist (Must Keep)

This section is the rewrite guardrail: every item below must remain available after refactor.

### API + Protocol Surface
- [ ] Keep `POST /api/chat` NDJSON streaming contract (`status`, `signal`, `final` frames).
- [ ] Keep `POST /api/chat/document` multipart flow and streamed NDJSON response.
- [ ] Keep `POST /api/format` payload-to-human formatting endpoint.
- [ ] Keep `POST /api/subscriptions/compile` shortcut compiler.
- [ ] Keep `DELETE /api/chat/{session_id}` clear-history endpoint.
- [ ] Keep `GET /health` service-health contract.
- [ ] Keep Hub startup registration (non-fatal on failure).

### Chat Orchestration
- [ ] Keep quick-chat vs domain-query routing behavior.
- [ ] Keep dynamic domain/schema discovery through Hub (`/domains`, `/schemas`).
- [ ] Keep preference injection in analyst prompt.
- [ ] Keep module-tool retrieval with Archive fallback.
- [ ] Keep active filters (`filters`, `filters_gt`, `filters_lt`) and sort metadata support.
- [ ] Keep chat history persistence (user + assistant turns).

### Action/Tool Calls in Chat
- [ ] Keep command discovery from Hub and method-based action filtering (`POST/PUT/PATCH/DELETE`).
- [ ] Keep template variable resolution (`$session_id`, `$chat_id`, `$owner`, etc.) for command payloads.
- [ ] Keep action result formatting via `/api/format` style path.
- [ ] Keep graceful fallback when action-selection JSON is invalid.

### Memory + Notifications
- [ ] Keep preference extraction and storage with ADD/DEPRECATE semantics.
- [ ] Keep subscription extraction and persistence with ADD/DEPRECATE semantics.
- [ ] Keep deterministic subscription upsert behavior and signal emission (`subscription.added/changed/removed`).
- [ ] Keep explicit/forced notification compiler mode.
- [ ] Keep no-direct-DB policy (Hub-routed Archive only).

### LLM Roles and Fallbacks
- [ ] Keep four-role architecture (router/scribe/analyst/embedder + fallback counterpart).
- [ ] Keep primary/fallback chain safety for all LLM critical paths.
- [ ] Keep provider-agnostic `UniversalAgent` abstraction.

### Document Intelligence (Current Scope)
- [ ] Keep attachment analysis for images, PDFs, audio/video, and office/text formats.
- [ ] Keep hybrid extraction path (native model capability + local extractors/transcribers fallback).
- [ ] Keep background document archiving and chunk embedding.
- [ ] Keep document-aware retrieval injection (RAG chunk search + user-doc listing).
- [ ] Keep document signal frame (`document_saved`) behavior.

---

## 12. Second-Pass Verified Notes on `ref/` (Accuracy Check)

This pass validates claims against the local `ref` snapshot, not social media summaries.

### 12.1 Size/Architecture Reality (Local Snapshot)
- `src/QueryEngine.ts` is **~1234 lines**, not 46k.
- `src/Tool.ts` is **~754 lines**, not 29k.
- `src/commands.ts` is **~717 lines**, not 25k.
- Conclusion: architecture is still rich, but some viral "massive file" numbers are not accurate for this snapshot.

### 12.2 Verified Features Actually Present
- Memory index pattern with `MEMORY.md` as pointer file exists (`memdir/`), with caps and truncation guardrails.
- Frontmatter-based memory typing and scan logic exists.
- Frustration keyword regex exists (`userPromptKeywords.ts`) and is used in prompt-processing flow.
- Undercover mode utilities exist (`utils/undercover.ts`) and are wired into prompts/commit flows.
- `ANTI_DISTILLATION_CC` and `NATIVE_CLIENT_ATTESTATION` flags are present in feature docs.
- Voice and buddy subsystems are present in source (`voice/`, `buddy/`), including deterministic companion logic.
- Auto-dream hooks and cron/scheduled task plumbing are present (`services/autoDream`, scheduler paths).

### 12.3 Verified Caveat: Flag-Gated or Partially Missing
- `FEATURES.md` marks several capabilities as compile-clean but runtime-caveated or missing pieces.
- `KAIROS`, `PROACTIVE`, and some assistant/coordinator surfaces are listed as incomplete/missing in this snapshot.
- `commands/buddy/index.js` path is referenced as missing in `FEATURES.md` despite buddy subsystem files existing.
- Conclusion: port architecture patterns, not one-to-one feature assumptions.

---

## 13. Third-Pass Reuse Matrix (3 Sources + Web Signals)

Sources considered in this pass:
- Local `ref/claude-code` snapshot (TypeScript fork + flags audit).
- Local `ref/claw-code` snapshot (Rust-first rewrite + roadmap).
- Local `ref/collection-claude-code-source-code` snapshot (original/decompiled + Python rewrites).
- Web signal cross-checks (architecture/feature catalogs): use as hints, never as source of truth over local code.

### 13.1 Keep and Reuse in Oracle (Direct Fit)
- [ ] Dynamic tool manifest assembly from Hub discovery per request.
- [ ] Turn-based agent loop with max-turn guard and tool-result reinjection.
- [ ] Fast/slow route split (`quick_chat` vs `deep/domain`) with hard latency budgets.
- [ ] Token-level streaming adapters and typed NDJSON event frames.
- [ ] Memory index + scoped memory retrieval + compaction checkpoints.
- [ ] Role-based model routing (router/scribe/analyst/embedder) with provider fallback.
- [ ] Strong permission policy for mutating tool calls (safe/mutating/destructive classes).
- [ ] Retry/backoff/circuit-breaker wrappers around LLM + Hub-routed calls.

### 13.2 Reuse but Move to Separate Service (Better SoC)
- [ ] Proactive/background planning loop (periodic reasoning, reminders, deferred maintenance).
- [ ] Autonomous coding/self-healing execution loop (code edits, tests, build/restart/deploy flows).
- [ ] Long-running schedule/trigger manager and escalation policies.
- [ ] Cross-run learning dataset builder (feedback -> training JSONL pipeline).

### 13.3 Do Not Port As Product Logic
- [ ] TUI-only patterns (Ink layout, terminal UI affordances).
- [ ] Anthropic internal/employee-specific logic (`undercover`, attestation, remote killswitch semantics).
- [ ] Telemetry defaults that violate local-first/privacy-first goals.
- [ ] Any direct DB pattern outside Archive.

---

## 14. Service Boundary Decision (Enterprise but Contained)

Goal: avoid both extremes (100 microservices vs giant monolith).

### 14.1 Recommended Shape
- Keep `oracle` focused on request-time cognition/orchestration.
- Keep `argus` focused on monitoring/detection.
- Add only two new services now:
  - `athena` (planning/proactive brain)
  - `hephaestus` (self-healing/coding executor)

### 14.2 Responsibilities

#### `oracle` (existing)
- [ ] User/service chat orchestration.
- [ ] Model routing + tool selection + response streaming.
- [ ] Context compression + memory retrieval + immediate preference handling.
- [ ] Question/clarification emission to clients via standard protocol.

### 14.2a Artifact Ownership and Write Authority

Service boundaries are not enough; write authority must also be explicit.

Rule:
- every durable artifact class has one owner of truth
- non-owning services may read, suggest, or emit proposals/events, but do not directly mutate the artifact outside their contract

Required ownership map:
- session history / chat turns -> `oracle`
- question lifecycle for live chat turns -> `oracle`
- proactive briefs / periodic planning state -> `athena`
- delivery attempts / delivery outcomes / dispatch logs -> `hermes`
- domain entities / freshness / lifecycle -> owning domain service (`scout`, calendar provider layer, etc.)
- subscriptions -> Archive as source of truth, written through Oracle compiler path or approved service contract
- self-healing run execution records / rollback checkpoints -> `hephaestus`

Implementation consequence:
- if a service wants to influence another service's artifact, it emits a structured proposal/event, not an out-of-band mutation
- this keeps retries, audits, and rollback semantics coherent

#### `argus` (existing, keep focused)
- [ ] Health + logs + anomaly detection.
- [ ] Incident event publication to Hub/Hermes.
- [ ] No direct code mutation.

#### `athena` (new)
- [ ] Periodic proactive planning loop (calendar/tasks/reminders/next-best-actions).
- [ ] Quiet-hours + anti-nag policy.
- [ ] Deferred reflection/consolidation jobs (non-request critical).
- [ ] Creates structured suggestions/events for Oracle/Hermes.

### 14.3 Proactive Thinking Policy

- Keep Hermes as the delivery engine for subscriptions/alerts.
- Do not move "what should I think about?" logic into Hermes.
- Athena owns proactive cognition, but only through small structured briefs, not free-form permanent prompt bloat.

Recommended unit: `focus_brief`
- `brief_id`
- `owner_id`
- `kind` (`agenda_watch`, `housing_watch`, `housing_revisit`, `fun_fact`, `nagging`, `cleanup_review`)
- `goal`
- `cadence`
- `priority`
- `quiet_hours_policy`
- `annoyance_budget`
- `inputs` (domains/entities/filters)
- `success_signal`
- `expiry` / `review_after`

Rules:
- A `focus_brief` tells Athena what to periodically inspect.
- Domain services still own domain truth and domain cleanup.
- Athena may request or suggest cleanup/revisit actions, but should not become the source of truth for stale entity pruning.
- For example:
  - Scout/real-estate stack owns listing freshness, matching, and entity lifecycle.
  - Athena owns revisit prompts like "check these older houses again" or "remind me that this search has gone stale".
  - Calendar/agenda logic can have persistent briefs because the subject is inherently longitudinal.

### 14.4 Notification Ownership

- Keep the current Oracle -> Archive subscription compiler -> Hermes dispatch path.
- Athena may emit synthetic reminder events, but Hermes should still deliver them.
- Existing domain subscriptions should remain event-driven.
- New proactive nudges should be represented as first-class scheduled/reminder events, not hidden prompt injections.

Decision:
- "Notify me when Scout finds houses matching X" stays in the current subscription model.
- "Periodically reconsider older houses and ask me if I want to re-check them" belongs to Athena.
- "Prune stale real-estate entities" belongs to the real-estate/Scout side or Archive policies, not to Athena.

### 14.5 Interaction Ledger / Decision Journal

Chat transcripts and preferences are not enough for longitudinal behavior. Hestia also needs durable structured records of decisions and obligations.

Add an Archive-backed interaction ledger with small typed records such as:
- `user_goal_created`
- `user_goal_closed`
- `user_preference_changed`
- `assistant_commitment_created`
- `assistant_commitment_completed`
- `question_asked`
- `question_answered`
- `suggestion_dismissed`
- `suggestion_snoozed`
- `annoyance_budget_consumed`

Purpose:
- prevent repeated nudges
- remember promises made by the assistant
- support "don't ask again for now" behavior
- make proactive behavior inspectable and debuggable

This ledger is not a second transcript. It is a compact, queryable behavioral memory layer.

#### `hephaestus` (new)
- [ ] Controlled self-healing and coding actions:
  - build/test/restart/deploy scripts
  - file edits/bugfix attempts
  - service bootstrap from templates
- [ ] Dual-brain executor policy:
  - local LLM mode
  - external coding model mode
  - fallback chain configurable via env
- [ ] Mandatory guardrails:
  - permission levels
  - dry-run mode
  - verification gates
  - rollback checkpoints

### 14.6 Hephaestus Execution Policy (strict by design)

Hephaestus should begin as a guarded executor, not an unconstrained autonomous coder.

First-version rules:
- default to runbook execution, diagnostics, and bounded bugfix attempts
- no silent production deploys
- no large refactors without explicit user consent
- no multi-file destructive change sets without approval
- every mutating action must produce:
  - reason/evidence
  - planned action summary
  - verification result
  - rollback checkpoint/reference

Model policy:
- support both local coding models and cloud/API coding models
- choose via env-configured execution policy, not hardcoded names
- allow fallback chain between local and cloud executors
- keep a dry-run/planning-only mode independent of execution mode

Consent policy:
- safe read-only diagnostics may be automatic when authorized by policy
- code edits, restarts, migrations, or deploy-adjacent actions require explicit permission level checks
- user-facing defaults should be conservative

Rollback policy:
- every mutating run must create a rollback point before applying changes where feasible
- rollback must be a first-class operation, not an afterthought
- failed verification should bias toward automatic rollback or "stop and ask" depending on policy tier

---

## 15. Cross-Client Question Protocol (Telegram/Web/App/Voice)

Need: Oracle must ask user follow-up questions in a clean, transport-agnostic way.

### 15.1 Protocol Frames
- Add NDJSON event type: `question`.
- Payload fields:
  - `question_id`
  - `header`
  - `prompt`
  - `kind` (`free_text`, `single_choice`, `multi_choice`, `confirm`)
  - `options` (optional)
  - `timeout_sec` (optional)
  - `required` (bool)

### 15.2 Response Contract
- Clients send answer via standard endpoint:
  - `POST /api/chat/question-answer`
- Payload:
  - `session_id`
  - `question_id`
  - `answer`
  - `client` metadata

### 15.3 Service-to-Service Behavior
- Non-interactive callers set `interactive=false`.
- Oracle must not block waiting for human answers.
- If clarification required in non-interactive mode:
  - return structured `needs_input` response
  - include machine-readable missing fields.

### 15.4 Proactive Message Strategy

- Do not blindly inject every proactive brief into every chat turn.
- Oracle should only inject a compact proactive summary when it is relevant to the current conversation.
- Athena should proactively start contact only when a brief produces a real nudge/reminder/question.
- Default behavior should feel like one assistant continuing one relationship, not many pseudo-agents opening unrelated threads.

Preferred rule:
- passive mode: store proactive state outside the main live prompt and inject only relevant summaries.
- active mode: when Athena decides to interrupt, emit a normal outbound message through Hermes/Telegram/voice using the same owner identity.

Avoid:
- a separate long-lived session per brief.
- prompt-stuffing the main chat with every standing concern.
- multiple competing assistant personas.

### 15.4a Relevance Gate ("why now?")

Athena should not interrupt just because it can produce a suggestion. Every active nudge should pass a relevance gate.

Minimum checks:
- importance
- actionability
- novelty / non-duplication
- timing suitability
- interruption cost
- confidence that the nudge is still based on fresh enough data

Suggested scoring fields:
- `urgency_score`
- `usefulness_score`
- `novelty_score`
- `interruption_cost`
- `confidence_score`

Policy:
- active outreach requires stronger thresholds than passive summary injection
- low-novelty, low-urgency items should be suppressed or batched
- stale-domain-data should block active nudges until refreshed

### 15.5 Primary Session Policy

Hestia should behave as one assistant for one owner.

- Add a single `primary_session_id` per owner/user.
- Telegram/voice/web should attach to that primary session by default.
- Temporary task/session branches may exist, but they must be explicit and secondary.
- Reset should support two scopes:
  - reset current branch/session
  - reset primary session

Current repo caveat:
- Telegram currently keys session state by `chat_id`, which is convenient for transport routing but not the right long-term identity model for a sole-assistant architecture.
- Migrate toward `owner_id -> primary_session_id`, with channel/chat mappings pointing to that owner/session.

### 15.6 Cross-Client Dedupe and Delivery State

One primary session is not enough by itself. Outbound questions, reminders, and proactive nudges need canonical lifecycle tracking across channels.

Required identifiers:
- `outbound_event_id`
- `question_id`
- `brief_id` (when sourced from Athena)
- optional `supersedes_event_id`

Required delivery states:
- `created`
- `queued`
- `delivered`
- `seen` (if client can report it)
- `answered` / `dismissed`
- `superseded`
- `failed`

Rules:
- the same logical question/reminder should not fan out as duplicate user-facing messages across clients unless policy explicitly allows broadcast
- retries must be idempotent
- newer events may supersede older unresolved ones when appropriate
- Archive/Hermes logs should make this traceable end-to-end

---

## 16. Model Routing and Speed Strategy (No Hardcoded Model Names)

### 16.1 Routing Classes
- [ ] `fast_chat` (hello/chitchat/short answers)
- [ ] `planner` (intent/tool planning)
- [ ] `analyst` (deep reasoning)
- [ ] `formatter` (payload-to-user text)
- [ ] `coder` (hephaestus only)

### 16.2 Config Pattern
- [ ] Env-only mapping, no model names in code:
  - `MODEL_CLASS_FAST_CHAT_PRIMARY`
  - `MODEL_CLASS_FAST_CHAT_FALLBACK`
  - etc.
- [ ] Per-client latency profiles:
  - Telegram: aggressive fast-path
  - Web/App: balanced
  - Internal service calls: deterministic/structured

### 16.3 Latency Targets
- [ ] first token target for `fast_chat`.
- [ ] max orchestration budget for classification/tool planning.
- [ ] timeout + graceful degradation policy per route.

### 16.4 Mode Selection Policy (fast vs deliberate)

Do not leave mode selection implicit.

Define all four:
- explicit user override (example: ask for deep thinking/planning)
- per-client default
- per-intent default
- auto-upgrade/auto-downgrade rules

Suggested defaults:
- Telegram -> `fast_chat` biased
- Web/App -> balanced
- multi-tool planning / document reasoning -> planner or deliberate path
- internal service calls -> deterministic structured path

Rule:
- if latency budget is exceeded, degrade gracefully and be explicit in status signaling rather than silently hanging
- fast mode should answer first and defer non-critical consolidation work
- deliberate mode may spend more budget on planning, summarisation, and tool iteration when appropriate

### 16.5 User Controllability Surface

Proactive and autonomous behavior should be user-tunable, not only inferred from free-form chat.

Expose durable controls for:
- proactive mode on/off
- allowed proactive categories
- quiet hours
- reminder aggressiveness
- revisit cadence
- "don't ask again for now"
- "keep this in mind"
- reset current branch vs reset primary session

These controls may still be extracted from conversation, but they should become inspectable/editable state once known.

### 16.6 Failure Doctrine and Resilience Rules

The root Hestia rule is that incomplete work must be tracked durably and retried until resolved or naturally expired. Oracle/Athena/Hephaestus should follow the same doctrine.

Required rules:
- no cross-service workflow is considered complete without durable state transition
- partial failures create explicit pending flags / pending events / retryable records
- retries must be idempotent
- stale or failed proactive chains must be visible in logs and Archive
- silent failure is forbidden

Examples:
- unanswered question timeout -> pending resolution state or expiry record, not silent disappearance
- failed Hermes dispatch -> retryable delivery record with structured failure detail
- failed Athena nudge emission -> pending outbound event / retry path
- failed Hephaestus verification -> failed run record plus rollback or stop-and-ask path

Observability consequence:
- cross-service proactive flows should be traceable end-to-end: source signal -> planning decision -> outbound event -> delivery -> user response / timeout

---

## 17. Prioritized Implementation Plan (Updated)

### P0 — Oracle Hardening
- [ ] Convert Section 11 parity checklist into tests.
- [ ] Async background memory extraction and non-blocking stream close.
- [ ] Remove dead artifacts and fix endpoint consistency (`database_client.py`, `router_service.py`, llm/generate path).
- [ ] Add retry/backoff/circuit-breaker wrappers.

### P1 — Oracle Intelligence Upgrade
- [ ] Turn-based tool loop + true streaming tokens.
- [ ] Context compaction/snapshot persistence.
- [ ] Question protocol (`question` frames + answer endpoint).
- [ ] Model-class routing + client latency profiles.
- [ ] Protected context promotion + memory taxonomy separation.
- [ ] Cross-client dedupe state for questions/reminders.
- [ ] User controls for proactive mode / quiet hours / branch-vs-primary reset.

### P2 — New Services (Contained Expansion)
- [ ] Scaffold `hestia-athena` from template.
- [ ] Scaffold `hestia-hephaestus` from template.
- [ ] Register both on Hub with strict capability contracts.
- [ ] Wire Argus -> Athena/Hephaestus incident pathways.
- [ ] Add write-authority matrix and artifact ownership to service contracts.
- [ ] Add interaction ledger / decision journal schema in Archive.
- [ ] Add proactive relevance gate and outbound lifecycle model.
- [ ] Add Hephaestus permission tiers, rollback checkpoints, and executor policy.

### P3 — Autonomous Ops and Feedback Learning
- [ ] Self-healing runbooks + guarded execution policies.
- [ ] Feedback API + quality labels + dataset exporter (JSONL).
- [ ] Optional training pipeline hooks for local fine-tuning workflows.

---

## 18. Analysis Done Criteria

- [ ] Section 11 parity has automated coverage.
- [ ] One canonical planning file is maintained (this document).
- [ ] New service boundaries are approved and reflected in Hub/Swagger contracts.
- [ ] Interactive question protocol is implemented in at least one client (Telegram) and validated for non-interactive service calls.
- [ ] Oracle fast-path latency targets are measured and enforced.
