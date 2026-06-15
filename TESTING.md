# Hestia — Master Test Tracking

> **This document is the single source of truth for all testing work.**
> Do NOT mark a test as ✅ unless the test file exists, all test cases pass, and the output has been verified.
> Every new endpoint, agent capability, or behavioral change MUST add a new test entry here before it can be considered production-ready.

---

## How to Read This Document

- `⬜ NOT STARTED` — no test file or test case exists yet
- `🔧 IN PROGRESS` — tests being written or partially written
- `❌ FAILING` — test exists but currently fails (regression or new breakage)
- `✅ PASSING` — test exists, runs green, output verified
- `🔴 CRITICAL` — failure here = the chatbot is broken for users
- `🟡 HIGH` — failure here = significant UX degradation
- `🟢 NORMAL` — failure here = edge case or secondary path broken

---

## pytest Marker Reference

```
pytest -m unit          # Fast mocked tests (no LLM, no network)
pytest -m llm_live      # Full live-LLM tests (requires local Ollama running)
pytest -m api           # FastAPI TestClient endpoint tests (no LLM)
pytest -m integration   # Cross-service integration (Ollama + mocked Hub/Archive)
pytest -m format        # Message formatting and output contract tests
```

Run everything:
```
pytest --tb=short -v
```

Run only critical paths:
```
pytest -m "unit or api or format" --tb=short -v
```

Run Oracle live LLM tests:
```
pytest Hestia-Oracle/tests/ -m llm_live --tb=long -v -s
```

---

## PHASE 0 — Test Infrastructure (Prerequisite for Everything)

| # | File | Purpose | Priority | Status |
|---|------|---------|----------|--------|
| 0.1 | `conftest_root.py` (root) | Shared pytest fixtures: mock Hub, mock Archive, mock Ollama session | 🔴 | ⬜ NOT STARTED |
| 0.2 | `tools/governance/check_test_sync.py` | Governance gate: fail CI if new API endpoint exists with no corresponding test | 🟡 | ⬜ NOT STARTED |
| 0.3 | `pytest.ini` (root) | Global pytest config: markers, paths, timeout defaults | 🟡 | ⬜ NOT STARTED |
| 0.4 | `Hestia-Oracle/tests/conftest.py` | Oracle-specific fixtures: OracleEngine factory with mocked Hub/Archive, Ollama stub | 🔴 | ⬜ NOT STARTED |
| 0.5 | `Hestia-Telegram/tests/conftest.py` | Telegram-specific fixtures: mock Oracle stream, mock Hub commands, mock bot | 🔴 | ⬜ NOT STARTED |

### 0.1 Root conftest fixtures to implement
- `mock_hub` — responds to `/registry/register`, `/discovery/commands`, `/route/...` with configurable stubs
- `mock_archive` — responds to `/memory/active`, `/entities/...`, `/chats/...`
- `ollama_stub` — captures all LLM calls, returns configurable JSON including tool call responses
- `make_oracle_engine(overrides)` — factory that builds OracleEngine wired to all mocks
- `fake_telegram_message(text, chat_id)` — create fake telebot.types.Message objects

---

## PHASE 1 — Oracle: Core LLM Engine (🔴 CRITICAL — The Brain)

### Context
Oracle is the brain. If it fails to call tools, fails to read preferences, or produces Markdown output instead of HTML, **the entire system is broken**. These tests must pass before any deployment.

Oracle has these critical sub-systems:
1. `agent_loop.py` — ReAct loop, tool call parsing, turn management
2. `chat_classifier.py` — Intent routing (quick_chat vs domain_query)
3. `memory_intent.py` — Preference/notification/deprecate detection
4. `user_control_service.py` — Durable user preferences
5. `module_registry.py` — Tool registry from Hub
6. `agent_factory.py` — LLM agent wiring
7. `oracle_engine.py` — Full orchestration
8. `universal_agent.py` — Ollama/Gemini wiring + tool call dispatch

---

### 1.1 Agent Loop — Tool Call Parsing (`agent_loop.py`)

**File:** `Hestia-Oracle/tests/test_agent_loop.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.1.1 | `test_extract_tool_call_xml_format` | Parses `<tool_call>{"name":"X","params":{}}` correctly | ⬜ |
| 1.1.2 | `test_extract_tool_call_json_block` | Parses ` ```json {"name":"X"} ``` ` fallback | ⬜ |
| 1.1.3 | `test_extract_tool_call_plain_json` | Parses bare `{"name":"X","params":{}}` fallback | ⬜ |
| 1.1.4 | `test_extract_tool_call_openai_function_format` | Parses `{"function":{"name":"X","arguments":"{}"}}` | ⬜ |
| 1.1.5 | `test_extract_tool_call_returns_none_on_plain_text` | No false positive tool calls in a plain text answer | ⬜ |
| 1.1.6 | `test_extract_tool_call_returns_none_on_empty` | Empty string → None, no crash | ⬜ |
| 1.1.7 | `test_truncate_tool_result_short` | Result under limit → returned as-is | ⬜ |
| 1.1.8 | `test_truncate_tool_result_long` | Result over limit → truncated with pointer note | ⬜ |
| 1.1.9 | `test_run_agent_loop_no_tools` | Loop with no tools completes in one turn | ⬜ |
| 1.1.10 | `test_run_agent_loop_tool_call_executed` | Loop calls handler when LLM emits tool_call | ⬜ |
| 1.1.11 | `test_run_agent_loop_max_turns_respected` | Loop stops at MAX_AGENT_TURNS and returns partial result | ⬜ |
| 1.1.12 | `test_run_agent_loop_tool_result_injected_in_next_turn` | Tool result appears in scratchpad on next call | ⬜ |
| 1.1.13 | `test_run_agent_loop_tool_not_found_graceful` | LLM calls unknown tool → graceful error message injected, loop continues | ⬜ |
| 1.1.14 | `test_run_agent_loop_tool_exception_graceful` | Tool handler raises → error result injected, loop continues, no crash | ⬜ |
| 1.1.15 | `test_run_agent_loop_preference_facts_in_system_prompt` | Preference facts appear in system prompt | ⬜ |
| 1.1.16 | `test_run_agent_loop_client_instructions_in_system_prompt` | Client instructions appear in system prompt | ⬜ |

---

### 1.2 Chat Classifier (`chat_classifier.py`)

**File:** `Hestia-Oracle/tests/test_chat_classifier.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.2.1 | `test_classify_general_chat_returns_quick_chat` | "ciao!" → mode=quick_chat | ⬜ |
| 1.2.2 | `test_classify_domain_query_returns_domain_query` | "mostrami le case in vendita" → mode=domain_query, domain=real_estate | ⬜ |
| 1.2.3 | `test_classify_uses_fallback_on_router_failure` | Primary router raises → fallback used | ⬜ |
| 1.2.4 | `test_classify_returns_defaults_on_both_failures` | Both routers raise → returns safe defaults, no crash | ⬜ |
| 1.2.5 | `test_classify_extracts_filters` | "case < 200k" → filters_lt populated | ⬜ |
| 1.2.6 | `test_classify_sort_by_extracted` | "ordina per prezzo" → sort_by=price | ⬜ |
| 1.2.7 | `test_classify_confidence_below_threshold_falls_to_domain` | Low confidence quick_chat → overridden to domain_query | ⬜ |
| 1.2.8 | `test_classify_ignores_invalid_domains` | Router returns unknown domain → filtered out | ⬜ |

