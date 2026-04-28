# Oracle Rewrite — Implementation Progress Tracker
*Auto-maintained. Update status + notes before stopping work.*

**Status legend:** `NOT_STARTED` | `IN_PROGRESS` | `DONE` | `BLOCKED`

---

## HOW TO RESUME
1. Read this file top-to-bottom.
2. The last `IN_PROGRESS` item is where work stopped — read its "Files" list and pick up from there.
3. Never mark `DONE` until the change is tested (even smoke-tested locally).
4. If a task is `BLOCKED`, check the "Notes" field before retrying.

---

## P0 — Oracle Hardening

### P0-1 · Rename Metis → Athena everywhere
**Status:** `DONE`
**Files:** `oracle-rewrite-groundwork.md`
**Notes:** Done via PowerShell `-creplace`. All 18 occurrences replaced.

---

### P0-2 · Delete dead artifacts
**Status:** `DONE`
**Files deleted:**
- `app/core/database_client.py` — direct Postgres, violates no-direct-DB contract, never imported
- `app/core/services/router_service.py` — instantiated but never called; routing lives inline
**Notes:** Verified with grep before deleting — zero imports.

---

### P0-3 · Fix `/api/llm/generate` engine.models crash
**Status:** `DONE`
**File:** `app/main.py`
**What:** The endpoint accessed `engine.models["analyst"]` which does not exist. OracleEngine uses `self._agents` (AgentBundle). Fixed to read env vars directly (same pattern as AgentFactory).
**Notes:** `complete()` method already exists on UniversalAgent (alias for `ask()`), so that specific call is fine.

---

### P0-4 · Move memory extraction to background task
**Status:** `DONE`
**File:** `app/core/oracle_engine.py`, `app/main.py`
**What:** `extract_and_save_preferences()` ran synchronously inside the generator, blocking stream close by 2-8s. Moved to `asyncio` background task. Stream closes immediately after `emit_final`; memory sync happens in parallel.
**Notes:** Signals (subscription.added etc.) are still emitted but now best-effort. The generator now yields `emit_final` before memory sync, so Telegram sees the answer immediately.

---

### P0-5 · Add retry/backoff wrappers to UniversalAgent
**Status:** `DONE`
**File:** `app/agents/universal_agent.py`
**What:** Added `_ask_with_retry()` internal helper with exponential backoff (max 3 attempts, 1s/2s/4s delays). Both `ask()` and `ask_stream()` use it. Fallback chain stays at call site in OracleEngine (primary → fallback agent).
**Notes:** Uses stdlib `time.sleep` + loop — no new deps required.

---

## P1 — Oracle Intelligence Upgrade

