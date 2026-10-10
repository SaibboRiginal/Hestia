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
| `EmailFetcher` | `iris_email` | Reads Hecate's mail gateway in-process (Gmail via OAuth; IMAP-style filter translated + since). Used by Scout |
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
| `POST` | `/api/gateway/auth/complete/{provider}` | Exchange auth code (or full pasted redirect URL) for token; returns `granted_scopes`, reloads Calendar + Gmail |
| `GET` | `/api/gateway/auth/callback/google` | Redirect target (localhost or Cloudflare tunnel) — verifies state, completes Google flow, returns HTML, notifies Telegram |
| `POST` | `/api/gateway/auth/verify` | Check every provider and push re-auth notifications (with button) for broken ones |
| `DELETE` | `/api/gateway/auth/initiate/{provider}` | Cancel pending OAuth flow |
| `GET` | `/api/gateway/calendar/events` | List events for a provider/calendar |
| `POST` | `/api/gateway/calendar/events` | Create event on target providers |
| `PUT` | `/api/gateway/calendar/events/{id}` | Update event on target provider |
| `DELETE` | `/api/gateway/calendar/events/{id}` | Delete event on target provider |
| `GET` | `/api/gateway/mail/status` | Gmail state (authorized, can_send, error) |
| `GET` | `/api/gateway/email/messages` (alias `/api/gateway/mail/messages`) | Mail search: `q` = Gmail syntax, raw IMAP criteria (`FROM "x"`, translated for Gmail) or free text; `since` = ISO date; `limit`. Gmail API (OAuth). Auth failure → `status=error`, `action_required=reauth_google` + Telegram notification |
| `GET` | `/api/gateway/email/messages/{id}` | Single message (Gmail id or Message-ID) |
| `POST` | `/api/gateway/email/send` (alias `/api/gateway/mail/send`) | Send `{to, subject, body}` via Gmail API (`gmail.send`) |
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

**Google (redirect flow — default):** authorization code + PKCE (`core/google_oauth.py`).
1. **Initiate**: `POST /api/gateway/auth/initiate/google` → `auth_url`, `redirect_uri`, `public_redirect`.
   Redirect URI: `GOOGLE_OAUTH_REDIRECT_URI` → Cloudflare tunnel URL (`GOOGLE_TUNNEL_URL_FILE`,
   default `/code/data/tunnel-url.txt`, written by `cloudflare-tunnel.bat`) → `localhost:19003`.
   The pending session (state + PKCE verifier) is persisted to `data/google_oauth_pending.json`
   (TTL 15 min): a restart between initiate and complete does not break the flow.
2. **Complete**, any of:
   - tunnel running → open the link from ANY device (phone too), grant Calendar + Gmail:
     the browser returns through the tunnel to `/api/gateway/auth/callback/google`, done. **Zero manual steps.**
   - no tunnel, browser on the Docker host → same callback via localhost, done.
   - no tunnel, phone → final localhost page does not load (expected): paste the full URL
     (or the `code=` value) in Telegram, or `POST /api/gateway/auth/complete/google {"code": "<url|code>"}`.
   `state` is validated when present. Errors return `{"detail": {"error", "hint"}}`.
3. Token → `GOOGLE_TOKEN_FILE` (volume, survives restarts); Calendar registry and Gmail reloaded;
   confirmation pushed to Telegram (warns if Gmail scope was not granted).

> Quick-tunnel URLs change at every restart: with a *Web application* client add the current
> `…/api/gateway/auth/callback/google` to the authorized redirect URIs (or use a fixed named tunnel
> and `GOOGLE_OAUTH_REDIRECT_URI`). *Desktop app* clients accept any localhost redirect but not the tunnel.

**Google (device_code flow — requires Desktop/TV client type):**
Set `GOOGLE_OAUTH_FLOW_MODE=device_code`. Returns `user_code` + `verification_url`; Hecate auto-polls
in background and notifies success/failure/timeout on Telegram. Google rejects it for "Web application" clients.

**Microsoft (device_code flow):** `user_code` + `verification_url`, poll for completion.

**Poll**: `GET /api/gateway/auth/poll/{provider}` → `authorized | pending | no_pending_flow | error`.

MCP/Hub tools: `gateway_auth_status`, `gateway_auth_verify`, `gateway_auth_initiate_google`,
`gateway_auth_complete`, `gateway_auth_initiate_microsoft`, `gateway_auth_poll`.

### Token Refresh

`POST /api/gateway/auth/refresh/{provider}` now calls `provider.refresh()` which:
- Google: re-calls `_load_credentials()` → triggers `creds.refresh(Request())` → rebuilds the API service client
- Outlook: re-calls `_setup()` → MSAL re-acquires access token with refresh token or client credentials

Falls back to full registry reinit if no providers are active.

### Periodic Auth Re-Check

Hecate re-checks provider auth status every `hecate.auth.recheck_interval` seconds (central setting, default 3600 s = 1 hour, 0 = only at startup; live). If a provider is still unavailable, a fresh `service.action_required` notification is pushed via Hermes. Hermes dedup for recurring events is time-limited so persistent failures are re-notified instead of being permanently silenced.

### Token Persistence & Recovery