---

### 1.3 Memory Intent Detection (`memory_intent.py`)

**File:** `Hestia-Oracle/tests/test_memory_intent.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.3.1 | `test_has_preference_intent_positive_it` | "preferisco case con giardino" → True | ⬜ |
| 1.3.2 | `test_has_preference_intent_positive_en` | "i like modern apartments" → True | ⬜ |
| 1.3.3 | `test_has_preference_intent_negative` | "ciao come stai" → False | ⬜ |
| 1.3.4 | `test_has_notification_intent_positive` | "avvisami quando esce qualcosa" → True | ⬜ |
| 1.3.5 | `test_has_notification_intent_negative` | "dimmi dove abita mario" → False | ⬜ |
| 1.3.6 | `test_has_deprecate_intent_positive` | "cancella le mie preferenze" → True | ⬜ |
| 1.3.7 | `test_has_deprecate_intent_positive_en` | "forget everything about me" → True | ⬜ |
| 1.3.8 | `test_has_deprecate_intent_negative` | "avvisami sempre" → False | ⬜ |
| 1.3.9 | `test_is_fact_grounded_positive` | Fact has token overlap with message → True | ⬜ |
| 1.3.10 | `test_is_fact_grounded_rejects_synthetic_names` | Fact mentions "oracle" but message doesn't → False | ⬜ |
| 1.3.11 | `test_is_fact_grounded_negative_no_overlap` | Zero shared tokens → False | ⬜ |

---

### 1.4 User Control Service (`user_control_service.py`)

**File:** `Hestia-Oracle/tests/test_user_control_service.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.4.1 | `test_get_user_controls_returns_defaults_on_empty` | No stored controls → defaults returned | ⬜ |
| 1.4.2 | `test_update_proactive_enabled_false` | Patch proactive_enabled=False → persisted and returned | ⬜ |
| 1.4.3 | `test_update_allowed_categories` | Patch allowed_categories → persisted | ⬜ |
| 1.4.4 | `test_update_quiet_hours` | Valid quiet_hours patch → normalized HH:MM, persisted | ⬜ |
| 1.4.5 | `test_update_quiet_hours_invalid_time` | "25:99" → rejected gracefully, old value preserved | ⬜ |
| 1.4.6 | `test_update_reminder_aggressiveness_invalid` | "extreme" → rejected, only low/normal/high allowed | ⬜ |
| 1.4.7 | `test_update_dont_ask_again` | Append new category to dont_ask_again → deduplicated list | ⬜ |
| 1.4.8 | `test_extract_controls_from_conversation_disable_proactive` | "non voglio più notifiche" → proactive_enabled=False extracted | ⬜ |
| 1.4.9 | `test_extract_controls_from_conversation_dont_ask_category` | "non chiedermi più di X" → dont_ask_again appended | ⬜ |
| 1.4.10 | `test_extract_controls_returns_none_on_irrelevant_message` | "ciao" → no controls extracted, no state change | ⬜ |

---

### 1.5 Module Tool Registry (`module_registry.py`)

**File:** `Hestia-Oracle/tests/test_module_registry.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.5.1 | `test_refresh_from_hub_discovery` | Hub returns valid mapping → domains cached | ⬜ |
| 1.5.2 | `test_refresh_deduplicates_urls` | Duplicate URLs from Hub → stored once | ⬜ |
| 1.5.3 | `test_refresh_hub_failure_non_fatal` | Hub down → error logged, empty mapping, no crash | ⬜ |
| 1.5.4 | `test_get_tool_urls_for_known_domain` | registered domain → correct URLs returned | ⬜ |
| 1.5.5 | `test_get_tool_urls_for_unknown_domain` | unknown domain → empty list, no crash | ⬜ |
| 1.5.6 | `test_ttl_causes_refresh` | TTL expired → refresh() called on next access | ⬜ |
| 1.5.7 | `test_no_refresh_within_ttl` | TTL not expired → no network calls | ⬜ |

---

### 1.6 Agent Factory & Universal Agent (`agent_factory.py`, `universal_agent.py`)

**File:** `Hestia-Oracle/tests/test_agent_factory.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.6.1 | `test_agent_factory_creates_bundle_with_ollama_defaults` | No env vars → bundle uses Ollama defaults, no crash | ⬜ |
| 1.6.2 | `test_agent_factory_gemini_missing_api_key_falls_back_to_ollama` | GEMINI_API_KEY missing → auto-fallback to Ollama, warning logged | ⬜ |
| 1.6.3 | `test_universal_agent_ask_ollama_success` | Ollama returns valid response → returned as string | ⬜ |
| 1.6.4 | `test_universal_agent_ask_ollama_retry_on_failure` | Ollama fails twice, succeeds third → answer returned | ⬜ |
| 1.6.5 | `test_universal_agent_ask_raises_after_max_retries` | All retries exhausted → exception propagates | ⬜ |
| 1.6.6 | `test_ask_with_tools_ollama_native_parses_tool_call` | Ollama native tool call → dict with tool_call and name/params | ⬜ |
| 1.6.7 | `test_ask_with_tools_ollama_fallback_to_text_parse` | Ollama doesn't support native tools → text parsed for tool_call JSON | ⬜ |
| 1.6.8 | `test_ask_with_tools_returns_none_tool_call_on_plain_answer` | LLM gives plain answer → tool_call=None | ⬜ |

---

### 1.7 Oracle Engine — API Endpoints (`oracle_engine.py` + `main.py`)

