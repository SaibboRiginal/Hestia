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
                               Oracle /api/chat  (primary)
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

### Query parameters for `/api/argus/logs`

| Param | Default | Description |
|-------|---------|-------------|
| `service` | — | Filter by service name (e.g. `scout`) |
| `level` | `WARNING` | Minimum severity: `WARNING`, `ERROR`, `CRITICAL` |
| `since` | `30m` | Time window: `30m`, `1h`, `2h` etc. |

## Hub Registration

- **Service name**: `argus`
- **Tags**: `core`, `monitoring`
- **Capabilities**: `argus.status`, `argus.logs`, `argus.analyze`
- **Telegram commands**: `system_status`, `system_log`, `system_analysis`, `system_remediate`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub base URL |
| `ARGUS_SERVICE_BASE_URL` | `http://hestia_argus:19008` | This service's externally reachable URL |
| `ARGUS_PORT` | `19008` | Listening port |
| `ARGUS_POLL_INTERVAL` | `60` | Seconds between health polls |
| `ARGUS_LOG_SOURCE` | `hub` | Log source mode: `hub` (via Hub `/api/monitor/logs`) or `docker` |
| `ARGUS_HUB_LOG_LIMIT` | `200` | Per-service max log rows fetched from Hub for each polling cycle |
| `ARGUS_LOG_SEEN_CACHE_SIZE` | `5000` | In-memory dedupe window for hub-sourced log alerts |
| `ARGUS_LOG_BUFFER_SIZE` | `500` | Max log events kept per container |
| `ARGUS_IGNORE_HEALTH_ACCESS` | `true` | Ignore container health-check access lines (e.g. `GET /health`) during log monitoring |
| `ARGUS_NOTIFY_TARGET` | — | Telegram chat_id for proactive alerts (optional) |
| `ORACLE_API_URL` | `http://hestia_oracle:19004/api/chat` | Oracle endpoint for alert dispatch |
| `ARGUS_AUTO_REMEDIATE_ENABLED` | `1` | Enable automatic remediation intent emission to Hephaestus on newly unhealthy service states |
| `ARGUS_AUTO_REMEDIATE_DRY_RUN` | `1` | Send remediation intents in dry-run mode |
| `ARGUS_AUTO_REMEDIATE_ENVIRONMENT` | `dev` | Target environment passed to Hephaestus remediation tasks |
| `ARGUS_REMEDIATE_TIMEOUT_SECONDS` | `15` | Hub-routed timeout for Hephaestus remediation request |

## Docker

When `ARGUS_LOG_SOURCE=docker`, Argus requires access to the Docker socket for log streaming:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

## Alert Flow

1. Monitor loop detects a service is down or degraded.
2. `alert_worker.send_alert()` POSTs a descriptive prompt to Oracle `/api/chat`.
3. Optional: Argus emits a structured remediation intent for Hephaestus (policy-gated).
4. Oracle processes the prompt and dispatches a response via Hermes to Telegram.
5. If Oracle is unreachable, a **TODO stub** logs the failure — direct Telegram Bot API
   fallback is not yet implemented.

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
