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
| `GET` | `/api/discovery/catalog` | **One catalog** organized by client × type (`?client=webui&type=page,widget&module=scout`): `tool` (MCP, client `*`), `command`, and the UI contributions `page` · `widget` · `quick_action` · `bundle` read from each module's `capabilities.ui_manifest` (cached 5 min, refetched when `ui_version` changes). Offline modules keep their last manifest with `online: false`. Each module carries `kind` (`domain` · `core`: the WebUI shows core modules under *Sistema*) and pages may carry `badge {source, field}`. Contract: `docs/work/2026-10-17-client-plugins/SPEC.md` §4.2 |
| `ANY` | `/api/route/{service}/{path:path}` | Proxy request to named service/path. Two styles: **envelope** (POST `{method, headers, query, body, timeout_seconds}`) or **direct passthrough** (real method + query string + raw JSON body; timeout via `X-Hub-Timeout-Seconds`, default 8s). Response is always `{status_code, service, target, payload}` |
| `GET` | `/api/ui/map` | *Mappa* read model (WebUI plugin): every service (newest instance, `instances` count) **plus Hub itself**: `online` (re-registered in the last 180 s), `node` (`capabilities.node` or base-URL host), `version`, `last_heartbeat`, `age_seconds`, `topology_tags` + parsed `topology`, `has_ui`, `has_mcp`; top level `revision`, `updated_at`, `online_count`, `offline_count`. `?probe=true` also calls each health endpoint in parallel (`health`: healthy · degraded · unavailable) |
| `GET` | `/api/ui/manifest` | Hub's own plugin manifest (also folded into the catalog in-process) |
| `GET` | `/ui/webui/{file}` | Hub's plugin bundle file (`hub.js`) |
| `GET` | `/health` | Hub health |

---

## WebUI plugin (core, *Sistema*)

Hub ships its own "inside view" on the client plugin contract (`hestia_common.plugin_client`, `kind="core"`,
order 100; SPEC `docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2). Code: `src/modules/inside.py` (manifest +
read model), bundle `ui/` (Lit, `@hestia/webui-sdk`) built in the Docker image's Node stage to `/ui/dist/webui/hub.js`
(`HUB_UI_DIST`, outside `/code/src` so the dev mount does not hide it). `api_prefix` = `/api/ui/`.

| Contribution | Element | What |
|---|---|---|
| Page *Mappa* (`mappa`) | `hub-map` | Every service: online/offline, node, version, last heartbeat, topology tags, instances, UI/MCP badges; group by layer / node / type, search; *Verifica salute* = `GET /api/ui/map?probe=true`. Hub unreachable → "Hub non raggiungibile" state |
| Widget *Servizi online* (`online`, auto, s/m) | `hub-online-widget` | online / total + the offline ones by name |

Hub never registers with itself, so two things are done in-process:
- **Catalog**: `discover_catalog(..., local_manifests={"hub": manifest})` adds Hub's manifest (always `online`;
  wins over a registered service with the same name).
- **Routing**: `/api/route/hub/<path>` (unicast, when no service named `hub` is registered) is answered by
  `inside.local_route` — `GET /api/ui/manifest`, `GET /api/ui/map`, `GET /ui/<client>/<file>` (non-JSON as
  `{"raw": text}`, like a proxied module); other paths 404, other methods 405. `target` = `"local"`.
  This is what the WebUI plugin proxy and bundle loader use (`RouteRawAsync("hub", …)`).

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
`tests/test_compose_registration_tags.py` validates every compose service's tags against these lists. Plutus
(`finance`, 2026-10-19, then `voice` for Echo on `layer:cognition`, 2026-10-22) were the latest: a new domain module adds its tag to `ALLOWED_TAGS` and `domain:` here.

Tag `coach` (2026-10-20): a module that serves `GET /api/coach/needs` (`hestia_common.coach`) carries it; Chronos
finds the coaches of the weekly plan with `GET /registry/services` filtered on this tag. `test_coach_modules_carry_the_coach_tag`
checks Hercules, Hygieia and Plutus.

`capabilities.owns_tool_domains: [...]` lets a non-`layer:domain` service own a tool domain in Oracle's tool
filtering (Argus and Hephaestus own `system`, so Forge/system tools reach the LLM).
