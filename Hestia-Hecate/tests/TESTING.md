# Hestia-Hecate — Test Cases

> Per-service test plan. Root index: `TESTING.md`

## PHASE 7 — Hecate: Provider Gateway (🟡 HIGH)

**File:** `Hestia-Hecate/tests/test_hecate_api.py`
**Markers:** `api, unit`

| # | Test Case | Status |
|---|-----------|--------|
| 7.1 | `test_health_returns_ok` | ⬜ |
| 7.2 | `test_provider_status_google_unconfigured` | ⬜ |
| 7.3 | `test_provider_status_microsoft_unconfigured` | ⬜ |
| 7.4 | `test_provider_loading_graceful_on_missing_file` | ⬜ |
| 7.5 | `test_auth_token_refresh_called_on_expiry` | ⬜ |
| 7.6 | `test_calendar_fetch_routed_to_correct_provider` | ⬜ |
| 7.7 | `test_calendar_fetch_all_providers` | ⬜ |
| 7.8 | `test_email_fetch_routed_to_correct_provider` | ⬜ |
| 7.9 | `test_provider_failure_isolated` | ⬜ |
| 7.10 | `test_google_token_persisted_on_refresh` | ⬜ |
| 7.11 | `test_google_token_loaded_from_file_first` | ⬜ |
| 7.12 | `test_google_token_persisted_on_oauth_complete` | ⬜ |

## Google OAuth loopback + PKCE (🔴 regression guard)

**File:** `Hestia-Hecate/tests/test_google_oauth.py` · **Markers:** `unit`

| # | Test Case | Status |
|---|-----------|--------|
| 7.13 | `test_initiate_never_uses_oob` | ✅ |
| 7.14 | `test_initiate_respects_custom_redirect` | ✅ |
| 7.15 | `test_initiate_missing_client_creds` | ✅ |
| 7.16 | `test_parse_code_input` (raw code / full URL / query / error) | ✅ |
| 7.17 | `test_complete_with_pasted_url_persists_token` | ✅ |
| 7.18 | `test_complete_rejects_state_mismatch` | ✅ |
| 7.19 | `test_complete_reports_google_error_with_hint` | ✅ |
| 7.20 | `test_complete_without_refresh_token` | ✅ |
| 7.21 | `test_pending_flow_survives_restart` | ✅ |
| 7.22 | `test_callback_endpoint_completes_flow` / `_shows_error` | ✅ |
| 7.23 | `test_token_file_counts_as_configured` | ✅ |
| 7.24 | `test_provider_falls_back_from_dead_file_token_to_env` | ✅ |
| 7.25 | `test_provider_error_explains_testing_mode` | ✅ |

Tests use a temp `GOOGLE_TOKEN_FILE` (see `tests/conftest.py`): never write to `/code/data`.
