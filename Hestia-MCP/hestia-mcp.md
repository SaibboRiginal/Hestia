# Hestia-MCP — Model Context Protocol Gateway

**Role:** Single tool source for the entire Hestia ecosystem.
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker
**Port:** 19013

---

## Responsibility

Aggregates MCP tools from all Hestia services and third-party MCP servers.
Provides domain-filtered tool manifests to Oracle's agent loop.
Replaces Hub's `/discovery/commands` as the canonical tool registry.

## Core Features

### Tool Aggregation
- Discovers tools from internal services via MCP `tools/list` protocol
- Falls back to Hub command discovery for services not yet migrated to MCP
- Supports third-party MCP server registration
- Domain-aware filtering: Oracle requests tools for `["scout", "chronos"]`, gets only relevant tools

### Caching
- Tool manifests cached with a configurable TTL (setting `mcp.tools.cache_ttl`, default 60 s)
- Registry refreshed on Hub service changes

### Tool Proxy
- Proxies tool calls to target services via Hub routing, using the `method` + `path` each tool declares
  (path vars `$x`/`{x}` filled from params; rest → query for GET/DELETE, JSON body otherwise).
  Previously it posted to a non-existent `/api/module-tools/call` endpoint, so every call failed.
- Single entry point for all tool execution

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health |
| `GET` | `/api/logs` | Filterable log buffer |
| `GET` | `/tools?domains=scout,chronos` | Tools for Oracle agent loop (domain-filtered) |
| `GET` | `/tools/all` | All tools (Telegram command catalog) |
| `POST` | `/tools/call` | Proxy a tool call to target service |

## Constraints
- Does not execute tools directly — always proxies via Hub routing
- Caches aggressively; TTL controls freshness vs latency trade-off
- MCP-native services take precedence over Hub-discovered commands

## Central settings (Themis)

Declared in `app/core/mcp_settings.py` (`SettingsClient("mcp")`, router `GET /api/settings/effective`,
`POST /api/settings/reload`). All `apply=live` (read at use time).

| Key | Type / default | Effect |
|---|---|---|
| `mcp.tools.cache_ttl` | int 60 s | How long tool manifests stay cached |
| `mcp.discovery.hub_timeout` | int 8 s | Timeout of the Hub registry lookup |
| `mcp.calls.timeout` | int 10 s | Timeout of MCP `tools/list` and of proxied tool calls |
| `mcp.log.level` | enum (boot = `LOG_LEVEL`) | Log verbosity |

Env keeps only infrastructure: `HUB_API_URL`, `MCP_SERVICE_BASE_URL`, `MCP_SERVICE_VERSION`,
`LOG_LEVEL` (boot default only).
