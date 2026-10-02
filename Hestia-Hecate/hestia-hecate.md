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
| `POST` | `/api/gateway/auth/complete/{provider}` | Exchange auth code for token; returns `granted_scopes` and invalidates cached mail provider |
| `DELETE` | `/api/gateway/auth/initiate/{provider}` | Cancel pending OAuth flow |
| `GET` | `/api/gateway/calendar/events` | List events for a provider/calendar |
| `POST` | `/api/gateway/calendar/events` | Create event on target providers |
| `PUT` | `/api/gateway/calendar/events/{id}` | Update event on target provider |
| `DELETE` | `/api/gateway/calendar/events/{id}` | Delete event on target provider |
| `GET` | `/api/gateway/email/messages` | Proxy email search to Iris via Hub; returns 503 with re-auth instructions on scope/auth failures |
| `GET` | `/api/gateway/email/messages/{id}` | Proxy single email lookup to Iris via Hub |
| `POST` | `/api/gateway/email/send` | Proxy email send to Iris via Hub |
| `POST` | `/api/ingest/trigger` | Trigger a domain connector fetch (legacy) |
| `POST` | `/api/ingest/calendar/trigger` | Sync calendar events from providers into Archive |

### OAuth Flow (Interactive Authentication)

Hecate supports interactive OAuth for users who have not yet granted access:

**Google (redirect flow — default, works from ANY device with tunnel):**
1. **Initiate**: `POST /api/gateway/auth/initiate/google`
   - Returns `auth_url` — the user opens it in a browser
2. **Auto-detect public URL**: If `cloudflare-tunnel.bat` is running, Hecate
   automatically uses the Cloudflare tunnel URL as the redirect target.  The
   auth URL works from phones, tablets, and other PCs — not just localhost.
3. User grants access to Calendar + Gmail
4. Browser redirects through the tunnel → Hecate callback → token persisted
5. Providers reload automatically; a confirmation appears in Telegram
6. **Zero manual steps** — no code copying, no pasting.

**Google (device_code flow — requires Desktop/TV client type):**
Set `GOOGLE_OAUTH_FLOW_MODE=device_code`.  Returns `user_code` + `verification_url`.
Auto-polls in background.  NOTE: Google rejects this for "Web application" clients.

**Microsoft (device_code flow):**
Same as before — `user_code` + `verification_url`, poll for completion.

### Token Refresh

`POST /api/gateway/auth/refresh/{provider}` now calls `provider.refresh()` which:
- Google: re-calls `_load_credentials()` → triggers `creds.refresh(Request())` → rebuilds the API service client
- Outlook: re-calls `_setup()` → MSAL re-acquires access token with refresh token or client credentials

Falls back to full registry reinit if no providers are active.

### Periodic Auth Re-Check

Hecate re-checks provider auth status every `HECATE_AUTH_RECHECK_INTERVAL_SECONDS` (default 3600 s = 1 hour). If a provider is still unavailable, a fresh `service.action_required` notification is pushed via Hermes. Hermes dedup for recurring events is time-limited so persistent failures are re-notified instead of being permanently silenced.

### Token Persistence & Recovery

**Token persistence (Google):** After every successful credential refresh or OAuth completion, the refreshed token (access + refresh) is automatically serialized to:
1. The volume-mounted file at `GOOGLE_TOKEN_FILE` (default `/code/data/google_token.json`)
2. The `GOOGLE_TOKEN_JSON` environment variable (process lifetime)

On startup, Hecate loads from the persistent file first (it holds the most recent token from a prior container run), then falls back to `GOOGLE_TOKEN_JSON`. This prevents the `invalid_grant` error that occurs when a stale refresh token from a static `.env` file is resent to Google after Google has rotated the token.

If the persistent file exists and contains a valid refresh token, the `.env` value is effectively ignored — the volume-mounted copy is always more current.

**`invalid_grant` recovery:** When Google returns `invalid_grant` (refresh token revoked or expired), Hecate automatically deletes the cached token file and clears the `GOOGLE_TOKEN_JSON`/`GOOGLE_REFRESH_TOKEN` env vars. This ensures the next OAuth flow starts from a clean slate. A `service.action_required` notification is pushed so the user can re-authenticate.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub routing base URL |
| `HECATE_SERVICE_BASE_URL` | `http://hestia_hecate:19003` | URL reported to Hub registry |
| `HECATE_SERVICE_VERSION` | `1.0.0` | Version reported to Hub |
| `HECATE_CALENDAR_BACKFILL_DAYS` | `7` | Days back to fetch on calendar sync |
| `HECATE_ARCHIVE_ROUTE_TIMEOUT` | `8` | Timeout (s) for Hub-routed Archive writes |
| `HECATE_CALENDAR_WRITE_TIMEOUT` | `10` | Timeout (s) for calendar item writes |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID (never expires) |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret (never expires) |
| `GOOGLE_REFRESH_TOKEN` | — | Google OAuth refresh token (never expires — the only secret needed for API access) |
| `GOOGLE_TOKEN_JSON` | — | Bundled alternative — refresh_token extracted from here if `GOOGLE_REFRESH_TOKEN` not set |
| `GOOGLE_TOKEN_FILE` | `/code/data/google_token.json` | Persistent token cache (volume-mounted `data/` dir) |
| `GOOGLE_CREDENTIALS_JSON` | — | Google service account JSON (JSON string; not a path) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | Alias for `GOOGLE_CREDENTIALS_JSON` |
| `OUTLOOK_CLIENT_ID` | — | Microsoft OAuth app client ID |
| `OUTLOOK_CLIENT_SECRET` | — | Microsoft OAuth client secret |
| `OUTLOOK_TENANT_ID` | — | Microsoft Azure tenant ID |
| `OUTLOOK_REFRESH_TOKEN` | — | Outlook OAuth refresh token |
| `HECATE_ENABLE_PROVIDER_GOOGLE` | `false` | Force-enable Google provider even without credentials |
| `HECATE_ENABLE_PROVIDER_MICROSOFT` | `false` | Force-enable Microsoft provider even without credentials |
| `GOOGLE_OAUTH_FLOW_MODE` | `device_code` | OAuth mode: `device_code` (works from any device) or `redirect` (localhost only) |
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:19003/api/gateway/auth/callback/google` | Redirect URI for `redirect` flow mode |
| `HECATE_AUTH_RECHECK_INTERVAL_SECONDS` | `3600` | Seconds between periodic auth re-check (0 to disable) |
| `HECATE_ACTION_NOTIFY_COOLDOWN` | `300` | Seconds between repeated action-required notifications per action key |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

**Canonical Google OAuth setup (no expiring values):**
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
```
These three values **never expire**. On every cold start, Hecate constructs fresh
credentials using only the refresh token, calls Google's token endpoint to get a
new access token, and caches the result to the persistent file. No access token
or expiry timestamp is stored in `.env` — the 1‑hour access token is always
obtained live.

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
