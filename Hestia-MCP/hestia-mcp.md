# Hestia-MCP — Model Context Protocol Gateway

**Role:** Hestia's one MCP server — the single way every client lists and runs tools.
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker
**Port:** 19013

---

## Responsibility

**Hestia's one MCP server.** Every client lists and runs tools here, the same way
(`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §B2): Oracle's agent loop, Telegram's command menu, the WebUI
*Comandi* page and (P3) external AIs such as Claude. Before 2026-10-18 there were four ways (Oracle read Hub
`/discovery/commands` and filled templates itself, Telegram read `/tools/all`, the WebUI had its own resolver,
`/tools/call` had a fourth copy); they are gone.

- **Catalog**: Hub's registry discovery (`/discovery/commands`: each module's own `/mcp` tools + inline
  `capabilities.commands`) turned into MCP tool descriptors (`app/core/catalog.py`), cached `mcp.tools.cache_ttl`.
  Hestia details stay in `_meta.hestia` (service, method, path, response mode/prompt, clients, Telegram menu fields).
- **Visibility**: a client sees tools whose `clients` is empty, `*` or its own key (`telegram`; `webui` = `ui`);
  `oracle` sees all (it filters by domain owner itself). The client names itself with `X-Hestia-Client`.
- **Execution**: `tools/call` builds the request with `hestia_common.tool_call` (path `$x`/`{x}`, templates
  `$session_id` · `$chat_id`/`$owner` · `$arg.x`, rest → query or JSON body) and routes it through Hub with
  `X-Session-Id`, `X-Trace-Id` and `X-Hestia-Client` (= the client the user talks from, given by the caller).
- Read tools carry `annotations.readOnlyHint: true` (same rule Oracle used for "writes").

Python clients use `hestia_common.mcp_client.MCPClient(HUB_API_URL, client=…)` (`list_tools`, `call`, `as_command`);
the WebUI uses `HubClient.McpListToolsAsync` / `McpCallToolAsync`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mcp` | MCP, Streamable HTTP with JSON answers: `initialize`, `tools/list`, `tools/call`, `ping`; batches; notifications → 202 |
| `GET` | `/mcp` | 405 (no server stream) |
| `GET` | `/health` | Service health |
| `GET` | `/api/logs` | Filterable log buffer |

Protocol versions: `2025-06-18` (default), `2025-03-26`, `2024-11-05`. Logs: `event=mcp_tool_call tool= service= client= ok= status= ms=`.

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
| `mcp.log.level` | enum (boot = `LOG_LEVEL`) | Log verbosity |

Env keeps only infrastructure: `HUB_API_URL`, `MCP_SERVICE_BASE_URL`, `MCP_SERVICE_VERSION`,
`LOG_LEVEL` (boot default only).
