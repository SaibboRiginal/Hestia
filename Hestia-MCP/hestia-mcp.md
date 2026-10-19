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

Python clients use `hestia_common.mcp_client.MCPClient(HUB_API_URL, client=…)` (`list_tools`, `call`, `as_command`);
the WebUI uses `HubClient.McpListToolsAsync` / `McpCallToolAsync`.

## External AIs (accesses)

`app/core/access.py`, `app/core/external.py` — SPEC §B2, §B6.

- **Door**: WebUI `POST /mcp` (the only service behind the tunnel; no WebUI login there) forwards body +
  `Authorization: Bearer <token>` through Hub to `POST /mcp/external` here. The internal `/mcp` is never exposed.
- **Access** = name, scope `read` | `write`, tools (`[]` = every tool opened to external AIs), expiry, last use, calls
  today. Stored in Archive (`/api/mcp-access-store`); the token (`hst_…`) is shown once and stored only as sha256.
  Lookups are cached 30 s; revoke / renew / delete here drop the cache, so they take effect at once.
- **Answers**: wrong, revoked or expired token → 401 (`WWW-Authenticate: Bearer`); more than
  `mcp.external.max_calls_per_min` messages a minute per access → 429 (`Retry-After: 60`); a `read` access calling a
  write tool → 403 (and `tools/list` shows it only reading tools); a tool outside the access → "Unknown tool".
- **Towards the module** an external call carries only `X-Hestia-Access: <access name>` (never session, chat or
  client from the caller): Forge files `forge_develop` as an external proposal, Themis shows "<name> (AI esterna)".
- **Audit**: `event=mcp_external_call access= tool= ok=`; a successful write also leaves a silent Hermes inbox entry
  (`/api/dispatch/send` with `metadata.quiet`), no push.
- Tools open to external AIs today: `forge_tasks`, `forge_task`, `forge_task_diff`, `forge_dossier`, `forge_status`,
  `forge_develop`, `forge_task_note`, `forge_submit_branch` (Hephaestus), `system_status`, `system_log` (Argus),
  `settings_search`, `settings_get`, `settings_propose` (Themis). Approve, reject, merge and rollback never leave.

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
  and JSON config, revoke, renew, delete, tool choice.

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
| `mcp.log.level` | enum (boot = `LOG_LEVEL`) | Log verbosity |

Env keeps only infrastructure: `HUB_API_URL`, `MCP_SERVICE_BASE_URL`, `MCP_SERVICE_VERSION`,
`MCP_UI_DIST` (set by the Dockerfile), `LOG_LEVEL` (boot default only). No token in env: accesses are data.
