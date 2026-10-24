# Hestia-MCP — Model Context Protocol Gateway

**Role:** Hestia's one MCP server — the single way every client lists and runs tools.
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker
**Port:** 19013

---

## Responsibility

**Hestia's one MCP server.** Every client lists and runs tools here, the same way
(`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §B2): Oracle's agent loop, Telegram's command menu, the WebUI
*Comandi* page and external AIs such as Claude (through an access, below). Before 2026-10-18 there were four ways (Oracle read Hub
`/discovery/commands` and filled templates itself, Telegram read `/tools/all`, the WebUI had its own resolver,
`/tools/call` had a fourth copy); they are gone.

- **Catalog**: Hub's registry discovery (`/discovery/commands`: each module's own `/mcp` tools + inline
  `capabilities.commands`) turned into MCP tool descriptors (`app/core/catalog.py`), cached `mcp.tools.cache_ttl`.
  Hestia details stay in `_meta.hestia` (service, method, path, response mode/prompt, clients, Telegram menu fields).
- **Visibility**: a client sees tools whose `clients` is empty, `*` or its own key (`telegram`; `webui` = `ui`);
  `oracle` sees all (it filters by domain owner itself). The client names itself with `X-Hestia-Client`.
  External AIs see **only** tools whose module wrote `"external"` in `clients` (empty or `*` is not enough).
- **Execution**: `tools/call` builds the request with `hestia_common.tool_call` (path `$x`/`{x}`, templates
  `$session_id` · `$chat_id`/`$owner` · `$arg.x`, rest → query or JSON body) and routes it through Hub with
  `X-Session-Id`, `X-Trace-Id` and `X-Hestia-Client` (= the client the user talks from, given by the caller).
- Read tools carry `annotations.readOnlyHint: true` (same rule Oracle used for "writes").
- **Display blocks**: a module answer may carry `display` (`hestia_common.display`, how Telegram draws it without the
  model). `tools/call` keeps it only for client `telegram` and strips it for everyone else (Oracle, WebUI, external
  AIs), so models see the same data as before.

Python clients use `hestia_common.mcp_client.MCPClient(HUB_API_URL, client=…)` (`list_tools`, `call`, `as_command`);
the WebUI uses `HubClient.McpListToolsAsync` / `McpCallToolAsync`.

## External AIs (accesses)

`app/core/access.py`, `app/core/external.py` — SPEC §B2, §B6.

- **Door**: WebUI `POST /mcp` (the only service behind the tunnel; no WebUI login there) forwards body +
  `Authorization: Bearer <token>` through Hub to `POST /mcp/external` here. The internal `/mcp` is never exposed.
- **Access** = name, scope `read` | `write`, tools (`[]` = every tool opened to external AIs), expiry, last use, calls
  today. Stored in Archive (`/api/mcp-access-store`); the token (`hst_…`) is shown once and stored only as sha256.
  Lookups are cached 30 s; revoke / renew / delete here drop the cache, so they take effect at once.
- **Answers**: wrong, revoked or expired token → 401 (`WWW-Authenticate: Bearer error="invalid_token",
  resource_metadata="<base>/.well-known/oauth-protected-resource/mcp"`, the start of OAuth for claude.ai / ChatGPT); more than
  `mcp.external.max_calls_per_min` messages a minute per access → 429 (`Retry-After: 60`); a `read` access calling a
  write tool → 403 (and `tools/list` shows it only reading tools); a tool outside the access → "Unknown tool".
- **Towards the module** an external call carries only `X-Hestia-Access: <access name>` (never session, chat or
  client from the caller): Forge files `forge_develop` as an external proposal, Themis shows "<name> (AI esterna)".
- **Audit**: `event=mcp_external_call access= tool= ok=`; a successful write also leaves a silent Hermes inbox entry
  (`/api/dispatch/send` with `metadata.quiet`), no push.
- Tools open to external AIs today: `forge_tasks`, `forge_task`, `forge_task_diff`, `forge_dossier`, `forge_status`,
  `forge_develop`, `forge_task_note`, `forge_submit_branch` (Hephaestus), `system_status`, `system_log` (Argus),
  `settings_search`, `settings_get`, `settings_propose` (Themis), `memory_note` (write), `memory_recall` (Oracle:
  conversations with an external AI end up in Hestia's memory, page Memoria). Approve, reject, merge and rollback never leave.

## OAuth 2.1 (claude.ai web/mobile, ChatGPT)

`app/core/oauth.py` — SPEC §B3, §B6. For clients that only speak OAuth; everything public goes through the WebUI door
(`OAuthDoorController`), which passes the address it was reached at in `X-Hestia-Public-Base` (issuer, metadata).
- Metadata: `/.well-known/oauth-protected-resource[/mcp]` (RFC 9728), `/.well-known/oauth-authorization-server`
  (RFC 8414). Dynamic registration `/oauth/register` (RFC 7591): redirect URIs https, or http only on loopback; 10
  registrations a minute; clients `hmc_…` (public id; a secret only for confidential clients, stored hashed).
- `/oauth/authorize` checks client, exact redirect_uri (an unknown one is never redirected to) and PKCE **S256 only**,
  then parks the request (15 min, in memory): **no code without the consent card**. The WebUI sends the browser to
  *Accessi AI* (`?oauth=<id>`, behind its login); *Consenti* (`POST /api/mcp/oauth/requests/{id}/approve`) issues a
  5-minute single-use code with the scope, tools, expiry and name picked there; *Rifiuta* → `access_denied`.
- `/oauth/token`: `authorization_code` (verifier, same redirect_uri, same client) → access token `hso_…`
  (`mcp.oauth.access_token_minutes`) + refresh token `hsr_…`; `refresh_token` rotates both every time. A replayed
  code or old refresh token **revokes the access**. `/oauth/revoke` (RFC 7009) stops the whole grant.
- A grant is an access of kind `oauth` in the same list: same checks on `/mcp/external` (scope, tools, expiry, rate
  limit, audit), *Revoca*, *Riattiva* (back on for 90 days, the AI keeps its refresh token), *Elimina*.
- Logs: `event=mcp_oauth_client_registered|consent_asked|consent_given|consent_denied|token_refreshed`,
  `event=mcp_oauth_token_refused error=`, `event=mcp_oauth_access_revoked_on_replay`.

**Servizi esterni** (`GET /api/mcp/outbound`): third-party MCP servers Hestia may use, read from Hecate
(`/api/gateway/outbound/mcp`, credentials in Hecate's `.env` only): names, host, key yes/no.

**WebUI plugin** (core module, *Sistema*, bundle `ui/` → `/ui/dist/webui/mcp.js`, outside `/code` so the compose dev
mount does not hide it):
- page *Comandi & MCP* (`comandi` → `mcp-commands`, order 190; ported from the built-in WebUI page, SPEC §A4): every
  tool the WebUI sees grouped by module, search, description, `METHOD path`, arguments from the JSON schema (enum →
  select, boolean → sì/no, array/object → JSON or `a, b, c`), *Esegui* (a tool that changes something asks first),
  raw result; tools with `response_mode=oracle_natural` then get Oracle's readable text (second call, own 30 s budget
  of the WebUI proxy); *Chiedi a Hestia* opens the assistant with the tool as context. Reads `/api/mcp/ui/tools…`
  (`core/ui_tools.py`): the same `MCPServer.tools_list` / `tools_call` as `/mcp` with client `webui` (same visibility,
  `X-Hestia-Client: webui` towards the module), call timeout 20 s.
- sub-page *Accessi AI* (`accessi` → `mcp-accesses`, parent `comandi`): new token with the ready `claude mcp add` line
  and JSON config, revoke, renew, delete, tool choice; OAuth consent card when opened with `?oauth=<id>`; badge
  *OAuth* on grants; *Servizi esterni* list.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mcp` | MCP, Streamable HTTP with JSON answers: `initialize`, `tools/list`, `tools/call`, `ping`; batches; notifications → 202 |
| `GET` | `/mcp` | 405 (no server stream) |
| `POST` | `/mcp/external` | Same MCP for external AIs, `Authorization: Bearer <token>` (reached only through the WebUI door) |
| `GET` | `/api/mcp/accesses` | Accesses (no tokens, no hashes) |
| `GET` | `/api/mcp/accesses/tools` | Tools open to external AIs (what an access can be limited to) |
| `POST` | `/api/mcp/accesses?base_url=` | New access `{name, scope, tools, expires_days}` → `{access, token, setup}` (token shown once) |
| `PATCH` | `/api/mcp/accesses/{id}` | Change name, scope, tools, expiry |
| `POST` | `/api/mcp/accesses/{id}/revoke` · `/renew` | Stop it at once · new token (old one stops) |
| `DELETE` | `/api/mcp/accesses/{id}` | Remove it |
| `GET` | `/.well-known/oauth-protected-resource[/mcp]` · `/.well-known/oauth-authorization-server` | OAuth metadata (base from `X-Hestia-Public-Base`) |
| `POST` | `/oauth/register` · `/oauth/token` · `/oauth/revoke` | OAuth 2.1 (form or JSON) |
| `GET` | `/oauth/authorize` | `{status: consent, request_id}` or `{status: error, …, redirect?}` (the WebUI door turns it into redirects) |
| `GET` | `/api/mcp/oauth/requests/{id}` · `POST …/approve` · `…/deny` | Consent card (WebUI only) |
| `GET` | `/api/mcp/oauth/clients` | Registered OAuth clients |
| `GET` | `/api/mcp/outbound` | Servizi esterni (from Hecate) |
| `GET` | `/api/mcp/ui/tools` | Comandi page: tools the WebUI sees, as commands `{command, title, description, service, method, path, response_mode, writes, arguments_schema}` + `services` |
| `POST` | `/api/mcp/ui/tools/call` | Run one `{command, args}` as client `webui` → `{ok, result, error?, status_code, response_mode}`; hidden/unknown → 404 |
| `POST` | `/api/mcp/ui/tools/format` | `{command, result, response_prompt?}` → Oracle `/api/format` via Hub → `{ok, text}` (plain text; failure → `ok:false`) |
| `GET` | `/api/ui/manifest` · `/ui/webui/{file}` | Plugin manifest and bundle |
| `GET` | `/health` | Service health |
| `GET` | `/api/logs` | Filterable log buffer |

Protocol versions: `2025-06-18` (default), `2025-03-26`, `2024-11-05`. Logs: `event=mcp_tool_call tool= service= client= ok= status= ms=`,
`event=mcp_external_call`, `event=mcp_external_denied reason=`, `event=mcp_external_rate_limited`, `event=mcp_access_created|revoked|renewed`, `event=ui_tool_run tool= ok=`, `[🔄] event=ui_tool_format_failed`.

## Constraints
- Never executes a tool itself: always through Hub routing.
- One server for every client: no client gets its own tool list format or resolver.

## Central settings (Themis)

Declared in `app/core/mcp_settings.py` (`SettingsClient("mcp")`, router `GET /api/settings/effective`,
`POST /api/settings/reload`). All `apply=live` (read at use time).

| Key | Type / default | Effect |
|---|---|---|
| `mcp.tools.cache_ttl` | int 60 s | How long tool manifests stay cached |
| `mcp.discovery.hub_timeout` | int 8 s | Timeout of the Hub registry lookup |
| `mcp.calls.timeout` | int 10 s | Default timeout of a tool call (a caller may ask more in `_meta.hestia.timeout_seconds`, max 300) |
| `mcp.external.max_calls_per_min` | int 60 /min | Messages a minute per external access; over it → 429 |
| `mcp.oauth.access_token_minutes` | int 60 min (5–1440) | Life of an OAuth access token (`hso_…`); the refresh token renews it |
| `mcp.log.level` | enum (boot = `LOG_LEVEL`) | Log verbosity |

Env keeps only infrastructure: `HUB_API_URL`, `MCP_SERVICE_BASE_URL`, `MCP_SERVICE_VERSION`,
`MCP_UI_DIST` (set by the Dockerfile), `LOG_LEVEL` (boot default only). No token in env: accesses are data.
