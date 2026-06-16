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
- Tool manifests cached with configurable TTL (default 60s)
- Registry refreshed on Hub service changes

### Tool Proxy
- Proxies tool calls from Oracle to target services via Hub routing
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