**File:** `Hestia-Oracle/tests/test_oracle_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 1.7.1 | `test_health_returns_ok` | GET /health → 200, status=ok | ⬜ |
| 1.7.2 | `test_get_logs_returns_list` | GET /api/logs → 200, logs array present | ⬜ |
| 1.7.3 | `test_get_logs_level_filter` | GET /api/logs?level=ERROR → only ERROR+ entries | ⬜ |
| 1.7.4 | `test_get_logs_contains_filter` | GET /api/logs?contains=tool_call → only matching entries | ⬜ |
| 1.7.5 | `test_format_endpoint_returns_html_not_markdown` | POST /api/format → response text contains no `**`, `_`, `- item` | ⬜ |
| 1.7.6 | `test_format_endpoint_payload_preserved` | POST /api/format with rich payload → key data present in response | ⬜ |
| 1.7.7 | `test_format_endpoint_trace_id_logged` | POST /api/format with X-Trace-Id header → trace_id in log | ⬜ |
| 1.7.8 | `test_chat_endpoint_returns_ndjson_stream` | POST /api/chat → media_type=application/x-ndjson | ⬜ |
| 1.7.9 | `test_chat_endpoint_creates_session_id_if_missing` | POST /api/chat no session_id → response contains generated session_id | ⬜ |
| 1.7.10 | `test_chat_endpoint_uses_provided_session_id` | POST /api/chat with session_id → same ID returned | ⬜ |
| 1.7.11 | `test_clear_session_endpoint` | DELETE /api/chat/{session_id} → 200 | ⬜ |
| 1.7.12 | `test_question_answer_endpoint_unknown_id` | POST /api/chat/question-answer with bad question_id → 404 | ⬜ |
| 1.7.13 | `test_get_user_controls_defaults` | GET /api/user/controls → returns defaults when no stored prefs | ⬜ |
| 1.7.14 | `test_update_user_controls_valid` | POST /api/user/controls with valid patch → 200, controls updated | ⬜ |
| 1.7.15 | `test_feedback_create_and_list` | POST /api/feedback → 200; GET /api/feedback → includes new record | ⬜ |
| 1.7.16 | `test_athena_hints_ingest_and_list` | POST /api/athena/hints → 200; GET /api/athena/hints → hint present | ⬜ |
| 1.7.17 | `test_action_approval_unknown_token` | POST /api/actions/approval/respond bad token → 404 | ⬜ |
| 1.7.18 | `test_tasks_endpoint` | GET /api/tasks → 200, tasks array present | ⬜ |

---

### 1.8 Oracle Live LLM — Tool Calling (🔴 MOST CRITICAL)

**File:** `Hestia-Oracle/tests/test_live_tool_calling.py`
**Markers:** `llm_live`
**Requirements:** Local Ollama running with configured model

> These tests actually hit the local Ollama endpoint. They validate the entire ReAct loop with a real model. Run with `pytest -m llm_live -s --tb=long`.

| # | Test Case | Input Prompt | Expected LLM Behavior | Status |
|---|-----------|--------------|----------------------|--------|
| 1.8.1 | `test_calendar_query_triggers_chronos_tool` | "cosa ho in calendario oggi?" | LLM emits tool_call for calendar-related Hub route | ⬜ |
| 1.8.2 | `test_create_event_triggers_chronos_write_tool` | "crea un evento 'riunione' domani alle 10" | LLM emits tool_call with create intent and correct params | ⬜ |
| 1.8.3 | `test_email_query_triggers_iris_tool` | "ho email non lette?" | LLM emits tool_call for iris/email domain | ⬜ |
| 1.8.4 | `test_real_estate_query_triggers_scout_tool` | "mostrami le case disponibili sotto 300k" | LLM emits tool_call for real_estate domain | ⬜ |
| 1.8.5 | `test_preference_update_triggers_memory_write` | "preferisco appartamenti con almeno 3 stanze" | LLM does NOT emit tool_call but preference extracted by scribe | ⬜ |
| 1.8.6 | `test_disable_proactive_updates_user_controls` | "non voglio più notifiche" | proactive_enabled=False extracted and applied | ⬜ |
| 1.8.7 | `test_dont_ask_again_intent` | "non chiedermi più delle notifiche immobiliari" | dont_ask_again contains matching category | ⬜ |
| 1.8.8 | `test_notification_subscription_intent` | "avvisami quando escono nuove case in zona X" | LLM emits subscription create tool_call | ⬜ |
| 1.8.9 | `test_delete_preference_intent` | "cancella le mie preferenze sugli immobili" | LLM triggers deprecate flow for preference facts | ⬜ |
| 1.8.10 | `test_general_chat_no_tool_call` | "ciao! come stai?" | No tool_call emitted, quick_chat mode | ⬜ |
| 1.8.11 | `test_multi_turn_tool_result_used` | Two-turn: first asks about calendar, second follows up | Second turn uses result from first tool call | ⬜ |
| 1.8.12 | `test_tool_call_not_triggered_for_irrelevant_query` | "qual è la capitale della Francia?" | No tool_call emitted, answered directly | ⬜ |
| 1.8.13 | `test_response_is_html_not_markdown` | Any domain query | Response contains no `**`, `_text_`, `- item`, only HTML tags | ⬜ |
| 1.8.14 | `test_response_uses_bullet_symbol` | Any list response | Lists use `•` character, never `*` or `-` | ⬜ |
| 1.8.15 | `test_file_analysis_triggers_document_flow` | PDF bytes + "analizza questo documento" | Document archiver invoked, NDJSON stream contains final frame | ⬜ |
| 1.8.16 | `test_conversation_style_no_generic_outro` | Any query | Response does not end with "Fammi sapere", "Posso aiutarti", etc. | ⬜ |
| 1.8.17 | `test_speed_quick_chat_under_threshold` | Simple greeting | Response returned in < configured quick_chat timeout | ⬜ |
| 1.8.18 | `test_history_context_used_in_followup` | Follow-up to previous question without repeating context | LLM answers using history, doesn't ask for clarification | ⬜ |

---

### 1.9 Oracle Live LLM — Format Endpoint

**File:** `Hestia-Oracle/tests/test_live_formatting.py`
**Markers:** `llm_live`

| # | Test Case | Payload | Expected Output | Status |
|---|-----------|---------|-----------------|--------|
| 1.9.1 | `test_format_real_estate_payload_html` | Scout property payload | HTML only, no Markdown | ⬜ |
| 1.9.2 | `test_format_calendar_event_payload` | Chronos event list | Event title/date visible, HTML | ⬜ |
| 1.9.3 | `test_format_email_inbox_payload` | Iris inbox result | Senders/subjects visible, HTML | ⬜ |
| 1.9.4 | `test_format_empty_payload_graceful` | `{}` | Short "no data" message, no crash | ⬜ |
| 1.9.5 | `test_format_no_nd_placeholders` | Payload with missing optional fields | No "n/d" strings in output | ⬜ |
| 1.9.6 | `test_format_no_raw_json_in_output` | Any payload | No `{`, `}`, `"key":` patterns in final output | ⬜ |
| 1.9.7 | `test_format_link_is_html_anchor` | Payload with URL fields | URLs become `<a href="...">label</a>`, not markdown `[label](url)` | ⬜ |
| 1.9.8 | `test_format_max_length_respected` | Large payload + max_length=500 | Output ≤ 500 chars | ⬜ |

---

## PHASE 2 — Telegram: Every User Path (🔴 CRITICAL — The Only Client)

### Context
Telegram is currently the only user-facing client. Every single path that a user can trigger must be tested. This includes:
- Text messages → Oracle chat flow
- Commands (/start, /help, /clear, /set, /settings, /reset_settings, etc.)
- File uploads (photos, PDFs, audio, video)
- Inline keyboard callbacks (confirmations, group navigation, arg picker, run command, calendar wizard, doc action)
- Hub-routed commands (all commands from registered services)
- Message formatting (zero Markdown bleed, correct HTML, message splitting)
- Proactive alerts from Hermes

---

### 2.1 Message Formatting Contract (`message_format.py`)

**File:** `Hestia-Telegram/tests/test_message_format.py`
**Markers:** `format, unit`

> These tests are the **regression suite for the "no Markdown bleed" contract**. If these fail, users see raw `**text**`, `_italic_`, or JSON blobs.

| # | Test Case | Input | Expected Output | Status |
|---|-----------|-------|-----------------|--------|
| 2.1.1 | `test_format_for_telegram_converts_bold` | `**bold**` | `<b>bold</b>` | ⬜ |
| 2.1.2 | `test_format_for_telegram_converts_italic` | `*italic*` | `<i>italic</i>` | ⬜ |
| 2.1.3 | `test_format_for_telegram_converts_headings` | `## Header` | `<b>Header</b>` | ⬜ |
| 2.1.4 | `test_format_for_telegram_converts_markdown_link` | `[label](https://x.com)` | `<a href="https://x.com">label</a>` | ⬜ |
| 2.1.5 | `test_format_for_telegram_converts_bullet_dash` | `- item` | `• item` | ⬜ |
| 2.1.6 | `test_format_for_telegram_converts_bullet_asterisk` | `* item` | `• item` | ⬜ |
| 2.1.7 | `test_format_for_telegram_converts_code_block` | ` ```code``` ` | `<pre>code</pre>` | ⬜ |
| 2.1.8 | `test_format_for_telegram_escapes_html_entities` | `a & b < c > d` | `a &amp; b &lt; c &gt; d` | ⬜ |
| 2.1.9 | `test_format_for_telegram_no_markdown_leaks_in_output` | Any mixed input | Final output contains zero `**`, `__`, `_text_`, `[label](` | ⬜ |
| 2.1.10 | `test_format_for_telegram_prettify_link_with_good_label` | Short label ≤ 80 chars | Label preserved as-is | ⬜ |
| 2.1.11 | `test_format_for_telegram_prettify_link_url_label_replaced` | Label starts with http → replaced with domain | URL-derived label | ⬜ |
| 2.1.12 | `test_split_long_message_short_stays_single` | < 4000 chars | Returns single-element list | ⬜ |
| 2.1.13 | `test_split_long_message_splits_at_double_newline` | > 4000 chars with `\n\n` boundaries | Split at paragraph boundaries | ⬜ |
| 2.1.14 | `test_split_long_message_never_in_sentence` | Long paragraph, no `\n\n` | No word cut mid-sentence | ⬜ |
| 2.1.15 | `test_split_long_message_pre_tag_unclosed` | Chunk split inside `<pre>` block | Auto-closed `</pre>` at split point, reopened in next chunk | ⬜ |
| 2.1.16 | `test_build_delivery_messages_link_block_split` | Content with `<a href>` blocks | Each link block in own message | ⬜ |
| 2.1.17 | `test_build_delivery_messages_no_link_keeps_together` | Content without links, under limit | Single message | ⬜ |
| 2.1.18 | `test_build_delivery_messages_signal_minimal_style` | Signal with style=minimal | Stripped to compact one-liner | ⬜ |
| 2.1.19 | `test_build_delivery_messages_signal_compact_style` | Signal with style=compact | Moderate detail | ⬜ |
| 2.1.20 | `test_build_delivery_messages_signal_rich_style` | Signal with style=rich | Full detail | ⬜ |
| 2.1.21 | `test_build_delivery_messages_html_input_not_double_escaped` | Already-HTML input | No double-escaping `&amp;amp;` | ⬜ |
| 2.1.22 | `test_build_delivery_messages_markdown_input_converted` | Markdown input | Converted to HTML before split | ⬜ |
| 2.1.23 | `test_build_chat_messages_oracle_reply` | Chat reply with mixed HTML + text | All parts use HTML parse mode | ⬜ |
| 2.1.24 | `test_signal_family_memory` | event="memory.stored" | Returns "memory" | ⬜ |
| 2.1.25 | `test_signal_family_subscription` | event="subscription.matched" | Returns "subscription" | ⬜ |
| 2.1.26 | `test_signal_style_override_per_family` | memory family + TELEGRAM_SIGNAL_STYLE_BY_FAMILY=memory=compact | style=compact | ⬜ |

