# Hestia-Oracle — Test Cases

> Single source of truth for all Oracle test cases.
> Updated 2026-06-16 — Phase 7 complete. Use-case model config. 263 tests pass.

## Test Summary

| Suite | Tests | Coverage Target | Status |
|-------|-------|-----------------|--------|
| `test_agent_loop.py` | 35 | 91% | ✅ PASSING |
| `test_agent_factory.py` | 9 | 98% | ✅ PASSING |
| `test_chat_classifier.py` | 17 | 92% | ✅ PASSING |
| `test_context_builder.py` | 2 | — | ✅ PASSING |
| `test_context_builder_extra.py` | 26 | 73% (combined) | ✅ PASSING |
| `test_memory_intent.py` | 29 | 100% | ✅ PASSING |
| `test_memory_service_unit.py` | 25 | 59% | ✅ PASSING |
| `test_module_registry.py` | 12 | 50% | ✅ PASSING |
| `test_oracle_api.py` | 17 | 54% (main.py) | ✅ PASSING |
| `test_oracle_engine_core.py` | 50 | 72% | ✅ PASSING |
| `test_stream_emitter.py` | 19 | 100% | ✅ PASSING |
| `test_user_control_service.py` | 21 | 80% | ✅ PASSING |
| `test_live_all_tools.py` | 24 | llm_live | ✅ PASSING |
| `test_live_tool_calling_comprehensive.py` | 10 | llm_live | ✅ PASSING |
| **TOTAL** | **298** | **55% overall / 72%+ core** | ✅ |

---

## §1 Unit Tests — agent_loop.py (91% coverage)

### §1.1 _extract_tool_call (14 cases)
- ✅ XML format returns name and params
- ✅ XML format empty params
- ✅ XML format multiline JSON
- ✅ Fenced JSON fallback
- ✅ Plain JSON fallback
- ✅ OpenAI function wrapper format
- ✅ OpenAI function arguments as string
- ✅ No tool call returns None
- ✅ Empty string returns None
- ✅ None returns None
- ✅ Malformed JSON in XML returns None
- ✅ JSON without name field returns None
- ✅ XML takes precedence over plain JSON
- ✅ Params default to empty dict when missing

### §1.2 _truncate_tool_result (4 cases)
- ✅ Short result not truncated
- ✅ Result exactly at limit not truncated
- ✅ Long result truncated with note
- ✅ Truncation note mentions max chars

### §1.3 run_agent_loop (17 cases)
- ✅ No tools returns direct answer
- ✅ Single tool call then answer
- ✅ Unknown tool logs error and continues
- ✅ Tool raises exception logs and continues
- ✅ Preference facts injected into prompt
- ✅ Client instructions injected into prompt
- ✅ LLM failure returns error message
- ✅ Stream function used for final answer
- ✅ Max turns reached returns final non-empty
- ✅ ask_tools_fn returns tool call dict
- ✅ History text injected into prompt
- ✅ Tool log populated after tool calls
- ✅ Tool log tracks failures
- ✅ Early exit after tool calls when no more tools
- ✅ on_thinking callback fires
- ✅ Custom max_turns overrides env
- ✅ action_intent injects policy into prompt

---

## §2 Unit Tests — chat_classifier.py (92% coverage)

### §2.1 Classification (14 cases)
- ✅ Quick chat classification
- ✅ Domain query classification with domain
- ✅ Invalid mode falls back to domain_query
- ✅ Domain not in available_domains is nulled
- ✅ Filters parsed correctly
- ✅ Sort by and sort order parsed
- ✅ Primary router fails uses fallback
- ✅ Both routers fail returns defaults
- ✅ Malformed JSON returns defaults
- ✅ Confidence clamped between 0 and 1
- ✅ Valid domains includes general as fallback
- ✅ Quick chat confidence threshold is float
- ✅ JSON wrapped in prose still parsed
- ✅ Current datetime context included in router prompt

### §2.2 Action Intent (3 new cases)
- ✅ action_intent True when user requests action
- ✅ action_intent False for informational query
- ✅ action_intent defaults to False when missing

---

## §3 Integration Tests — oracle_engine.py (72% coverage)

### §3.1 Chat Quick Chat Path (5 cases)
- ✅ Quick chat returns direct answer via fallback_analyst
- ✅ Quick chat saves history
- ✅ Quick chat with document context
- ✅ Quick chat emits memory sync signals
- ✅ Quick chat skipped when classified as domain_query

### §3.2 Chat Domain Query Path (6 cases)
- ✅ Domain query builds tools and runs agent loop
- ✅ Domain query injects preferences
- ✅ Domain query emits thinking events
- ✅ Domain query emits tool summary when tools called
- ✅ Domain query persists history
- ✅ Domain query runs background memory

### §3.3 Chat Action Intent Path (2 cases)
- ✅ Action intent injects policy in agent loop
- ✅ Action intent creates event tool