**Token persistence (Google):** After every successful credential refresh or OAuth completion, the refreshed token (access + refresh) is automatically serialized to:
1. The volume-mounted file at `GOOGLE_TOKEN_FILE` (default `/code/data/google_token.json`)
2. The `GOOGLE_TOKEN_JSON` environment variable (process lifetime)

On startup Hecate tries refresh-token candidates in order: persistent file →
`GOOGLE_REFRESH_TOKEN` → `GOOGLE_TOKEN_JSON` (duplicates skipped). The token's own granted scopes
are used (asking for scopes it never had → `invalid_scope`). A cached access token is reused only
when its stored `expiry` is in the future. Client id/secret from env win over the token file.

**`invalid_grant` recovery:** a revoked/expired refresh token is dropped (file deleted, or the env
var cleared for the process) and the next candidate is tried, so a dead file never hides a valid
`.env` token. With no valid candidate a `service.action_required` notification with the
"🔑 Riautentica Google" button is pushed (startup + every `hecate.auth.recheck_interval` seconds).

`POST /api/gateway/auth/refresh/{provider}` refreshes active providers and fully reloads the
registry when any provider is still unavailable (e.g. token file just written by the host script).

### Central settings (Themis)

Tunables are declared in `app/core/hecate_settings.py` (owner `hecate`) and changed from WebUI/Telegram;
they are not env vars. All apply **live** (read at use time).

| Key | Type | Default | Effect |
|---|---|---|---|
| `hecate.calendar.backfill_days` | int (giorni) | `7` | Days back fetched on each calendar sync |
| `hecate.archive.route_timeout` | int (s, advanced) | `8` | Timeout for Hub-routed Archive writes |
| `hecate.archive.calendar_write_timeout` | int (s, advanced) | `10` | Timeout for calendar item writes to Archive |
| `hecate.auth.recheck_interval` | int (s) | `3600` | Periodic provider auth re-check + re-notify (0 = only at startup) |
| `hecate.auth.notify_cooldown` | int (s, advanced) | `300` | Min gap between identical action-required notifications |
| `hecate.log.level` | enum | boot `LOG_LEVEL` | Log verbosity |

Endpoints: `GET /api/settings/effective`, `POST /api/settings/reload` (used by Themis).

### Environment Variables

Env holds only secrets, infrastructure and credential-bound deployment choices
(provider enable flags, OAuth flow mode/scopes, Outlook user id).


| Variable | Default | Description |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub routing base URL |
| `HECATE_SERVICE_BASE_URL` | `http://hestia_hecate:19003` | URL reported to Hub registry |
| `HECATE_SERVICE_VERSION` | `1.0.0` | Version reported to Hub |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID (never expires) |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret (never expires) |
| `GOOGLE_REFRESH_TOKEN` | — | Google OAuth refresh token (never expires — the only secret needed for API access) |
| `GOOGLE_TOKEN_JSON` | — | Bundled alternative — refresh_token extracted from here if `GOOGLE_REFRESH_TOKEN` not set |
| `GOOGLE_TOKEN_FILE` | `/code/data/google_token.json` | Persistent token cache (volume-mounted `data/` dir) |
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:19003/api/gateway/auth/callback/google` | Loopback redirect used by the OAuth flow |
| `GOOGLE_OAUTH_SCOPES` | `calendar gmail.readonly gmail.send` (full URLs) | Space/comma separated scopes |
| `GOOGLE_CREDENTIALS_JSON` | — | Google service account JSON (JSON string; not a path) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | Alias for `GOOGLE_CREDENTIALS_JSON` |
| `OUTLOOK_CLIENT_ID` | — | Microsoft OAuth app client ID |
| `OUTLOOK_CLIENT_SECRET` | — | Microsoft OAuth client secret |
| `OUTLOOK_TENANT_ID` | — | Microsoft Azure tenant ID |
| `OUTLOOK_REFRESH_TOKEN` | — | Outlook OAuth refresh token |
| `HECATE_ENABLE_PROVIDER_GOOGLE` | `false` | Force-enable Google provider even without credentials (deployment choice tied to credentials → stays in env) |
| `HECATE_ENABLE_PROVIDER_MICROSOFT` | `false` | Force-enable Microsoft provider even without credentials |
| `GOOGLE_OAUTH_FLOW_MODE` | `redirect` | `redirect` (PKCE; any device with the Cloudflare tunnel, paste-URL fallback otherwise) or `device_code` (Desktop/TV clients only) |
| `GOOGLE_TUNNEL_URL_FILE` | `/code/data/tunnel-url.txt` | Public tunnel URL written by `cloudflare-tunnel.bat`, used as redirect base |
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:19003/api/gateway/auth/callback/google` | Redirect URI for `redirect` flow mode |
| `LOG_LEVEL` | `INFO` | Boot log level only; runtime level = setting `hecate.log.level` |

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

### Mail (`providers/mail.py`)

Gmail only, via the Google OAuth token (no IMAP, no app passwords): read with `gmail.readonly`, send with
`gmail.send` (both in the default scopes — re-authorize Google once if the token predates them).
IMAP-style criteria from connectors (`FROM "x"`, `SUBJECT "y"`, `SINCE 01-Jan-2026`, `UNSEEN`) are translated to
Gmail search. Auth failure → `status=error`, `action_required=reauth_google` + Telegram re-auth button.

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