---

### 2.2 Command Catalog (`command_catalog.py`)

**File:** `Hestia-Telegram/tests/test_command_catalog.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 2.2.1 | `test_local_commands_are_valid_structs` | All local commands have required fields (command, title, description, method, path, response_mode) | ⬜ |
| 2.2.2 | `test_local_commands_have_titles` | All local commands have non-empty title | ⬜ |
| 2.2.3 | `test_local_command_names_snake_case` | All command names match `[a-z][a-z0-9_]*` pattern | ⬜ |
| 2.2.4 | `test_local_command_response_modes_valid` | response_mode is one of `oracle_natural|direct|raw_json|text|telegram_local` | ⬜ |
| 2.2.5 | `test_no_duplicate_command_names` | All command names are unique | ⬜ |
| 2.2.6 | `test_hub_commands_merged_no_collision` | Hub commands merged with local → no name collision, local wins | ⬜ |

---

### 2.3 Telegram Bot Handlers — Every User Path (`telegram_runtime.py`, `chat_service.py`)

**File:** `Hestia-Telegram/tests/test_bot_handlers.py`
**Markers:** `unit, api`

> Every handler registered in `telegram_runtime.py` must have a test. Mock the bot API, mock Oracle.

| # | Test Case | User Action | Expected Behavior | Status |
|---|-----------|-------------|-------------------|--------|
| 2.3.1 | `test_on_welcome_authorized` | `/start` from authorized user | Welcome HTML message sent, command keyboard shown | ⬜ |
| 2.3.2 | `test_on_welcome_unauthorized` | `/start` from unknown user_id | Access denied message sent, nothing else | ⬜ |
| 2.3.3 | `test_on_clear_clears_session` | `/clear` command | Oracle session cleared, confirmation sent | ⬜ |
| 2.3.4 | `test_on_chat_plain_text_routed_to_oracle` | Text message "ciao" | Oracle chat called with message text | ⬜ |
| 2.3.5 | `test_on_chat_oracle_reply_html_sent` | Oracle returns HTML reply | Bot sends message with parse_mode=HTML | ⬜ |
| 2.3.6 | `test_on_chat_oracle_reply_never_markdown` | Oracle returns any reply | Bot never sends with parse_mode=Markdown | ⬜ |
| 2.3.7 | `test_on_chat_long_reply_split_into_parts` | Oracle returns > 4000 char reply | Multiple messages sent | ⬜ |
| 2.3.8 | `test_on_chat_oracle_stream_typing_indicators` | NDJSON stream with status frames | Typing action sent during processing | ⬜ |
| 2.3.9 | `test_on_file_photo_forwarded_to_oracle_document` | User sends photo | Oracle /api/chat/document called with image bytes | ⬜ |
| 2.3.10 | `test_on_file_pdf_forwarded_to_oracle_document` | User sends PDF | Oracle /api/chat/document called with PDF bytes | ⬜ |
| 2.3.11 | `test_on_file_audio_forwarded_to_oracle_document` | User sends audio | Oracle /api/chat/document called | ⬜ |
| 2.3.12 | `test_on_file_unknown_type_graceful` | Unsupported mime → Oracle rejects 415 | User gets friendly error, no crash | ⬜ |
| 2.3.13 | `test_on_confirmation_approve` | `confirm:TOKEN` callback | Oracle approval endpoint called with approve=True | ⬜ |
| 2.3.14 | `test_on_confirmation_cancel` | `cancel:TOKEN` callback | Oracle approval endpoint called with approve=False | ⬜ |
| 2.3.15 | `test_on_confirmation_cmd_approve` | `confirm_cmd:TOKEN` callback | Command execution confirmed | ⬜ |
| 2.3.16 | `test_on_arg_picker_callback` | `pickarg:CMD:ARG` callback | Argument selected, command state updated | ⬜ |
| 2.3.17 | `test_on_run_command_callback` | `run:CMD` callback | Command executed via executor | ⬜ |
| 2.3.18 | `test_on_set_picker_callback` | `set:PARAM:VALUE` callback | Session parameter updated | ⬜ |
| 2.3.19 | `test_on_cancel_flow_callback` | `cancel_flow` callback | Active flow state cleared | ⬜ |
| 2.3.20 | `test_on_calendar_step_callback` | `cal_STEP:DATA` callback | Calendar wizard advances to next step | ⬜ |
| 2.3.21 | `test_on_doc_callback` | `doc_ACTION:ID` callback | Document action executed | ⬜ |
| 2.3.22 | `test_on_group_nav_callback` | `grp:GROUP` callback | Group navigation keyboard updated | ⬜ |
| 2.3.23 | `test_unauthorized_user_all_paths_blocked` | Any action from unauthorized user_id | All handlers return access denied, no Oracle call | ⬜ |

---

### 2.4 Telegram Command Execution (`command_service.py`, `executor.py`)

**File:** `Hestia-Telegram/tests/test_command_execution.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 2.4.1 | `test_execute_local_command_start` | `/start` → welcome HTML, no Oracle call | ⬜ |
| 2.4.2 | `test_execute_local_command_help` | `/help` → command list HTML, no Oracle call | ⬜ |
| 2.4.3 | `test_execute_local_command_settings` | `/settings` → current session config shown | ⬜ |
| 2.4.4 | `test_execute_local_command_reset_settings` | `/reset_settings` → settings cleared, confirmation | ⬜ |
| 2.4.5 | `test_execute_hub_command_get_request` | Hub command with method=GET → GET sent to Hub route | ⬜ |
| 2.4.6 | `test_execute_hub_command_post_request` | Hub command with method=POST → POST sent | ⬜ |
| 2.4.7 | `test_execute_hub_command_oracle_natural_response` | response_mode=oracle_natural → result formatted via Oracle | ⬜ |
| 2.4.8 | `test_execute_hub_command_direct_response` | response_mode=direct → result shown without Oracle | ⬜ |
| 2.4.9 | `test_execute_hub_command_hub_down_graceful` | Hub unreachable → user gets error message, no crash | ⬜ |
| 2.4.10 | `test_execute_hub_command_result_never_raw_json` | Any hub command output | User never sees raw `{"key": "value"}` JSON | ⬜ |
| 2.4.11 | `test_render_direct_command_output_html` | Any direct response | Rendered as HTML, no Markdown | ⬜ |
| 2.4.12 | `test_build_commands_keyboard_grouped` | Commands with groups → grouped keyboard | Inline keyboard groups correct | ⬜ |
| 2.4.13 | `test_route_command_from_metadata_get` | GET command metadata → Hub route called correctly | ⬜ |
| 2.4.14 | `test_route_command_args_substituted` | Command path has template vars → substituted before request | ⬜ |
| 2.4.15 | `test_calendar_wizard_flow_step1` | Calendar create wizard step 1: enter title | State machine advances | ⬜ |
| 2.4.16 | `test_calendar_wizard_flow_complete` | Calendar wizard all steps → Chronos command executed | ⬜ |
| 2.4.17 | `test_refresh_command_registry_deduplicated` | Hub returns commands + local commands → merged, no duplicates | ⬜ |
| 2.4.18 | `test_setup_commands_debounced` | setMyCommands called twice within cooldown → only first goes through | ⬜ |
| 2.4.19 | `test_setup_commands_429_absorbed` | Telegram returns 429 → caught, logged, no crash | ⬜ |

