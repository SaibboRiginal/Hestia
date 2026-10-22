# Hestia-Argus

> All-seeing system watchman for the Hestia ecosystem.

## Purpose

Argus continuously monitors every Hestia service by polling their `/health` endpoints and
collecting runtime logs (Hub monitor API by default, Docker tailing as fallback). When an issue is detected it alerts the user
through **Hermes** (every client); Oracle only writes the text, with a fixed text when it cannot. Oracle itself down
→ *Oracle offline* (below). Argus also exposes an on-demand HTTP API so the Oracle
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
                     text: Hub route -> Oracle /api/llm/generate
                           (fixed text when Oracle fails or Oracle is offline)
                     send: Hub route -> Hermes /api/events/ingest
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
| POST | `/api/argus/recheck/{service}` | Repair follow-up (fired by the agenda, or *Ricontrolla* in the WebUI): up → close + recovery notice; still down → new repair request + next recheck. Answer carries `health` and a short `message` (toast) |
| GET | `/api/argus/overview` | Last monitor cycle, no network: `total`, `healthy`, `unhealthy`, `unhealthy_services[]`, `open_incidents`, `last_cycle_at`, `last_cycle_ms`, `cycles` (widget *Stato sistema*) |
| GET | `/api/argus/history` | Health per service over time (`minutes` 5–1440, default 360; `buckets` 1–240, default 60): per service `status`, `error`, `checked_at`, `strip` (one char per bucket, worst status: `u` up · `w` degraded · `d` down · `-` no data), `uptime_pct`, `incident_open` |
| GET | `/api/argus/incidents` | `open[]` and `recent[]` (closed, `limit` ≤ 50) incidents, each with `actions[]` = what Argus did (`detected`, `status`, `alert`, `remediation`, `recheck_planned`, `recheck`, `recovered`; `ok` when known) |
| GET | `/api/argus/recheck-targets` | `{items: [{id, label, icon, state, hint}]}` — one *Ricontrolla* chip per service that is not up (quick-action `source`) |
| GET | `/api/ui/manifest` · `/ui/webui/{file}` | WebUI plugin manifest and bundle (`argus.js`) |

### Query parameters for `/api/argus/logs`

| Param | Default | Description |
|-------|---------|-------------|
| `service` | — | Filter by service name (e.g. `scout`) |
| `level` | `WARNING` | Minimum severity: `WARNING`, `ERROR`, `CRITICAL` |
| `since` | `30m` | Time window: `30m`, `1h`, `2h` etc. |

## WebUI plugin (core, *Sistema*)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Action history icons: detected alert, status arrows-v, alert bell, remediation wrench, recheck pulse, recovered check-circle; a failed action shows x-circle (danger).

