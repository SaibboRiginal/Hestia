# Hestia-WebUI 🌐

Web-based chat interface for Project Hestia — the second client alongside Telegram.

## Status

**Phase 1: Backend Core** — DONE
**Phase 2: Angular Frontend** — DONE
**Phase 3: File Upload** — DONE (base64 inline via Hub routing)
**Phase 4: Settings + Commands** — DONE
**Phase 5: Chain of Thought** — DONE
**Phase 6: Feedback + Documents** — DONE
**Phase 7: Polish** — PENDING
**Phase 8: Docker + Deploy** — DONE
**Phase 9: Telegram Integration** — PENDING

## Stack

- **Backend**: .NET 9 / ASP.NET Core + SignalR
- **Frontend**: Angular 19 (standalone components)
- **Real-time**: SignalR WebSocket (Oracle NDJSON → typed JSON bridge)
- **UI**: Gemini + Mistral Le Chat inspired dark theme

## Architecture

```
Browser (Angular SPA)
    ↓ SignalR WebSocket + REST
WebUI Backend (ASP.NET Core :19015)
    ├── SignalR Hub /hubs/chat  →  Hub /api/route/oracle/api/chat → Oracle (NDJSON stream)
    ├── REST /api/webui/*       →  Hub /api/route/{service}/{path}
    └── TokenAuthMiddleware on EVERY request
```

**Critical: ALL inter-service calls go through Hub routing.** The WebUI backend NEVER calls Oracle directly.
Chat messages are sent to `{HUB}/api/route/oracle/api/chat` with `stream: true`. Hub forwards the request to
Oracle and streams the NDJSON response back with proper line delimiters (Hub adds `\n` after each line since
`requests.iter_lines()` strips them).

## Key Design Decisions

1. **Backend as security gateway** — frontend NEVER talks directly to internal services
2. **SignalR for real-time** — native reconnection, typed messages, cancellation support
3. **Single-token auth** — generated via Telegram, URL-based, one active at a time
4. **Mistral-style CoT** — numbered reasoning steps, expand/collapse, tinted container
5. **Same app/ structure** — mirrors all other Hestia services
6. **OracleStreamService as typed HttpClient** — uses `AddHttpClient<T>` for managed HttpClient lifecycle (NOT singleton + manual HttpClient)

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| WS | `/hubs/chat?access_token=...` | SignalR chat streaming (Oracle NDJSON bridge) |
| POST | `/api/webui/auth/login` | Validate access token |
| GET | `/api/webui/auth/status` | Token status |
| GET | `/api/webui/sessions/current` | Current session ID |
| POST | `/api/webui/sessions/clear` | Reset session |
| GET | `/api/webui/settings` | Get session settings |
| PUT | `/api/webui/settings` | Update settings |
| GET | `/api/webui/commands` | Discover commands |
| POST | `/api/webui/commands/execute` | Execute command |
| POST | `/api/webui/feedback` | Submit feedback |
| POST | `/api/webui/chat/document` | Upload file (multipart) → base64 JSON via Hub → Oracle `/api/chat/document/json`, NDJSON streamed back (📎 in the chat bar) |
| GET | `/api/webui/documents` | List documents |
| DELETE | `/api/webui/documents/{id}` | Delete document |
| GET | `/health` | Health check |
| POST | `/api/webui/admin/generate-token` · `revoke-token` · GET `token-status` · GET/POST `public-url` | Admin (Telegram / tunnel script). **Guarded**: `X-WebUI-Admin-Secret` = `WEBUI_ADMIN_SECRET` when set, else only direct loopback/private-network calls not coming through Cloudflare/proxy |

### Chat features

- **Oracle questions**: `question` frames (free_text / single_choice / multi_choice / confirm, options as strings or
  `{label, value}`) render as a card above the input; the answer goes back via SignalR `question_answer`.
  `needs_input` frames show the missing fields.
- **Stop / answers during a stream**: SignalR `MaximumParallelInvocationsPerClient = 4` (default 1 queued `cancel`
  and question answers behind the running stream).