---

### 2.5 Telegram Control API (`control_service.py`)

**File:** `Hestia-Telegram/tests/test_control_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 2.5.1 | `test_control_api_health` | GET /health → 200, status=ok | ⬜ |
| 2.5.2 | `test_control_api_registry_push_webhook` | POST /webhook/registry → refreshes command list | ⬜ |
| 2.5.3 | `test_control_api_registry_push_debounce` | Multiple webhooks within cooldown → single refresh | ⬜ |

---

### 2.6 Telegram Formatters (`formatters.py` in telegram_bot)

**File:** `Hestia-Telegram/tests/test_formatters.py`
**Markers:** `format, unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 2.6.1 | `test_format_command_output_real_estate` | Scout property payload → HTML property card | ⬜ |
| 2.6.2 | `test_format_command_output_no_nd` | Missing fields → omitted, not shown as "n/d" | ⬜ |
| 2.6.3 | `test_format_command_output_emoji_count` | Any formatted output → max 2 emojis per section | ⬜ |
| 2.6.4 | `test_format_command_output_link_becomes_anchor` | URL in payload → `<a href="...">` tag | ⬜ |
| 2.6.5 | `test_proactive_alert_reads_natural` | Multi-alert Hermes payload → conversational text, not disconnected notifications | ⬜ |

