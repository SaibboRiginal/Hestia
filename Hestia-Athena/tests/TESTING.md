# Hestia-Athena — Test Cases

> Per-service test plan. Root index: `TESTING.md`

## PHASE 3 — Athena: Proactive Cognition (🔴 CRITICAL)

### 3.1 Athena Runtime (`runtime.py`)

**File:** `Hestia-Athena/tests/test_athena_runtime.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 3.1.1 | `test_runtime_init_defaults` | ⬜ |
| 3.1.2 | `test_relevance_threshold_gates_emit` | ⬜ |
| 3.1.3 | `test_relevance_above_threshold_emits_hint` | ⬜ |
| 3.1.4 | `test_commitment_tracking_open` | ⬜ |
| 3.1.5 | `test_commitment_tracking_ttl_expiry` | ⬜ |
| 3.1.6 | `test_retrospective_failure_boosts_urgency` | ⬜ |
| 3.1.7 | `test_retrospective_unresolved_boosts_usefulness` | ⬜ |
| 3.1.8 | `test_oracle_hint_post_success` | ⬜ |
| 3.1.9 | `test_oracle_hint_post_failure_non_fatal` | ⬜ |
| 3.1.10 | `test_loop_enabled_env_off` | ⬜ |
| 3.1.11 | `test_loop_ticks_increment` | ⬜ |

### 3.2 Athena Schemas (`schemas.py`)

**File:** `Hestia-Athena/tests/test_athena_schemas.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 3.2.1 | `test_relevance_signals_normalize_01` | ⬜ |
| 3.2.2 | `test_trigger_request_valid_payload` | ⬜ |
| 3.2.3 | `test_trigger_request_missing_required_field` | ⬜ |

### 3.3 Athena API Endpoints (`main.py`)

**File:** `Hestia-Athena/tests/test_athena_api.py`
**Markers:** `api`

| # | Test Case | Status |
|---|-----------|--------|
| 3.3.1 | `test_health_returns_ok` | ⬜ |
| 3.3.2 | `test_get_logs_returns_list` | ⬜ |
| 3.3.3 | `test_trigger_hint_endpoint` | ⬜ |
| 3.3.4 | `test_status_endpoint_returns_runtime_stats` | ⬜ |

### 3.4 Conversation Auditor (`auditor.py`)

**File:** `Hestia-Athena/tests/test_auditor.py`
**Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 3.4.1 | `test_audit_session_no_history` | ⬜ |
| 3.4.2 | `test_audit_session_scores_and_submits` | ⬜ |
| 3.4.3 | `test_audit_session_oracle_fails` | ⬜ |
| 3.4.4 | `test_parse_scores_extracts_json_array` | ⬜ |
| 3.4.5 | `test_parse_scores_handles_malformed` | ⬜ |
| 3.4.6 | `test_judge_prompt_contains_key_elements` | ⬜ |
| 3.4.7 | `test_submit_score_calls_archive` | ⬜ |
