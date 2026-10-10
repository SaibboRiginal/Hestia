# Hestia-Argus

> All-seeing system watchman for the Hestia ecosystem.

## Purpose

Argus continuously monitors every Hestia service by polling their `/health` endpoints and
collecting runtime logs (Hub monitor API by default, Docker tailing as fallback). When an issue is detected it alerts the operator via the
Oracle → Hermes → Telegram chain. Argus also exposes an on-demand HTTP API so the Oracle
chatbox and Telegram commands can query the current system state at any time.

Argus is the only monitoring authority. It does not execute code fixes; instead it emits remediation intents for execution services (Hephaestus).

## Port

| Context | Port |
|---------|------|
| Docker  | **19008** |

## Architecture

```
Hub registry
    │
    ▼
Health Poller ──────────────────┐
    │                           │
Hub Monitor Logs / Docker Tails │
    │                           │
    └──────────► Monitor Loop ──┴──► Alert Worker
                                         │
                               Hub route -> Oracle /api/chat
                               Direct Telegram   (TODO stub)
                                         │
                               Remediation Intent Dispatcher
                                         │
                               Hub route -> Hephaestus remediation APIs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Argus own health check |
| GET | `/api/argus/status` | Live health snapshot of all services |
| GET | `/api/argus/logs` | Recent filtered log events (params: `service`, `level`, `since`) |
| POST | `/api/argus/analyze` | Full system analysis report |
| POST | `/api/argus/remediate` | Forward remediation intent to Hephaestus via Hub route |
| POST | `/api/argus/recheck/{service}` | Repair follow-up (fired by the agenda): up → close + recovery notice; still down → new repair request + next recheck |

### Query parameters for `/api/argus/logs`

| Param | Default | Description |
|-------|---------|-------------|
| `service` | — | Filter by service name (e.g. `scout`) |
| `level` | `WARNING` | Minimum severity: `WARNING`, `ERROR`, `CRITICAL` |
| `since` | `30m` | Time window: `30m`, `1h`, `2h` etc. |

## Hub Registration

- **Service name**: `argus`
- **Tags**: `core`, `monitoring`
- **Topology tags**: `layer:foundation`, `domain:observability`, `status:stable`
- **Capabilities**: `argus.status`, `argus.logs`, `argus.analyze`
- **Telegram commands**: `system_status`, `system_log`, `system_analysis`, `system_remediate`

## Environment Variables

Env holds only infrastructure; every tunable is a central setting (below).

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub base URL |
| `ARGUS_SERVICE_BASE_URL` | `http://hestia_argus:19008` | This service's externally reachable URL |
| `ARGUS_PORT` | `19008` | Listening port |
| `ORACLE_ROUTE_PATH` | `api/llm/generate` | Hub-routed Oracle path for alert narration/analysis (plain generation; no classifier/tools) |
| `HESTIA_DOCS_PATH` | `/hestia_root` | Repo mount used to load project docs as Oracle context |
| `STARTUP_WAIT_TIMEOUT_SECONDS` | `0` | Wait for Hub readiness at startup (0 = indefinitely) |
| `LOG_LEVEL` | `INFO` | Boot log level only (live: `argus.log.level`) |

## Central settings