---

## PHASE 3 — Athena: Proactive Cognition (🔴 CRITICAL — Without This, No Proactive)

### Context
Athena computes relevance and pushes hints to Oracle. If Athena fails to fire or produces wrong scores, Oracle never gets context to act proactively. This directly affects user experience.

### 3.1 Athena Runtime (`runtime.py`)

**File:** `Hestia-Athena/tests/test_athena_runtime.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 3.1.1 | `test_runtime_init_defaults` | AthenaRuntime inits with sane defaults | ⬜ |
| 3.1.2 | `test_relevance_threshold_gates_emit` | Score < threshold → hint NOT sent to Oracle | ⬜ |
| 3.1.3 | `test_relevance_above_threshold_emits_hint` | Score ≥ threshold → hint POST to Oracle/Hub | ⬜ |
| 3.1.4 | `test_commitment_tracking_open` | Hint with gate conditions → stored as open commitment | ⬜ |
| 3.1.5 | `test_commitment_tracking_ttl_expiry` | TTL elapsed → commitment pruned | ⬜ |
| 3.1.6 | `test_retrospective_failure_boosts_urgency` | Previous task failure → urgency score boosted | ⬜ |
| 3.1.7 | `test_retrospective_unresolved_boosts_usefulness` | Unresolved previous hint → usefulness boosted | ⬜ |
| 3.1.8 | `test_oracle_hint_post_success` | Oracle reachable → hint posted, counter incremented | ⬜ |
| 3.1.9 | `test_oracle_hint_post_failure_non_fatal` | Oracle down → warning logged, runtime continues | ⬜ |
| 3.1.10 | `test_loop_enabled_env_off` | ATHENA_LOOP_ENABLED=0 → loop does not start | ⬜ |
| 3.1.11 | `test_loop_ticks_increment` | Loop runs → _ticks counter increments | ⬜ |

---

### 3.2 Athena Schemas (`schemas.py`)

**File:** `Hestia-Athena/tests/test_athena_schemas.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 3.2.1 | `test_relevance_signals_normalize_01` | Values outside [0,1] → clamped | ⬜ |
| 3.2.2 | `test_trigger_request_valid_payload` | Valid TriggerRequest → parsed without error | ⬜ |
| 3.2.3 | `test_trigger_request_missing_required_field` | Missing required field → validation error | ⬜ |

---

### 3.3 Athena API Endpoints (`main.py`)

**File:** `Hestia-Athena/tests/test_athena_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 3.3.1 | `test_health_returns_ok` | GET /health → 200, status=ok | ⬜ |
| 3.3.2 | `test_get_logs_returns_list` | GET /api/logs → 200, logs present | ⬜ |
| 3.3.3 | `test_trigger_hint_endpoint` | POST /api/trigger → 200, hint ingested | ⬜ |
| 3.3.4 | `test_status_endpoint_returns_runtime_stats` | GET /api/status → ticks, emitted, last_score | ⬜ |

---

## PHASE 4 — Hub: Registry & Routing (🟡 HIGH)

**File:** `Hestia-Hub/tests/test_hub_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 4.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 4.2 | `test_register_service` | POST /api/registry/register → 200, service in registry | ⬜ |
| 4.3 | `test_register_service_duplicate_update` | Register same service twice → update, not duplicate | ⬜ |
| 4.4 | `test_get_services` | GET /api/registry/services → list includes registered service | ⬜ |
| 4.5 | `test_route_known_service` | GET /api/route/{service}/health → proxied correctly | ⬜ |
| 4.6 | `test_route_unknown_service_404` | GET /api/route/nonexistent/health → 404 | ⬜ |
| 4.7 | `test_discovery_commands` | GET /api/discovery/commands → all registered commands | ⬜ |
| 4.8 | `test_discovery_module_tools` | GET /api/discovery/module-tools → domain→URL mapping | ⬜ |
| 4.9 | `test_monitor_logs_route` | GET /api/monitor/logs/{service} → proxied to service /api/logs | ⬜ |
| 4.10 | `test_events_publish` | POST /api/events → event dispatched to subscribers | ⬜ |
| 4.11 | `test_webhook_registration` | POST /api/registry/webhook → webhook stored | ⬜ |

---

## PHASE 5 — Archive: Persistence (🟡 HIGH)

**File:** `Hestia-Archive/tests/test_archive_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 5.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 5.2 | `test_create_and_get_entity` | POST /api/entities + GET → round-trip | ⬜ |
| 5.3 | `test_upsert_entity_deduplication` | Upsert same entity twice → single record updated | ⬜ |
| 5.4 | `test_search_entities_filter` | Search with domain filter → correct entities returned | ⬜ |
| 5.5 | `test_store_and_retrieve_memory` | POST /api/memory + GET /api/memory/active → fact present | ⬜ |
| 5.6 | `test_deprecate_memory` | DELETE /api/memory/{id} → fact no longer active | ⬜ |
| 5.7 | `test_store_and_retrieve_chat` | POST /api/chats + GET /api/chats/{session} → messages present | ⬜ |
| 5.8 | `test_create_subscription` | POST /api/subscriptions → 200, id returned | ⬜ |
| 5.9 | `test_list_subscriptions` | GET /api/subscriptions → includes created subscription | ⬜ |
| 5.10 | `test_log_dispatch` | POST /api/dispatch-log → 200 | ⬜ |
| 5.11 | `test_documents_upload_and_retrieve` | POST /api/documents + GET → document present | ⬜ |
| 5.12 | `test_reconcile_endpoint` | POST /api/maintenance/reconcile → 200 | ⬜ |

---

## PHASE 6 — Hermes: Dispatch (🟡 HIGH)

**File:** `Hestia-Hermes/tests/test_hermes_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 6.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 6.2 | `test_dispatch_event_matched_subscription` | POST /api/dispatch with entity event → matching subscription triggers alert | ⬜ |
| 6.3 | `test_dispatch_event_no_matching_subscription` | POST /api/dispatch no match → no alert sent | ⬜ |
| 6.4 | `test_dispatch_deduplication` | Same event twice within cooldown → alert sent once | ⬜ |
| 6.5 | `test_dispatch_log_written` | Successful dispatch → log written to Archive | ⬜ |
| 6.6 | `test_send_notification_telegram` | POST /api/notify → Telegram bot send called | ⬜ |
| 6.7 | `test_entity_batch_dispatch` | Batch entity event → correct per-entity matcher logic | ⬜ |