- **Upload**: 📎 next to the input (text in the box = instructions for the file).
- **Feedback** 👍/👎 sends `interaction_id` + the prompt/answer pair (`payload.instruction/output`, used by Metis);
  🔄 regenerates the last answer.
- **Command palette**: arguments from the command's `arguments_schema`; `oracle_natural` results are formatted by
  Oracle `/api/format` (like Telegram) and appear in the chat.
- **Settings**: tone / custom prompt become Oracle client instructions; *thinking display* is UI-only
  (hidden = no reasoning box, compact = collapsed, detailed = expanded).

## Known Constraints

- **Document uploads** travel as base64 JSON through Hub (Hub envelopes cannot carry multipart) to Oracle's
  `/api/chat/document/json`, the JSON twin of `/api/chat/document` (a `document` field on `/api/chat` was ignored).
- `HubClient` raises when the routed `status_code` ≥ 400 (target errors used to look like success).
- **OracleStreamService** is transient (managed by `IHttpClientFactory`), not singleton. This means the
  `_oracleReady` flag resets per-resolution but `IsReady` is not critical for the streaming path.
- **NDJSON streaming** depends on Hub correctly adding `\n` delimiters between lines. The `iter_lines()`
  method in Python `requests` strips newlines; Hub's streaming path must re-add them.

## Environment Variables

All documented in `docker-compose.yml`. Key vars:
- `Hestia__HubApiUrl` — Hub endpoint
- `WebUI__SecretKey` — Token signing key (auto-generated; an empty value no longer replaces the random key)
- `WEBUI_ADMIN_SECRET` — optional shared secret for the admin API (set the same value for `telegram`; the tunnel
  script reads it from the environment)
- `WEBUI_PUBLIC_HOST_SUFFIXES` — hosts accepted for public-URL auto-detection (default `.trycloudflare.com`)
- `WebUI__TokenLifetimeHours` — Token expiry (default 72h)

## Local Development (Windows host, outside Docker)

- `appsettings.json` default `Hestia__HubApiUrl=http://hestia_hub:19001/api` is the **Docker-network** name — it only resolves inside the `hestia_net` network.
- `Properties/launchSettings.json` overrides it with `http://localhost:19001/api` (Hub's published port) so `dotnet run` / VS Code F5 works directly on the Windows host.
- Ollama must be running on the host for Oracle's primary LLM (the Oracle container reaches it via `host.docker.internal:host-gateway`, declared as `extra_hosts` in the compose files).

## Docker

```bash
docker compose -f Hestia-WebUI/docker-compose.yml up --build -d
```

Multi-stage build: Angular (node) → .NET SDK → ASP.NET runtime.
Built Angular app served as static files from `wwwroot/`.

## Security

- Single-user, single-active-token policy
- Token: 256-bit random, validated constant-time
- CSP, X-Frame-Options, XSS protection on all responses
- Public URL: set explicitly by `cloudflare-tunnel.bat` (wins); Host-header auto-detection only for real
  Cloudflare traffic (`Cf-Connecting-Ip`) on allowed suffixes — an arbitrary Host could redirect the login
  link (and the token) to another domain
- Admin API guarded (see Endpoints); Telegram mints tokens only through it (no local fallback, no token in Archive memory)
- Rate limiting TBD
- Token state = SHA-256(token + salt) with its own persisted salt in `/app/data/token_state.json`
  (`hestia_webui_data` volume, `WEBUI_TOKEN_STATE_FILE`): survives restarts. The salt used to be
  `WebUI:SecretKey`, random per start → every restart invalidated the token. Nothing is written to Archive
  memory any more (the clear token was readable by Oracle's memory tools).
- `TokenAuthMiddleware` protects `/api/webui/*` (header `X-Access-Token` or `?token=`); exempt: login,
  command list, `/api/webui/admin/*` (guarded by `AdminGuard`), `/health`, static files, `/hubs/chat` (auth in the hub).
