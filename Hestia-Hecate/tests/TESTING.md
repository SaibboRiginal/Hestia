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