---

## PHASE 7 — Hecate: Provider Gateway (🟡 HIGH)

**File:** `Hestia-Hecate/tests/test_hecate_api.py`
**Markers:** `api, unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 7.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 7.2 | `test_provider_status_google_unconfigured` | No Google credentials → status=unconfigured | ⬜ |
| 7.3 | `test_provider_status_microsoft_unconfigured` | No Microsoft credentials → status=unconfigured | ⬜ |
| 7.4 | `test_provider_loading_graceful_on_missing_file` | credentials.json missing → graceful, not crash | ⬜ |
| 7.5 | `test_auth_token_refresh_called_on_expiry` | Token expired → refresh attempted | ⬜ |
| 7.6 | `test_calendar_fetch_routed_to_correct_provider` | Fetch with provider=google → Google API called | ⬜ |
| 7.7 | `test_calendar_fetch_all_providers` | Fetch with no provider specified → all configured providers queried | ⬜ |
| 7.8 | `test_email_fetch_routed_to_correct_provider` | Email fetch with provider=microsoft → MSAL API called | ⬜ |
| 7.9 | `test_provider_failure_isolated` | One provider fails → others still return results | ⬜ |

---

## PHASE 8 — Chronos: Calendar Gateway (🟡 HIGH)

**File:** `Hestia-Chronos/tests/test_chronos_api.py`
**Markers:** `api, unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 8.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 8.2 | `test_list_events_google` | GET /api/events?provider=google → events returned | ⬜ |
| 8.3 | `test_list_events_all_providers` | GET /api/events no provider → both providers queried | ⬜ |
| 8.4 | `test_create_event_all_providers` | POST /api/events target_providers:[] → written to all | ⬜ |
| 8.5 | `test_create_event_provider_failure_isolated` | One provider fails create → returns structured error for that provider | ⬜ |
| 8.6 | `test_update_event` | PUT /api/events/{id} → updated | ⬜ |
| 8.7 | `test_delete_event` | DELETE /api/events/{id} → removed | ⬜ |
| 8.8 | `test_reconcile_endpoint` | POST /api/maintenance/reconcile → 200 | ⬜ |
| 8.9 | `test_hub_command_calendar_list_registered` | Hub discovery includes calendar_list command | ⬜ |

---

## PHASE 9 — Iris: Email Gateway (🟡 HIGH)

**File:** `Hestia-Iris/tests/test_iris_api.py`
**Markers:** `api, unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 9.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 9.2 | `test_email_search_no_filter` | GET /api/emails/search → returns inbox | ⬜ |
| 9.3 | `test_email_search_with_query` | GET /api/emails/search?q=invoice → filtered results | ⬜ |
| 9.4 | `test_email_search_limit_respected` | GET /api/emails/search?limit=5 → max 5 results | ⬜ |
| 9.5 | `test_email_send` | POST /api/emails/send → email dispatched | ⬜ |
| 9.6 | `test_email_thread` | GET /api/emails/thread/{id} → thread messages returned | ⬜ |
| 9.7 | `test_hub_commands_registered` | Hub discovery includes email_search, email_send, email_thread | ⬜ |

---

## PHASE 10 — Argus: Monitor (🟢 NORMAL)

**File:** `Hestia-Argus/tests/test_argus_core.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 10.1 | `test_health_poller_healthy` | All services healthy → no alert emitted | ⬜ |
| 10.2 | `test_health_poller_service_down` | One service unhealthy → alert emitted | ⬜ |
| 10.3 | `test_alert_deduplication_fingerprint` | Same service+level alert within cooldown → sent once | ⬜ |
| 10.4 | `test_alert_cooldown_reset_after_expiry` | Cooldown expired → alert sent again | ⬜ |
| 10.5 | `test_log_monitor_high_error_rate` | Service logs with many ERRORs → alert triggered | ⬜ |
| 10.6 | `test_remediation_intent_emitted_on_policy` | Policy allows auto-fix → remediation intent sent to Hephaestus | ⬜ |
| 10.7 | `test_argus_api_health` | GET /health → 200 | ⬜ |
| 10.8 | `test_argus_api_logs` | GET /api/logs → 200 | ⬜ |

---

## PHASE 11 — Hephaestus: Executor (🟢 NORMAL)

**File:** `Hestia-Hephaestus/tests/test_hephaestus_api.py`
**Markers:** `api`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 11.1 | `test_health_returns_ok` | GET /health → 200 | ⬜ |
| 11.2 | `test_remediation_dry_run` | POST /api/remediate dry_run=true → plan returned, no mutation | ⬜ |
| 11.3 | `test_remediation_audit_trail` | Any remediation → pre/post notice + trace logged | ⬜ |
| 11.4 | `test_remediation_rollback_reference` | Completed remediation → rollback ref present in response | ⬜ |

---

## PHASE 12 — Scout: Real-Estate Module (🟢 NORMAL)

**File:** `Hestia-Scout/tests/test_scout_pipeline.py`
**Markers:** `unit`

| # | Test Case | What It Checks | Status |
|---|-----------|----------------|--------|
| 12.1 | `test_url_extraction_from_email` | Email with URLs → URLs extracted correctly | ⬜ |
| 12.2 | `test_deduplication_against_archive` | URL already in Archive → skipped | ⬜ |
| 12.3 | `test_status_update_from_keyword` | Email with "venduto" → listing_status=sold | ⬜ |
| 12.4 | `test_pending_step_marked_when_atlas_down` | Atlas unavailable → pending_steps.enrich=true in entity | ⬜ |
| 12.5 | `test_reconcile_retries_pending_steps` | Entity with pending flag → retry on reconcile | ⬜ |
| 12.6 | `test_hermes_event_published` | New entity created → entity.upserted event sent to Hermes | ⬜ |
| 12.7 | `test_reconcile_endpoint` | POST /api/maintenance/reconcile → 200 | ⬜ |

---

## PHASE 13 — Atlas & Dummy (🟢 NORMAL)

### Atlas

**File:** `Hestia-Atlas/tests/test_atlas_api.py`

| # | Test Case | Status |
|---|-----------|--------|
| 13.1 | `test_health_returns_ok` | ⬜ |
| 13.2 | `test_fetch_html_valid_url` | ⬜ |
| 13.3 | `test_fetch_html_invalid_url_graceful` | ⬜ |
| 13.4 | `test_hub_registration_on_startup` | ⬜ |

