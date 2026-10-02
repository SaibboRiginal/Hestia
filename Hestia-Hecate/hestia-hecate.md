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
| `POST` | `/api/gateway/auth/complete/{provider}` | Exchange auth code (or full pasted redirect URL) for token |
| `GET` | `/api/gateway/auth/callback/google` | Loopback redirect target — completes Google flow, returns HTML |
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

### Google setup (one-time, ~5 min)

> History: the old flow used the "out-of-band" redirect (`urn:ietf:wg:oauth:2.0:oob`).
> Google blocked OOB in January 2023, so the consent page always failed with
> `Error 400: invalid_request`. The current flow uses a **loopback redirect + PKCE**.

1. Google Cloud Console → *APIs & Services* → enable **Google Calendar API**.
2. *OAuth consent screen* → User type **External** → add your Google account to *Test users*.
   Then press **Publish app → In production**. In *Testing* mode Google kills refresh tokens
   after **7 days** (`invalid_grant`). Unverified "In production" is fine for personal use:
   you just click *Advanced → Go to app (unsafe)* on the consent page.
3. *Credentials* → *Create credentials* → *OAuth client ID* → type **Desktop app**.
   (Desktop clients accept any `http://localhost:<port>` redirect; no redirect URI to register.)
   Using a *Web application* client instead? Add the exact `GOOGLE_OAUTH_REDIRECT_URI`
   (default `http://localhost:19003/api/gateway/auth/callback/google`) to its authorized redirect URIs.
4. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `Hestia-Hecate/app/.env`, restart Hecate.
5. Authorize — pick one:
   - **From Telegram (works from the phone):** ask "collega Google Calendar". Open the link,
     grant access. The final `localhost` page will not load on the phone — that's expected.
     Copy the full URL from the address bar and paste it in the chat. Telegram forwards it to
     Hecate automatically and replies "✅ Google collegato".
   - **From a browser on the Docker host:** call `POST /api/gateway/auth/initiate/google`, open
     `auth_url`. Google redirects to `localhost:19003/.../callback/google` and Hecate completes
     the flow by itself.
   - **Host script:** `google-oauth.bat` (Windows) or `./google-oauth.sh` (Linux/RPi with browser).
     Writes `data/google_token.json` and hot-reloads Hecate via `POST /api/gateway/auth/refresh/google`.
6. Check: `GET /api/gateway/auth/status` → `runtime.active` contains `google`.

**Troubleshooting**

| Symptom | Cause / fix |
|---|---|
| `Error 400: invalid_request` (OOB) | Old code. Update Hecate. |
| `redirect_uri_mismatch` | Client is *Web application* without the redirect URI → use *Desktop app*. |
| `access_denied` | Consent refused, or account not in *Test users*. |
| `invalid_grant` after ~7 days | Consent screen in *Testing* → publish *In production*, re-authorize. |
| `invalid_grant` on complete | Code already used/expired (~10 min) → initiate again. |
| No `refresh_token` returned | Remove the app at myaccount.google.com/permissions, re-authorize. |
| `state mismatch` | URL from an older attempt → use the latest link. |

### OAuth Flow (API)

1. **Initiate**: `POST /api/gateway/auth/initiate/{provider}`
   - Google: returns `auth_url` + `redirect_uri` (loopback, PKCE S256, `access_type=offline`, `prompt=consent`).
     The pending session (state + PKCE verifier) is persisted to `data/google_oauth_pending.json`
     (TTL 15 min), so a restart between initiate and complete does not break the flow.
   - Microsoft: returns `user_code` + `verification_url` (device-code flow).
2. **Complete (Google)**, any of:
   - `GET /api/gateway/auth/callback/google?code=&state=` — loopback redirect target, returns an HTML page.
   - `POST /api/gateway/auth/complete/google` with `{"code": "<code OR full redirect URL>"}`.
     `state` is validated when present in the URL. Errors return `{"detail": {"error", "hint"}}`.
3. **Poll**: `GET /api/gateway/auth/poll/{provider}` → `authorized | pending | no_pending_flow`.
4. Google token is written to `GOOGLE_TOKEN_FILE` (volume-mounted, survives restarts) and the provider
   registry is reloaded in place. Microsoft refresh token lives in `OUTLOOK_REFRESH_TOKEN` for the process lifetime.

MCP/Hub tools: `gateway_auth_status`, `gateway_auth_initiate_google`, `gateway_auth_complete_google`,
`gateway_auth_initiate_microsoft`, `gateway_auth_poll`.

### Token Refresh

`POST /api/gateway/auth/refresh/{provider}` now calls `provider.refresh()` which:
- Google: re-calls `_load_credentials()` → triggers `creds.refresh(Request())` → rebuilds the API service client
- Outlook: re-calls `_setup()` → MSAL re-acquires access token with refresh token or client credentials

Falls back to full registry reinit if no providers are active.

**Token persistence (Google):** After every successful credential refresh, the refreshed token
(access + refresh) is automatically serialized to:
1. The volume-mounted file at `GOOGLE_TOKEN_FILE` (default `/code/data/google_token.json`)
2. The `GOOGLE_TOKEN_JSON` environment variable (process lifetime)

On startup Hecate tries refresh-token candidates in order: persistent file →
`GOOGLE_REFRESH_TOKEN` → `GOOGLE_TOKEN_JSON` (duplicates skipped). A cached access token is
reused only when its stored `expiry` is in the future. If a candidate fails (`invalid_grant`),
the next one is tried, so a revoked token in the file never hides a valid `.env` token.
Client id/secret from env always win over values stored in the token file.

`POST /api/gateway/auth/refresh/{provider}` refreshes active providers and fully reloads the
registry when any provider is still unavailable (e.g. token file just written by the host script).

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
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:19003/api/gateway/auth/callback/google` | Loopback redirect used by the OAuth flow |
| `GOOGLE_OAUTH_SCOPES` | `https://www.googleapis.com/auth/calendar` | Space/comma separated scopes |
| `GOOGLE_CREDENTIALS_JSON` | — | Google service account JSON (JSON string; not a path) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | Alias for `GOOGLE_CREDENTIALS_JSON` |
| `OUTLOOK_CLIENT_ID` | — | Microsoft OAuth app client ID |
| `OUTLOOK_CLIENT_SECRET` | — | Microsoft OAuth client secret |
| `OUTLOOK_TENANT_ID` | — | Microsoft Azure tenant ID |
| `OUTLOOK_REFRESH_TOKEN` | — | Outlook OAuth refresh token |
| `HECATE_ENABLE_PROVIDER_GOOGLE` | `false` | Force-enable Google provider even without credentials |
| `HECATE_ENABLE_PROVIDER_MICROSOFT` | `false` | Force-enable Microsoft provider even without credentials |
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