### §3.4 Tool Building (10 cases)
- ✅ Builds domain search tools
- ✅ Builds document search tool
- ✅ Builds memory tools (save + search)
- ✅ memory.save handler persists via MemoryService
- ✅ memory.search handler queries via MemoryService
- ✅ Hub commands become tools
- ✅ Hub command tool has proper JSON Schema
- ✅ Hub command handler routes to service
- ✅ Handles commands with no args_schema
- ✅ Duplicate command names not added twice

### §3.5 Athena Hints (5 cases)
- ✅ Ingest hint stores
- ✅ List hints returns stored
- ✅ Hints disabled when env false
- ✅ Select relevant hints filters by domain
- ✅ Format hints produces text

### §3.6 Action Approval (6 cases)
- ✅ Queue and resolve (approve)
- ✅ Reject approval
- ✅ Unknown token returns not_found
- ✅ Expired approval cleaned up
- ✅ Requires approval for DELETE method
- ✅ GET method skipped for approval

### §3.7 Temporal Context (2 cases)
- ✅ Current datetime context has all fields
- ✅ Temporal context injected into agent loop

### §3.8 Format Payload (3 cases)
- ✅ Format returns HTML
- ✅ Format alert uses alert template
- ✅ Format with thinking disabled

### §3.9 Error Handling (4 cases)
- ✅ Quick chat fallback on primary failure
- ✅ Save history failure non-fatal
- ✅ Classifier failure falls back to defaults
- ✅ Agent loop analyst failure returns reply

### §3.10 Session Management (3 cases)
- ✅ Delete chat history
- ✅ Save history appends user and assistant
- ✅ Load preferences deduplicates by id

### §3.11 Question Protocol (4 cases)
- ✅ Ask question registers
- ✅ Answer question resolves
- ✅ Answer unknown question returns False
- ✅ Get question answer returns correct value

---

## §4 Unit Tests — memory_service.py (59% coverage)

### §4.1 save_memory (5 cases)
- ✅ Save memory persists fact
- ✅ Rejects empty fact
- ✅ Rejects whitespace fact
- ✅ Defaults domain to general
- ✅ Handles persistence failure

### §4.2 search_memories (5 cases)
- ✅ Returns results for matching query
- ✅ Empty query returns all
- ✅ No match returns empty
- ✅ Handles exception
- ✅ Case insensitive search

### §4.3 _save_memory_fact (2 cases)
- ✅ Correct payload structure
- ✅ Returns false on failure

### §4.4 _ask fallback chain (3 cases)
- ✅ Primary used when available
- ✅ Fallback used when primary fails
- ✅ Both fail returns NONE

### §4.5 _save_subscriptions (5 cases)
- ✅ Add subscription emits signal
- ✅ Deprecate subscription disables it
- ✅ Upsert updates existing (changed signal)
- ✅ No signal for identical upsert
- ✅ Empty subscription_id skipped

### §4.6 _save_preferences (2 cases)
- ✅ Add preference emits signal
- ✅ Deprecate preference emits signal

### §4.7 Memory Classes (3 cases)
- ✅ Constants are distinct
- ✅ Preference class is correct
- ✅ Commitment class is correct

---

## §5 Unit Tests — stream_emitter.py (100% coverage)

### §5.1 emit_status (3 cases)
- ✅ Correct type and content
- ✅ Empty message handled
- ✅ Ends with newline

### §5.2 emit_token (2 cases)
- ✅ Correct type and text
- ✅ Empty token handled

### §5.3 emit_thinking (5 cases)
- ✅ Reasoning action
- ✅ Tool call action with metadata
- ✅ Tool result action with metadata
- ✅ Without tool name (optional field)
- ✅ Ends with newline

### §5.4 emit_final (2 cases)
- ✅ Correct type, reply, domain
- ✅ Default domain "none"

### §5.5 emit_question (2 cases)
- ✅ Required fields present
- ✅ With options, timeout, kind

### §5.6 emit_needs_input (1 case)
- ✅ Correct format with missing fields

### §5.7 emit_signal (2 cases)
- ✅ Correct format with data
- ✅ Defaults data to empty dict

### §5.8 emit_tool_summary (2 cases)
- ✅ Multiple tool calls in log
- ✅ Empty log handled

---

## §6 Unit Tests — context_builder.py (73% coverage)

### §6.1 compact_history (5 cases)
- ✅ Empty history returns empty string
- ✅ Single message formatted
- ✅ User and assistant roles
- ✅ Truncates long messages
- ✅ Limits to max messages

### §6.2 compact_entity (4 cases)
- ✅ Priority keys included
- ✅ Truncates long string fields
- ✅ Empty entity returns record key
- ✅ Nested dict fields preserved

### §6.3 compact_entities_for_prompt (3 cases)
- ✅ Empty entities returns "No records found"
- ✅ Single entity JSON output
- ✅ Limits to max entities