Declared to Themis in `app/core/argus_settings.py` (`GET /api/settings/effective`, `POST /api/settings/reload`);
read at use time, so changes apply live unless marked *restart*. Safety switches are `oracle=read`
(the assistant can read them, never propose a change).

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `argus.poll.interval` | int (s) | `60` | Seconds between monitor cycles |
| `argus.auth_check.enabled` | bool | `true` | Periodic Google/Outlook provider auth check |
| `argus.auth_check.every_cycles` | int | `5` | Auth check every N monitor cycles |
| `argus.logs.source` | enum | `hub` | `hub` (Hub `/api/monitor/logs`) or `docker` (socket tail) |
| `argus.logs.hub_limit` | int | `200` | Max log rows per service per poll/report (hub source) |
| `argus.logs.seen_cache_size` | int | `5000` | Dedupe memory for hub-sourced log events (min 500) |
| `argus.logs.ignore_health_access` | bool | `true` | Drop `/health` access lines (docker source) |
| `argus.logs.ignore_patterns` | list | `["OUTLOOK_CLIENT_ID and OUTLOOK_TENANT_ID must be set"]` | Substrings whose lines are dropped (docker source) |
| `argus.logs.buffer_size` | int | `500` | Log events kept per container (docker source) — *restart* |
| `argus.logs.backfill_minutes` | int (min) | `0` | Past logs read on first poll of a container (docker source) |
| `argus.alerts.cooldown` | int (min) | `60` | Minimum time between repeated alerts with the same fingerprint |
| `argus.alerts.batch_window` | int (s) | `20` | Quiet time before a burst is sent as one notification |
| `argus.remediate.enabled` | bool | `true` | Auto remediation intents to Hephaestus — `oracle=read` |
| `argus.remediate.dry_run` | bool | `true` | Remediation intents in dry-run mode — `oracle=read` |
| `argus.remediate.environment` | enum | `dev` | `dev`/`staging`/`prod` forwarded to Hephaestus — `oracle=read` |
| `argus.remediate.timeout` | int (s) | `15` | Hub-routed timeout of the remediation request |
| `argus.repair.recheck` | int (min) | `10` | First agenda recheck after a service goes down (doubles each attempt) |
| `argus.repair.recheck_max` | int (min) | `360` | Backoff cap for agenda rechecks |
| `argus.forge.enabled` | bool | `true` | Recurring errors become Forge fix proposals — `oracle=read` |
| `argus.forge.threshold` | int | `3` | Occurrences of one signature inside the window |
| `argus.forge.window` | int (s) | `3600` | Counting window |
| `argus.forge.cooldown` | int (s) | `86400` | One proposal per signature per cooldown |
| `argus.log.level` | enum | `LOG_LEVEL` | Live log level |

## Docker

When `argus.logs.source=docker`, Argus requires access to the Docker socket for log streaming:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

## Alert Flow

1. Monitor loop detects a service is down or degraded.
2. `alert_worker.send_alert()` routes a descriptive prompt through Hub to Oracle (`/route/oracle/api/llm/generate`).
3. Optional: Argus emits a structured remediation intent for Hephaestus (policy-gated).
4. Oracle processes the prompt and dispatches a response via Hermes to Telegram.
5. If Oracle is unreachable, a **TODO stub** logs the failure — direct Telegram Bot API
   fallback is not yet implemented.

## Forge fix proposals

Recurring errors become fix *proposals* for Hephaestus Forge (`app/core/forge_proposer.py`):
- Same error signature (exception line, numbers/ids/quoted values stripped) from one service
  ≥ `argus.forge.threshold` (3) times within `argus.forge.window` (3600 s).
- Argus posts to `/api/hephaestus/forge/tasks` (source `argus`) with the log sample as context.
  Forge's permission mode decides (`ask` / `auto` / `full_auto`, defaults local=auto, cloud=ask).
- One proposal per signature per `argus.forge.cooldown` (86400 s). Failed posts retry on next occurrence.
- Disable with setting `argus.forge.enabled=false`. Hephaestus/Argus own errors are excluded.
- Log dedupe key now includes the row timestamp: each occurrence counts once (alert spam still bounded by alert cooldown).

## Repair follow-up (assistant agenda)

A service that stays unhealthy is never forgotten: when Argus requests the repair it also plans
**`argus.repair.<service>`** in Hestia's agenda (`argus.repair.recheck` = +10 min, then 20, 40 … max `argus.repair.recheck_max` = 6 h). Chronos fires
`POST /api/argus/recheck/{service}` through Hub; still down → new Hephaestus repair request and next recheck;
recovered → entry completed and recovery notice. Visible/movable/cancellable from the agenda.

## Remediation Contract

1. Argus detects and classifies incidents.
2. Argus requests remediation via Hub-routed Hephaestus endpoints.
3. Argus verifies post-remediation health/log recovery.
4. Argus never mutates source code or executes git/deploy operations directly.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
