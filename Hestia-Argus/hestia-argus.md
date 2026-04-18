# Hestia-Argus

> All-seeing system watchman for the Hestia ecosystem.

## Purpose

Argus continuously monitors every Hestia service by polling their `/health` endpoints and
streaming Docker container logs. When an issue is detected it alerts the operator via the
Oracle → Hermes → Telegram chain. Argus also exposes an on-demand HTTP API so the Oracle
chatbox and Telegram commands can query the current system state at any time.

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
Docker Log Tails (per container)│
    │                           │
    └──────────► Monitor Loop ──┴──► Alert Worker
                                         │
                               Oracle /api/chat  (primary)
                               Direct Telegram   (TODO stub)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Argus own health check |
| GET | `/api/argus/status` | Live health snapshot of all services |
| GET | `/api/argus/logs` | Recent filtered log events (params: `service`, `level`, `since`) |
| POST | `/api/argus/analyze` | Full system analysis report |

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
- **Telegram commands**: `system_status`, `system_logs`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub base URL |
| `ARGUS_SERVICE_BASE_URL` | `http://hestia_argus:19008` | This service's externally reachable URL |
| `ARGUS_PORT` | `19008` | Listening port |
| `ARGUS_POLL_INTERVAL` | `60` | Seconds between health polls |
| `ARGUS_LOG_BUFFER_SIZE` | `500` | Max log events kept per container |
| `ARGUS_NOTIFY_TARGET` | — | Telegram chat_id for proactive alerts (optional) |
| `ORACLE_API_URL` | `http://hestia_oracle:19004/api/chat` | Oracle endpoint for alert dispatch |

## Docker

Argus requires access to the Docker socket for log streaming:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

## Alert Flow

1. Monitor loop detects a service is down or degraded.
2. `alert_worker.send_alert()` POSTs a descriptive prompt to Oracle `/api/chat`.
3. Oracle processes the prompt and dispatches a response via Hermes to Telegram.
4. If Oracle is unreachable, a **TODO stub** logs the failure — direct Telegram Bot API
   fallback is not yet implemented.