### §6.4 build_analysis_prompt (3 cases)
- ✅ Includes all sections with datetime
- ✅ No preferences shows "Nessuna preferenza"
- ✅ Omits datetime when None

### §6.5 needs_compaction (2 cases)
- ✅ Small history no compaction
- ✅ Large history needs compaction

### §6.6 extract_protected_messages (4 cases)
- ✅ Extracts [PREFERENCE] tagged
- ✅ Extracts [SUBSCRIPTION] tagged
- ✅ Extracts [COMMITMENT] tagged
- ✅ No protected messages returns empty

### §6.7 build_compaction_prompt (2 cases)
- ✅ Includes message content
- ✅ Empty history handled

### §6.8 truncate (3 cases)
- ✅ Short string not truncated
- ✅ Long string truncated with ellipsis
- ✅ Exact length not truncated

---

## §7 Live LLM Tests (llm_live — Requires Ollama)

### §7.1 Live Tool Calling — Comprehensive (7 cases)
- ✅ Model calls domain search tool
- ✅ Model calls memory.save
- ✅ Model calls memory.search
- ✅ Model handles multiple tools
- ✅ Model returns answer without tools for greeting
- ✅ Tool log contains all calls with metadata
- ✅ HTML contract: no Markdown in output

### §7.2 Live Classifier (2 cases)
- ✅ Classifier detects action_intent for imperative commands
- ✅ Classifier no action_intent for informational query

### §7.3 Live Fallback (1 case)
- ✅ Tool error does not crash loop

### §7.4 Live All Tools by Domain (24 cases) — test_live_all_tools.py
- ✅ Scout: search houses, show listings
- ✅ Chronos: show agenda, create event, delete event, today agenda
- ✅ Iris: search emails, send email, show thread
- ✅ Hecate: sync calendar, auth status, connect Google
- ✅ Argus: system status, system logs, system analysis
- ✅ Hephaestus: remediation status, create remediation
- ✅ Memory: save memory, search memory
- ✅ Misc: search documents, fetch page
- ✅ Tool discrimination: email vs calendar, no destructive on greeting
- ✅ Tool coverage: all 34 tools accounted

---

## §12 Unit Tests — test_plan_features.py (20 cases, NEW)

Oracle Enhancement Plan (P1-P3) feature tests. 20 cases, all passing.

### §12.1 Domain Tool Filtering (4 cases)
- `test_owned_domain_gets_search_tool` — Domain with layer:domain owner gets {domain}.search
- `test_unowned_domain_skipped_with_warning` — Unowned domain logs WARNING, gets only memory+docs
- `test_multi_domain_owners` — Multiple domains each get search tools
- `test_commands_filtered_by_relevant_services` — Hub commands filtered to domain-owning services

### §12.2 Mode Routing (2 cases)
- `test_quick_mode_no_classify` — Quick mode skips classify phase entirely
- `test_thinking_mode_uses_resolved_agent` — Thinking mode respects model param (mode × model independence)

### §12.3 Token Counting (3 cases)
- `test_fallback_heuristic` — Falls back to ~3 chars/token when Ollama unreachable
- `test_context_window_from_env` — ORACLE_CONTEXT_LENGTH env var controls window
- `test_context_pct` — Percentage calculation correct

### §12.4 Preference Domains (5 cases)
- `test_domain_list_from_env` — ORACLE_PREFERENCE_DOMAINS overrides defaults
- `test_cosine_identical` — Identical vectors = 1.0
- `test_cosine_orthogonal` — Orthogonal vectors = 0.0
- `test_cosine_empty` — Empty vectors = 0.0
- `test_classifier_returns_general_when_embed_fails` — Graceful fallback

### §12.5 Multi-Domain Preferences (3 cases)
- `test_multi_domain_match` — Preference with domains=['calendar','work'] matches calendar query
- `test_multi_domain_no_match` — Preference with domains=['food'] filtered out for calendar
- `test_general_always_included` — general domain always matches regardless of query

### §12.6 Thinking Events (2 cases)
- `test_reasoning_content_in_decision` — reasoning_content extracted from decision dict
- `test_empty_reasoning_not_emitted` — Empty reasoning skipped

### §12.7 Compaction (1 case)
- `test_compaction_skips_short_history` — Short history (≤6 msgs) not compacted

---

## Governance Notes

- All new API endpoints and command catalog entries have corresponding tests.
- Live Ollama tests are auto-skipped when Ollama is not reachable (conftest.py).
- Old/legacy files (oracle_engine_old.py, memory_service_old.py, memory_service_new.py) are excluded from coverage targets.
- Document pipeline modules (analyser, archiver, extractor, rag, local_models) have lower coverage — tests for these require file fixtures and are lower priority than core chat/agent functionality.
- **2026-06-18**: Oracle Enhancement Plan P1-P3 features added with 20 new unit tests (test_plan_features.py). AgentFactory now validates required MODEL_USECASE_* env vars at startup. TRACE log level registered in conftest for all tests.
