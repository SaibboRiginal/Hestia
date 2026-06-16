# Hestia-Archive — Test Cases

> Per-service test plan. Root index: `TESTING.md`

## Unit Tests (`unit`)

**File:** `test_feedback_mcp.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 1.1 | `test_tools_list_returns_feedback_submit` | ⬜ |
| 1.2 | `test_tools_list_feedback_submit_schema` | ⬜ |
| 1.3 | `test_tools_call_feedback_submit_minimal` | ⬜ |
| 1.4 | `test_tools_call_feedback_submit_full` | ⬜ |
| 1.5 | `test_tools_call_unknown_tool_returns_error` | ⬜ |
| 1.6 | `test_tools_call_missing_required_fields` | ⬜ |
| 1.7 | `test_tool_has_client_metadata` | ⬜ |

## API Tests (`api`)

**File:** `test_archive_api.py` (to be created)
**Markers:** `api`

| # | Test Case | Status |
|---|-----------|--------|
| 2.1 | `test_health_returns_ok` | ⬜ |
| 2.2 | `test_create_and_get_entity` | ⬜ |
| 2.3 | `test_upsert_entity_deduplication` | ⬜ |
| 2.4 | `test_search_entities_filter` | ⬜ |
| 2.5 | `test_store_and_retrieve_memory` | ⬜ |
| 2.6 | `test_deprecate_memory` | ⬜ |
| 2.7 | `test_store_and_retrieve_chat` | ⬜ |
| 2.8 | `test_create_subscription` | ⬜ |
| 2.9 | `test_list_subscriptions` | ⬜ |
| 2.10 | `test_log_dispatch` | ⬜ |
| 2.11 | `test_documents_upload_and_retrieve` | ⬜ |
| 2.12 | `test_reconcile_endpoint` | ⬜ |

## MCP Tool Notes

- `feedback_submit` handler creates its own `SessionLocal()` — not FastAPI `Depends` — since MCP calls run outside the request lifecycle.
- Feedback records use `source_service="mcp"` to distinguish MCP-submitted grades from internal Oracle feedback submissions.
- The handler defaults `quality_label` to `"mixed"` when not provided rather than rejecting the call.
