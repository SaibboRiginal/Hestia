# Hestia-Hub 🔀

**Role:** Generic Service Registry + Internal Gateway
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

Hub is the internal control plane of Hestia.
- Registers service instances.
- Exposes capability/discovery views.
- Routes internal HTTP requests by logical service name.

Hub is **fully generic**: no domain, no DB, no user/business logic.

---

## Core Features

### Registry
- `register` / `deregister` service instances.
- Keep metadata: name, base URL, health endpoint, tags, capabilities.

### Discovery
- Provide service list.
- Provide module-tools discovery for Oracle (`domain -> endpoint`).

### Routing
- Proxy request to target service by name and path.
- Return structured unavailability errors when target is offline.

### Health Snapshot
- Poll or cache health status for each registered service.

---

## API (MVP)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/registry/register` | Register/update one service |
| `POST` | `/api/registry/deregister` | Deregister one service |
| `GET` | `/api/registry/services` | List registered services |
| `GET` | `/api/discovery/module-tools` | Domain to module-tool endpoint map |
| `GET` | `/api/discovery/commands` | Commands from inline `capabilities.commands` + MCP tools (`?client=`) |
| `GET` | `/api/discovery/catalog` | **One catalog** organized by client × type (`?client=webui&type=page,widget&module=scout`): `tool` (MCP, client `*`), `command`, and the UI contributions `page` · `widget` · `quick_action` · `bundle` read from each module's `capabilities.ui_manifest` (cached 5 min, refetched when `ui_version` changes). Offline modules keep their last manifest with `online: false`. Contract: `docs/work/2026-10-17-client-plugins/SPEC.md` §4.2 |
| `ANY` | `/api/route/{service}/{path:path}` | Proxy request to named service/path. Two styles: **envelope** (POST `{method, headers, query, body, timeout_seconds}`) or **direct passthrough** (real method + query string + raw JSON body; timeout via `X-Hub-Timeout-Seconds`, default 8s). Response is always `{status_code, service, target, payload}` |
| `GET` | `/health` | Hub health |

---

## Constraints

- No persistence dependency.
- No domain logic.
- Stateless restart-safe behavior (services re-register on startup).


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Registration validation (read this when a service "disappears")

Hub **rejects** a registration (422) when topology tags repeat a dimension or use a value outside
`ALLOWED_TOPOLOGY_DIMENSIONS`, or when `tags` miss the `service_type`. The service only logs a warning and is
unreachable through Hub. Argus (duplicate `layer:`/`domain:` + `domain:system`) and Metis (`domain:improvement`,
`status:alpha`) were rejected this way; fixed by tag cleanup and by adding `system`, `improvement`, `alpha`.
Themis (`settings` tag, `layer:core`, `domain:settings`) and Metis (`improvement` tag) had the same fate: `settings` and
`improvement` added to `ALLOWED_TAGS`, `settings` to `domain:`, Themis moved to `layer:foundation`. The unit test
`tests/test_compose_registration_tags.py` validates every compose service's tags against these lists.

`capabilities.owns_tool_domains: [...]` lets a non-`layer:domain` service own a tool domain in Oracle's tool
filtering (Argus and Hephaestus own `system`, so Forge/system tools reach the LLM).