Argus ships its "inside view" on the client plugin contract (`hestia_common.plugin_client`, `kind="core"`, order
110; SPEC `docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2/A6). Manifest: `app/core/ui_plugin.py` (its
`ui_manifest`/`ui_version` go in the Hub registration capabilities). Bundle: `ui/` (Lit, `@hestia/webui-sdk`) built in
the Docker image's Node stage to `/ui/dist/webui/argus.js` (`ARGUS_UI_DIST`, outside `/code` so the dev mount does
not hide it). `api_prefix` = `/api/argus/` (no duplicate endpoints).

| Contribution | Element | What |
|---|---|---|
| Page *Salute* (`salute`) | `argus-health` | KPI tiles; open incidents with the timeline of what Argus did; health strip per service over 1/6/24 h with uptime %; closed incidents; log viewer (service, minimum level, period, text search) over `/api/argus/logs`; *Ricontrolla* per service (confirm when not up: it may re-request the repair) |
| Widget *Stato sistema* (`stato`, auto, s/m/l) | `argus-status-widget` | healthy / total, services not up, open incidents (`/api/argus/overview`) |
| Quick action *Ricontrolla* (`ricontrolla`) | — | `POST /api/argus/recheck/{id}`, chips from `/api/argus/recheck-targets` (only services that are not up) |

History and incidents (`app/services/health_history.py`) are **in memory**: one sample per service per minute
(worst status), 24 h kept; 50 closed incidents kept. A restart starts empty (Argus owns no DB). Fed by the monitor
cycle (`record_cycle`, `note_unhealthy`/`note_action`/`note_recovered`) and by `recheck`. Logs:
`event=argus_incident_opened` / `event=argus_incident_closed`. Module stopped → the page/widget show
"Argus non raggiungibile".

## Hub Registration

- **Service name**: `argus`
- **Tags**: `core`, `monitoring`
- **Topology tags**: `layer:foundation`, `domain:observability`, `status:stable`
- **Capabilities**: `argus.status`, `argus.logs`, `argus.analyze`
- **Telegram commands**: `system_status`, `system_log`, `system_analysis`, `system_remediate`
- **External AIs** (MCP access, 2026-10-18): `system_status` and `system_log` are marked `"external"` (read only)

## Environment Variables

Env holds only infrastructure; every tunable is a central setting (below).

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub base URL |
| `ARGUS_SERVICE_BASE_URL` | `http://hestia_argus:19008` | This service's externally reachable URL |
| `ARGUS_PORT` | `19008` | Listening port |
| `ORACLE_ROUTE_PATH` | `api/llm/generate` | Hub-routed Oracle path for alert narration/analysis (plain generation; no classifier/tools; use case `argus.analisi`, declared in the Hub registration, chain chosen in Oracle → Modelli) |
| `HESTIA_DOCS_PATH` | `/hestia_root` | Repo mount used to load project docs as Oracle context |
| `STARTUP_WAIT_TIMEOUT_SECONDS` | `0` | Wait for Hub readiness at startup (0 = indefinitely) |
| `LOG_LEVEL` | `INFO` | Boot log level only (live: `argus.log.level`) |
| `ARGUS_UI_DIST` | `/ui/dist` | WebUI plugin bundle folder (set in the Dockerfile; infra only) |

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
| `argus.oracle.grace` | int (s) | `60` | Oracle down this long → presence signal `oracle.offline` + Hermes notice (0 = at once); also used for «Limitato» |
| `argus.repair.max_restarts` | int | `3` (0–5) | Immune system: container restarts of a down module before giving up (0 = never restart) — depends on `remediate.enabled` |
| `argus.repair.restart_after` | int (s) | `120` (30–3600) | Immune system: down this long → first restart; then the wait doubles |
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

1. Monitor loop detects a service is down or degraded (or new WARNING+ log lines).
2. `alert_worker.send_alert()` dedupes (cooldown) and batches (`argus.alerts.batch_window`).
3. The batch text is written by Oracle (`/route/oracle/api/llm/generate`, plain generation); if Oracle fails or is
   offline, a fixed grouped text is used at once.
4. Argus publishes the event to **Hermes** (`service.health`, `_message` = the text): Hermes delivers it to every
   client (Telegram, WebUI). Argus never talks to Telegram directly (Hermes is the only outbound messenger).
5. Optional: Argus emits a structured remediation intent for Hephaestus (policy-gated) and plans agenda rechecks.

## Oracle offline (Oracle down)

SPEC `docs/work/2026-10-19-oracle-offline` (v2.0), code `app/services/oracle_watch.py`, fed by the monitor cycle and
`recheck/oracle` (no loop of its own).
- Oracle unhealthy or missing from the Hub registry for `argus.oracle.grace` s (60) → presence signal
  `oracle.offline = true` (meta `reason` unreachable/unhealthy/unregistered, `since`; refreshed every 10 min, TTL 30
  min) → Chronos overlay «⏳ Non disponibile» (effect `chat.reply = queued`, proactive work deferred).
- Same moment, one Hermes notice with fixed text (event `service.action_required`, the system subscription every
  client always has, unlike the opt-in `service.health` alerts; `replaces: "system.oracle"`, one live notice). Oracle back → signal
  cleared and the notice closed (`closes: "system.oracle"`) with «✅ Di nuovo disponibile dopo N min». Chronos then asks
  the chat clients to answer the messages they queued (`chat_queue_drain`).
- Oracle's generic `service.health` alert/recovery is not sent (the Oracle notice replaces it); repair requests and
  agenda rechecks stay as for any service. A shorter outage (restart, deploy) says nothing.
- While offline Argus never asks Oracle to write a text (no 60 s waits). Logs: `event=oracle_offline`,
  `event=oracle_online`.
- Oracle's `/health` carries `models` (`ok` · `limited` · `none`, v3 E). `none` (no model left in any chain) counts as
  offline with reason `no_models`. `limited` (only fallback models answer) for the grace time → signal
  `oracle.limited` (overlay «Limitato»: heavy work deferred, short answers) and one notice «🔋 Limitato…»
  (`replaces: "system.oracle"`); back to `ok` → signal cleared and «✅ Di nuovo al completo» (`closes`).

## Immune system (v3 B, `app/services/immune.py`)

Each monitor cycle calls `immune.observe(service, healthy)`. A module down for `argus.repair.restart_after` s (120) is
restarted through the Hub on Hephaestus (`POST /api/hephaestus/restart`, Docker socket), then again after double the
wait, up to `argus.repair.max_restarts` (3). Never acts on argus, hephaestus or hub; a module Forge is deploying is
skipped (does not use up a try). After the last try: one Hermes notice «Una parte di Hestia non riparte da sola»
(key `system.repair.<svc>`); back healthy → «Tornato a posto» closes it. Restarts run in a thread, logs
`event=immune_restart`, `event=immune_gave_up`.

## Journal (v3 F, «Registro» in the Salute page)

The incidents of `health_history` (down, restart, restart result, gave up, recovered) are the journal of notable
events. They persist in Archive (`/api/argus-store`, kind `incident`; the last 200 closed kept) and are reloaded at
startup, so the «Registro» survives restarts. Hermes notices stay for what needs you; the journal is the history,
shown with an icon per action (`/api/argus/incidents?limit=` up to 200).

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

## Assistant presence

Argus reports the number of degraded services to Chronos presence (`health.degraded_services`, on change or every 10 min, ttl 30 min): enough of them make the assistant «Stanco». Oracle down past the grace → `oracle.offline` (see *Oracle offline*): overlay «Non disponibile».
