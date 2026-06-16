# Hestia-Metis — Test Cases

> Per-service test plan. Root index: `TESTING.md`

## Unit Tests (`unit`)

**File:** `test_mcp_tools.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| M.1 | `test_all_five_tools_present` | ⬜ |
| M.2 | `test_each_tool_has_required_fields` | ⬜ |
| M.3 | `test_dataset_build_requires_name` | ⬜ |
| M.4 | `test_dataset_export_requires_name` | ⬜ |
| M.5 | `test_dataset_status` | ⬜ |
| M.6 | `test_dataset_export_not_found` | ⬜ |
| M.7 | `test_unknown_tool_returns_error` | ⬜ |
| M.8 | `test_all_tools_have_telegram_group` | ⬜ |
| M.9 | `test_visible_tools` | ⬜ |

## Integration Tests (`integration`)

**File:** `test_integration.py`
**Markers:** `integration`

| # | Test Case | Status |
|---|-----------|--------|
| M.10 | `test_build_dataset_from_mocked_feedback` | ⬜ |
| M.11 | `test_dataset_status_after_build` | ⬜ |
| M.12 | `test_export_chatml_format` | ⬜ |
| M.13 | `test_export_alpaca_format` | ⬜ |
| M.14 | `test_benchmark_without_dataset` | ⬜ |
| M.15 | `test_lora_train_without_dataset` | ⬜ |
| M.16 | `test_lora_train_with_dataset` | ⬜ |
| M.17 | `test_build_empty_dataset` | ⬜ |

**File:** `test_dataset_builder.py` (to be created)
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| M.10 | `test_build_dataset_empty` | ⬜ |
| M.11 | `test_build_dataset_with_records` | ⬜ |
| M.12 | `test_deduplicate_removes_duplicates` | ⬜ |
| M.13 | `test_export_chatml_format` | ⬜ |
| M.14 | `test_export_alpaca_format` | ⬜ |

## Integration Tests (`integration`)

| # | Test Case | Status |
|---|-----------|--------|
| M.15 | `test_full_flow_build_export` | ⬜ |

## Notes

- Hub and Archive calls are mocked in unit tests via `patch("main.hub", MagicMock())`.
- Dataset store is in-memory — cleared between test runs.
- The `metis_benchmark_run` and `metis_loRA_train` handlers require live Oracle/external script access; tested as integration tests.
