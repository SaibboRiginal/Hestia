# Hestia-Hecate 📥

**Role:** Gateway + Dynamic Data Fetcher — Connector Runtime
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

A gateway runtime that executes provider-facing operations on behalf of domain services. Hecate owns provider auth lifecycles (Google/Outlook), exposes full calendar CRUD, and still supports connector-based fetch triggers for domain modules.

Hecate registers itself into Hub (service name `hecate`) and remains discoverable as gateway + fetch runtime.

Hecate is the only service boundary that should hold provider OAuth credentials/tokens for Google and Outlook. Domain services must not keep token.json, credentials.json, refresh tokens, or service-account JSON as their runtime source of truth.

---

## Core Features

### Dynamic Connector Registry
- Modules register a connector on startup by providing: `connector_type`, `config` (credentials, parameters), and `owner` (the registering module's name).
- Connectors are deregistered automatically when the owning module deregisters or becomes unavailable (tracked via Hub).
- Multiple modules can register the same connector type with different configs.

### On-Demand Fetching
- A module calls Hecate with a `connector_id` and optional fetch parameters.
- Hecate runs the connector, collects raw data, and returns it directly in the response.
- For calendar sync flows, Hecate also mirrors normalized events into Archive.

### Connector Interface
All connectors implement a common interface:
```
connect() → establishes connection / authenticates
fetch(params) → returns list of raw items
disconnect() → cleans up
```
Adding a new data source = implementing this interface and registering the connector type.

**Current Connectors:**

| Connector | Type Key | Description |
|---|---|---|
| `IrisEmailFetcher` | `iris_email` | Fetches email-domain items via Hub-routed Iris APIs |
| `GCalFetcher` | `gcal` | Fetches Google calendar events via Hub-routed Hecate gateway APIs |
| `OutlookFetcher` | `outlook_calendar` | Fetches Outlook calendar events via Hub-routed Hecate gateway APIs |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `GET` | `/api/logs` | Runtime log inspection (limit/level/contains) |
| `GET` | `/api/gateway/providers` | List provider runtime status + registry |
| `GET` | `/api/gateway/auth/status` | Auth/configuration state by provider |
| `POST` | `/api/gateway/auth/refresh/{provider}` | Re-acquire token via provider.refresh() (real OAuth refresh) |
| `POST` | `/api/gateway/auth/initiate/{provider}` | Start OAuth flow: Google redirect URL or Microsoft device-code |
| `GET` | `/api/gateway/auth/poll/{provider}` | Poll completion of pending OAuth device-code flow |
| `POST` | `/api/gateway/auth/complete/{provider}` | Exchange auth code for token (Google redirect flow) |
| `DELETE` | `/api/gateway/auth/initiate/{provider}` | Cancel pending OAuth flow |
| `GET` | `/api/gateway/calendar/events` | List events for a provider/calendar |
| `POST` | `/api/gateway/calendar/events` | Create event on target providers |
| `PUT` | `/api/gateway/calendar/events/{id}` | Update event on target provider |
| `DELETE` | `/api/gateway/calendar/events/{id}` | Delete event on target provider |
| `GET` | `/api/gateway/email/messages` | Proxy email search to Iris via Hub |
| `GET` | `/api/gateway/email/messages/{id}` | Proxy single email lookup to Iris via Hub |
| `POST` | `/api/gateway/email/send` | Proxy email send to Iris via Hub |
| `POST` | `/api/ingest/trigger` | Trigger a domain connector fetch (legacy) |
| `POST` | `/api/ingest/calendar/trigger` | Sync calendar events from providers into Archive |

### OAuth Flow (Interactive Authentication)

Hecate supports interactive OAuth for users who have not yet granted access:

1. **Initiate**: `POST /api/gateway/auth/initiate/{provider}`
   - Google: returns `auth_url` → user opens in browser, copies code
   - Microsoft: returns `user_code` + `verification_url` → user visits URL and enters code
2. **Complete (Google)**: `POST /api/gateway/auth/complete/google` with `{"code": "<code>"}`
3. **Poll (Microsoft)**: `GET /api/gateway/auth/poll/microsoft` until `{"status": "authorized"}`
4. Token is stored in `GOOGLE_TOKEN_JSON` / `OUTLOOK_REFRESH_TOKEN` env for the process lifetime.

These endpoints are registered in the Hub command catalog so Oracle and Telegram can guide users through auth.

### Token Refresh

`POST /api/gateway/auth/refresh/{provider}` now calls `provider.refresh()` which:
- Google: re-calls `_load_credentials()` → triggers `creds.refresh(Request())` → rebuilds the API service client
- Outlook: re-calls `_setup()` → MSAL re-acquires access token with refresh token or client credentials

Falls back to full registry reinit if no providers are active.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub routing base URL |
| `HECATE_SERVICE_BASE_URL` | `http://hestia_hecate:19003` | URL reported to Hub registry |
| `HECATE_SERVICE_VERSION` | `1.0.0` | Version reported to Hub |
| `HECATE_CALENDAR_BACKFILL_DAYS` | `7` | Days back to fetch on calendar sync |
| `HECATE_ARCHIVE_ROUTE_TIMEOUT` | `8` | Timeout (s) for Hub-routed Archive writes |
| `HECATE_CALENDAR_WRITE_TIMEOUT` | `10` | Timeout (s) for calendar item writes |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | — | Google OAuth refresh token (if pre-authorized) |
| `GOOGLE_TOKEN_JSON` | — | Full Google token JSON (alternative to above) |
| `GOOGLE_CREDENTIALS_JSON` | — | Google service account JSON |
| `OUTLOOK_CLIENT_ID` | — | Microsoft OAuth app client ID |
| `OUTLOOK_CLIENT_SECRET` | — | Microsoft OAuth client secret |
| `OUTLOOK_TENANT_ID` | — | Microsoft Azure tenant ID |
| `OUTLOOK_REFRESH_TOKEN` | — | Outlook OAuth refresh token |
| `HECATE_ENABLE_PROVIDER_GOOGLE` | `false` | Force-enable Google provider even without credentials |
| `HECATE_ENABLE_PROVIDER_MICROSOFT` | `false` | Force-enable Microsoft provider even without credentials |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Provider Credential Ownership

- Google and Outlook OAuth material belongs in Hecate runtime configuration only.
- Chronos and Iris may reference Hecate through Hub routes, but they must not store provider tokens as their own source of truth.
- If provider access fails, the first place to inspect is Hecate provider config and logs, not downstream domain modules.



---

## Constraints

- Hecate owns provider auth/runtime and provider gateway orchestration (Google/Outlook); domain modules route provider-facing operations through Hub-routed Hecate endpoints.
- Iris remains the email-domain owner for business APIs (search/send/thread); Hecate may proxy/provider-orchestrate email flows through Iris contracts.
- Generic connector fetches return raw data and remain domain-agnostic.
- Calendar gateway operations can mirror events into Archive to support downstream domain workflows.
- Hecate does not publish notifications directly; downstream services handle dispatch logic.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