### P1-1 · True async token streaming (`ask_stream`)
**Status:** `DONE`
**File:** `app/agents/universal_agent.py`
**What:** Added `ask_stream(user_message) → Iterator[str]` that yields token strings.
- Gemini: `client.models.generate_content_stream(...)` → iterate chunks, yield `.text`
- Ollama: POST with `"stream": true` → `response.iter_lines()` → parse JSON, yield `response` field
- `ask()` unchanged (still joins stream for callers that don't need streaming)
**Notes:** Streaming for attachment path deferred to P1-2 (document analyser).

---

### P1-2 · Wire token streaming into oracle_engine chat path
**Status:** `DONE`
**File:** `app/core/oracle_engine.py`, `app/core/services/stream_emitter.py`
**What:** Added `_stream_analyst(prompt)` generator that yields token frames. Added `emit_token(token)` to stream_emitter. Telegram ignores unknown frame types safely.
**Notes:** Mid-stream fallback: if primary LLM fails mid-stream, return partial; only retry fallback if 0 tokens yielded.

---

### P1-3 · Phase-based session state machine
**Status:** `DONE`
**File:** `app/core/oracle_engine.py`
**What:** Refactored `chat()` into `_phase_init`, `_phase_classify`, `_phase_context`, `_phase_background_memory`, `_build_domain_tools`, `_stream_analyst`. Added `SessionIntent` dataclass. Generator contract unchanged.
**Notes:** History is passed as param to `_phase_context` to avoid double-fetch.

---

### P1-4 · Agentic tool loop (ReAct pattern, MAX_AGENT_TURNS=6)
**Status:** `DONE`
**Files:** `app/core/oracle_engine.py`, new `app/core/agent_loop.py`
**What:** `run_agent_loop()` in `agent_loop.py`. XML tool_call detection. Tool result truncation at 2000 chars. `ToolDefinition` + `ScratchMessage` dataclasses. `_build_domain_tools()` generates tool defs from module registry.
**Notes:** Falls back to non-agentic path when no module tools registered.

---

### P1-5 · Model-class routing via env only
**Status:** `DONE`
**Files:** `app/core/services/agent_factory.py`
**What:** `MODEL_CLASS_<CLASS>_PROVIDER/MODEL/FALLBACK_PROVIDER/FALLBACK_MODEL` pattern. Classes: `fast_chat`, `planner`, `analyst`, `coder`. `AgentBundle` extended with `coder` + `fallback_coder`. Full backward compat to old env var names.
**Notes:** Coder default: `qwen2.5-coder:7b` (Ollama). Software engineer system prompt.

---

### P1-6 · Cross-client question protocol
**Status:** `DONE`
**Files:** `app/main.py`, `app/core/oracle_engine.py`, `app/core/services/stream_emitter.py`
**What:** `emit_question()` + `emit_needs_input()` in stream_emitter. `QuestionAnswerRequest` model + `POST /api/chat/question-answer` endpoint. `ask_question()`, `answer_question()`, `get_question_answer()` methods on OracleEngine. In-memory pending question store with threading.Lock.
**Notes:** question_id→state dict on engine. Future: persist to Archive for restart resilience.

---

### P1-7 · Context compaction + snapshot persistence
**Status:** `DONE`
**Files:** `app/core/services/context_builder.py`, `app/core/services/hub_client.py`, `app/core/oracle_engine.py`
**What:** `needs_compaction()`, `extract_protected_messages()`, `build_compaction_prompt()`, `run_background_compaction()` on ContextBuilder. `get_history()` on HubClient. Protected prefixes: [PREFERENCE] [SUBSCRIPTION] [COMMITMENT] [QUESTION] [CORRECTION] [PINNED]. Compaction runs in background daemon thread after every response (checks threshold, skips if not needed).
**Notes:** `ORACLE_COMPACT_TRIGGER_MSGS` (default 20) + `ORACLE_COMPACT_KEEP_RECENT` (default 6) env vars.

---

### P1-8 · Memory taxonomy separation
**Status:** `DONE`
**Files:** `app/core/services/memory_service.py`, `app/core/oracle_engine.py`
**What:** Added taxonomy classes and class-aware retrieval/writes on Oracle side: `conversational_history`, `durable_user_preference`, `task_goal_state`, `domain_fact_entity`, `assistant_commitment`. Preference reads/writes now prefer `memory_class=durable_user_preference` with legacy fallback. Subscription lifecycle now also writes commitment facts into dedicated class.
**Notes:** Archive-side hard enforcement/filtering is backward compatible: Oracle sends `memory_class` now and also post-filters typed rows when available.

---

### P1-9 · User controllability surface
**Status:** `DONE`
**Files:** `app/core/services/user_control_service.py`, `app/core/oracle_engine.py`, `app/main.py`
**What:** Added durable controls surface with API read/write and conversation extraction. New endpoints: `GET /api/user/controls`, `POST /api/user/controls`. Stored controls include proactive on/off, allowed categories, quiet hours, reminder aggressiveness, don't-ask-again topics, and reset scope.
**Notes:** Controls are persisted as typed control facts in Archive memory (`domain=user_controls`, `memory_class=durable_user_preference`) and are extractable from free-form user messages via scribe.

---

## P2 — New Services

### P2-1 · Scaffold Hestia-Athena service
**Status:** `DONE`
**Files:** New `Hestia-Athena/` directory
**What:** Proactive planning/cognition service. Periodic focus_brief loop. Relevance gate (urgency/usefulness/novelty/interruption_cost/confidence scoring). Emits structured events to Hermes.
**Notes:** Scaffolded from project python-service-template and implemented startup Hub registration, background focus_brief loop, weighted relevance gate, manual trigger API, status API, and Hermes `/api/events/ingest` emission. Added Athena service wiring to root `docker-compose.global.yml`.

---

### P2-2 · Scaffold Hestia-Hephaestus service
**Status:** `DONE`
**Files:** New `Hestia-Hephaestus/` directory
**What:** Guarded self-healing/coding executor. Runbook-first, explicit consent tiers, dry-run mode, rollback checkpoints.
**Notes:** Scaffolded from project python-service-template and implemented read-only diagnostics APIs with runbook-first planning, explicit consent tiers, dry-run default, rollback checkpoints, and preview-only execution decisions. Production and mutating execution are intentionally blocked in MVP. Added Hephaestus service wiring to root `docker-compose.global.yml`.

---

### P2-3 · Interaction ledger in Archive
**Status:** `DONE`
**Files:** Archive schema + Oracle write path
**What:** Archive-backed ledger with typed records: user_goal_created, assistant_commitment_created, question_asked, suggestion_dismissed, annoyance_budget_consumed, etc.
**Notes:** Added Archive `interaction_ledger` table + API endpoints (`POST/GET /api/interaction-ledger`) and Oracle write-path emission for key typed events (`question_asked`, `question_answered`, `assistant_commitment_created`, `assistant_commitment_completed`) using Hub-routed Archive calls. Compact, queryable layer; not a second transcript.

---

### P2-4 · Cross-client dedupe delivery state machine
**Status:** `DONE`
**Files:** Hermes + Archive schema
**What:** Outbound event lifecycle: created→queued→delivered→seen→answered/dismissed→superseded/failed. One logical question/reminder must not fan out as duplicates across clients.
**Notes:** Added Archive outbound lifecycle storage (`outbound_events`) with APIs for upsert/query/state updates, then wired Hermes dispatch flow with dedupe keys and lifecycle transitions (`created`, `queued`, `delivered`, `failed`, `superseded`). Hermes now tracks `outbound_event_id`, `question_id`, and `brief_id` in logs and in the outbound lifecycle records.

---

## P3 — Autonomous Ops

### P3-1 · Hephaestus self-healing runbooks
**Status:** `DONE`
**Files:** `Hestia-Hephaestus/app/main.py`
**What:** Added guarded self-healing runbook support in Hephaestus with `rbk_service_self_heal_recovery`, issue-based runbook selection for recovery/restart/crash scenarios, explicit `self_healing_preview` payload in diagnostics, and enriched execute-preview metadata (`mutating_step_count`, `requires_human_approval`). Added `GET /api/hephaestus/runbooks/{runbook_id}` and exposed self-healing capability flags.
**Notes:** Runtime smoke-tested via live container restart and endpoint checks: `/health`, `/api/hephaestus/diagnose`, `/api/hephaestus/execute-preview`.

### P3-2 · Feedback API + quality labels + JSONL exporter
**Status:** `DONE`
**Files:** Archive `models.py`, `schemas.py`, `routers/memory.py`; Oracle `core/services/hub_client.py`, `core/oracle_engine.py`, `main.py`; Swagger `swagger.yml`
**What:** Added quality feedback capture from Oracle responses with Archive persistence and JSONL export for offline analysis/training. Archive models FeedbackRecord with JSONB columns (payload, tags), GIN indexes. Endpoints: POST/GET /api/feedback (create/list), GET /api/feedback/export/jsonl (NDJSON streaming). Oracle service layer routes through Hub per architectural contract. Quality label normalization with alias map + score-based fallback.
**Notes:** Docker runtime smoke-tested: Archive + Oracle containers built and started successfully. Validated endpoints: Archive POST/GET/JSONL and Oracle POST/GET/JSONL all returning 200 OK with proper feedback persistence.

---

## Change Log
| Date | Item | Change |
|------|------|--------|
| 2026-04-27 | P0-1 | Metis→Athena rename, 18 occurrences |
| 2026-04-27 | P0-2 | Deleted database_client.py and router_service.py |
| 2026-04-27 | P0-3 | Fixed engine.models crash in /api/llm/generate |
| 2026-04-27 | P0-4 | Memory extraction moved to background task |
| 2026-04-27 | P0-5 | Retry/backoff added to UniversalAgent |
| 2026-04-27 | P1-1 | ask_stream() added to UniversalAgent |
| 2026-04-27 | P1-2 | Token streaming + emit_token frame wired into oracle_engine |
| 2026-04-27 | P1-3 | Phase-based state machine refactor in oracle_engine.chat() |
| 2026-04-27 | P1-4 | agent_loop.py created; ReAct agentic loop wired into chat path |
| 2026-04-27 | P1-5 | MODEL_CLASS_* env routing + coder class in agent_factory |
| 2026-04-27 | P1-6 | Question protocol: emit_question, POST /api/chat/question-answer |
| 2026-04-27 | P1-7 | Context compaction: ContextBuilder.run_background_compaction() |
| 2026-04-27 | P1-8 | Memory taxonomy wiring: class-aware memory reads/writes + commitments |
| 2026-04-27 | P1-9 | Durable user controls: API surface + scribe extraction + Archive persistence |
| 2026-04-27 | P2-1 | Hestia-Athena scaffold with focus_brief loop, relevance gate, and Hermes emit |
| 2026-04-27 | P2-2 | Hestia-Hephaestus scaffold with guarded read-only runbook diagnostics |
| 2026-04-27 | P2-3 | Archive interaction ledger + Oracle typed interaction writes |
| 2026-04-28 | P2-4 | Hermes+Archive outbound dedupe lifecycle state machine |
| 2026-04-28 | P3-1 | Hephaestus guarded self-healing runbook previews + execute-preview guardrail metadata |
| 2026-04-28 | P3-2 | Feedback API with quality labels + JSONL exporter; Archive persistence + Oracle service layer + endpoints |