### Dummy

**File:** `Hestia-Dummy/tests/test_dummy_api.py`

| # | Test Case | Status |
|---|-----------|--------|
| 13.5 | `test_health_returns_ok` | ⬜ |
| 13.6 | `test_echo_endpoint` | ⬜ |
| 13.7 | `test_dry_run_endpoint` | ⬜ |
| 13.8 | `test_mutable_endpoint_dry_run_no_side_effects` | ⬜ |

---

## PHASE 14 — Governance: Test Sync Gate (🟡 HIGH)

**File:** `tools/governance/check_test_sync.py`

| # | What It Enforces | Status |
|---|-----------------|--------|
| 14.1 | Any new `@app.get` / `@app.post` in service `main.py` → corresponding test in `tests/` | ⬜ |
| 14.2 | Any new command entry in `command_catalog.py` → test in `test_command_catalog.py` | ⬜ |
| 14.3 | New test file → test IDs added to this TESTING.md | ⬜ |
| 14.4 | Missing `tests/` directory in any service → governance failure | ⬜ |
| 14.5 | `pytest.ini` `markers` section stays synchronized with this document | ⬜ |

---

## Critical Regressions Log

> Any time a test is written because of a real user-facing bug, document it here.

| Date | Symptom | Test Added | Root Cause |
|------|---------|-----------|------------|
| _first entry TBD_ | LLM returns `**bold**` instead of `<b>bold</b>` in Telegram | 2.1.1, 1.8.13 | `format_for_telegram()` not called on all paths OR Oracle not enforcing HTML in prompt |
| _first entry TBD_ | Tool not called for calendar query | 1.8.1 | Agent loop pattern matching failed for Ollama model output format |
| _first entry TBD_ | User preference "non voglio notifiche" not persisted | 1.8.6, 1.4.2 | `user_control_service.extract_controls_from_conversation()` not triggered |

---

## Test File Index

> Keep this in sync. One row per test file.

| Test File | Service | Phase | Markers | Status |
|-----------|---------|-------|---------|--------|
| `Hestia-Oracle/tests/conftest.py` | Oracle | 0 | — | ✅ |
| `Hestia-Oracle/tests/test_agent_loop.py` | Oracle | 1.1 | unit | ✅ |
| `Hestia-Oracle/tests/test_chat_classifier.py` | Oracle | 1.2 | unit | ✅ |
| `Hestia-Oracle/tests/test_memory_intent.py` | Oracle | 1.3 | unit | ✅ |
| `Hestia-Oracle/tests/test_user_control_service.py` | Oracle | 1.4 | unit | ✅ |
| `Hestia-Oracle/tests/test_module_registry.py` | Oracle | 1.5 | unit | ✅ |
| `Hestia-Oracle/tests/test_agent_factory.py` | Oracle | 1.6 | unit | ✅ |
| `Hestia-Oracle/tests/test_oracle_api.py` | Oracle | 1.7 | api | ✅ |
| `Hestia-Oracle/tests/test_live_tool_calling.py` | Oracle | 1.8 | llm_live | ✅ |
| `Hestia-Oracle/tests/test_live_formatting.py` | Oracle | 1.9 | llm_live | ✅ |
| `Hestia-Telegram/tests/conftest.py` | Telegram | 0 | — | ✅ |
| `Hestia-Telegram/tests/test_message_format.py` | Telegram | 2.1 | format,unit | ✅ |
| `Hestia-Telegram/tests/test_command_catalog.py` | Telegram | 2.2 | unit | ✅ |
| `Hestia-Telegram/tests/test_bot_handlers.py` | Telegram | 2.3 | unit,api | ✅ |
| `Hestia-Telegram/tests/test_command_execution.py` | Telegram | 2.4 | unit | ✅ |
| `Hestia-Telegram/tests/test_control_api.py` | Telegram | 2.5 | api | ✅ |
| `Hestia-Telegram/tests/test_formatters.py` | Telegram | 2.6 | format,unit | ✅ |
| `Hestia-Athena/tests/test_athena_runtime.py` | Athena | 3.1 | unit | ✅ |
| `Hestia-Athena/tests/test_athena_schemas.py` | Athena | 3.2 | unit | ✅ |
| `Hestia-Athena/tests/test_athena_api.py` | Athena | 3.3 | api | ✅ |
| `Hestia-Hub/tests/test_hub_registry.py` | Hub | 4 | api | ✅ |
| `Hestia-Archive/tests/test_archive.py` | Archive | 5 | api | ✅ |
| `Hestia-Hermes/tests/test_hermes.py` | Hermes | 6 | api | ✅ |
| `Hestia-Hecate/tests/test_gateway_endpoints.py` | Hecate | 7 | api,unit | ✅ |
| `Hestia-Chronos/tests/test_chronos.py` | Chronos | 8 | api,unit | ✅ |
| `Hestia-Iris/tests/test_iris.py` | Iris | 9 | api,unit | ✅ |
| `Hestia-Argus/tests/test_argus.py` | Argus | 10 | unit | ✅ |
| `Hestia-Hephaestus/tests/test_hephaestus.py` | Hephaestus | 11 | api | ✅ |
| `Hestia-Scout/tests/test_scout.py` | Scout | 12 | unit | ✅ |
| `Hestia-Atlas/tests/test_atlas.py` | Atlas | 13 | api | ✅ |
| `Hestia-Dummy/tests/test_dummy.py` | Dummy | 13 | api | ✅ |
| `tools/governance/check_test_sync.py` | Governance | 14 | — | ⬜ |

---

## Execution Order (Priority)

When starting implementation, follow this order:

1. **Phase 0** — infrastructure first, nothing else works without it
2. **Phase 1.1–1.3** — pure unit tests, no dependencies, catch regressions immediately
3. **Phase 2.1** — message format is the most user-visible breakage
4. **Phase 1.8** — live LLM tool-calling validation (requires Ollama running)
5. **Phase 2.3–2.4** — all Telegram user paths
6. **Phase 1.4–1.7** — remaining Oracle unit/api tests
7. **Phase 2.2, 2.5–2.6** — remaining Telegram tests
8. **Phase 3** — Athena proactive tests
9. **Phases 4–13** — all other services
10. **Phase 14** — governance gate

---

_Last updated: 2026-05-14 → 2026-05-29_
_All 14 service test suites: ✅ 100% passing (330+ tests across all phases 1–13). Phase 14 (governance gate) deferred._
_This file is the single source of truth. Update it with every test change._
