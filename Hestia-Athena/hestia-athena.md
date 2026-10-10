# Hestia-Athena

Role: Proactive cognition and advisory strategy engine.

Athena is the "thinking brain" of Hestia. It runs a periodic observation-and-reasoning
loop: gathers system state, generates action candidates via Oracle LLM, scores them
through a relevance gate, and emits accepted actions to Hermes. Every thinking cycle
is archived for audit and client display.

## Event contract
- Event type: `athena.focus_brief`
- Destination: Hermes `/api/events/ingest`
- Domain: cognition (or candidate-specific domain)
- Payload: brief + gate decision and component signals

## Gate factors
- urgency
- usefulness
- novelty
- interruption_cost
- confidence

Weighted score:
- 0.30 × urgency
- 0.25 × usefulness
- 0.20 × novelty
- 0.15 × confidence
- 0.10 × (1 − interruption_cost)

## Architecture (Phase 3)

```
┌─────────────────────────────────────────────────────┐
│                  Athena Runtime Loop                  │
│                                                       │
│  1. OBSERVE ──► Observer queries Hub, Archive, Argus │
│  2. THINK   ──► Strategist calls Oracle LLM          │
│  3. SCORE   ──► Relevance gate with retrospective    │
│  4. ACT     ──► Emit to Hermes, hint to Oracle       │
│  5. ARCHIVE ──► Store thinking record                 │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### Modules

| Module | File | Responsibility |
|--------|------|---------------|
| Observer | `app/core/observer.py` | Gather system state via Hub-routed calls to Archive, Argus, and self |
| Strategist | `app/core/strategist.py` | Call Oracle LLM for reasoning, parse structured action candidates |
| Runtime | `app/core/runtime.py` | Main loop: observe → think → score → act → archive |
| Schemas | `app/core/schemas.py` | Data models: RelevanceSignals, ObservationSnapshot, ActionCandidate, ThinkingRecord |

### Observation sources
- **Hub registry**: registered services, base URLs, types, tags, topology tags
- **Argus health**: per-service health status (up/down/degraded)
- **Archive entities**: domain summaries (counts, recent activity, pending steps)
  - Domains are **discovered dynamically** from Hub: services with `layer:domain` tag
    (e.g. Scout with `domain:real_estate`) map to Archive domains
  - No hardcoded domain list — if Hub is unreachable, domains are simply empty (logged)
- **Self-state**: active commitments, unresolved commitments, failure streaks
- **Settings (Themis)**: up to 12 proposable system settings as `key=value [scelte]` (not advanced, not personal)

### Strategist (LLM reasoning)
- Single Oracle round-trip per cycle via Hub routing (`POST /route/oracle/api/llm/generate`)
- Compact prompt format optimized for local models
- Structured `AZIONE:/TIPO:/PRIORITA:/DOMINIO:/MOTIVO:/RIASSUNTO:` output format
- Graceful responses: `NESSUNA_AZIONE` when nothing actionable, empty list on Oracle failure
- Oracle is a **core dependency** — if it is unreachable, Athena returns no candidates
  (the observation cycle still runs and is archived, but no static rules are substituted)

### Idle retrospective (autonomous mode)
- Cycles run **only when the user is idle**: Athena reads Oracle `GET /api/activity` and defers the cycle while the
  last real chat is younger than `athena.loop.idle_seconds` (default 300; `0` = always run). The local model is never
  contended with the user.
- Retrospective inputs on top of health/domains: **Argus errors of the last hour** (`/api/argus/logs?level=ERROR&since=1h`)
  and **Metis weak spots** (`/api/metis/insights`).
- Candidate kind `improvement` (code/prompt change) is handed to **Hephaestus Forge** via Hub. Forge's permission
  mode decides (`ask` waits for you, `auto` codes on a branch, `full_auto` may also merge). Defaults: local=auto, cloud=ask.
  Max `athena.forge.max_per_day` (2) hand-offs/day, deduplicated by title. Disable: `athena.forge.enabled`.
- Strategist prompt is caveman-style (short lines, exact output format) to save context on local models.

### Action candidate kinds
- `advisory` — suggestion for user consideration
- `remediation` — fix action for Hephaestus
- `notification` — user-facing alert
- `maintenance` — routine housekeeping
- `improvement` — change to Hestia code/prompts → Hephaestus Forge
- `setting` — change one listed setting (`CHIAVE:` + `VALORE:` lines) → `POST /route/themis/api/settings/proposals`
  with `proposer: athena`. Themis validates and dedupes, Hermes asks you on every client, nothing changes until you
  approve. Max `athena.settings.proposals_per_day` (setting, default 2; 0 = off) per day, one per key.

### Central settings
All tunables live in Themis, declared in `app/core/athena_settings.py` (`SettingsClient("athena")`), editable
from every client. All `live` (read at use time) except `athena.tasks.store_max` (`restart`).

| Key | Type | Default | Notes |
|---|---|---|---|
| `athena.settings.proposals_per_day` | int | 2 | setting proposals/day (0 = off) |
| `athena.loop.enabled` | bool | true | thinking loop on/off (thread always runs, checks every cycle) |
| `athena.loop.interval` | int s | 300 | seconds between cycles |
| `athena.loop.idle_seconds` | int s | 300 | idle gate (0 = always) |
| `athena.gate.threshold` | float | 0.55 | minimum relevance score to emit |
| `athena.retro.window` | int | 24 | outcome history for boosts (advanced) |
| `athena.retro.failure_urgency_boost` | float | 0.07 | per consecutive failure (advanced) |
| `athena.retro.unresolved_urgency_boost` | float | 0.04 | per unresolved commitment (advanced) |
| `athena.retro.unresolved_usefulness_boost` | float | 0.03 | per unresolved commitment (advanced) |
| `athena.commitments.ttl` | int s | 86400 | commitment / hint expiry (advanced) |
| `athena.hints.enabled` | bool | true | publish hints to Oracle (also skill-curator hints) |
| `athena.hints.timeout` | int s | 8 | Oracle hint call timeout (advanced) |
| `athena.thinking.archive_enabled` | bool | true | push thinking records to Archive |
| `athena.thinking.store_max` | int | 100 | in-memory thinking records (advanced) |
| `athena.tasks.store_max` | int | 500 | task lifecycle records, `restart` (advanced) |
| `athena.observe.timeout` | float s | 8 | observation call timeout (advanced) |
| `athena.observe.entity_window_hours` | int h | 24 | "recent" entity window |
| `athena.strategist.enabled` | bool | true | LLM reasoning via Oracle |
| `athena.strategist.timeout` | float s | 20 | strategist Oracle timeout (advanced) |
| `athena.strategist.max_candidates` | int | 3 | candidates per cycle |
| `athena.forge.enabled` | bool | true | hand-off to Forge (`oracle=read`) |
| `athena.forge.max_per_day` | int | 2 | Forge hand-offs/day (`oracle=read`) |
| `athena.memory.active_days` | int giorni | 7 | sessions active in last N days are consolidated |
| `athena.memory.lookback_hours` | int h | 24 | min time between consolidations of one session |
| `athena.memory.oracle_timeout` | int s | 30 | consolidation LLM timeout |
| `athena.memory.preference_decay_days` | int giorni | 90 | preference decay |
| `athena.memory.reinforce_threshold` | int | 3 | occurrences to reinforce a pattern |
| `athena.skills.min_sessions` | int | 3 | sessions per cluster to create a skill |
| `athena.skills.sim_threshold` | float | 0.90 | clustering similarity |
| `athena.skills.dedup_threshold` | float | 0.95 | duplicate-skill merge similarity |
| `athena.skills.stale_days` | int giorni | 30 | deprecate unused skills |
| `athena.skills.hard_delete_days` | int giorni | 90 | hard-delete dead skills (<3 uses) |
| `athena.skills.core_use_count` | int | 50 | uses to promote to core |
| `athena.audit.timeout` | float s | 40 | auditor LLM timeout |
| `athena.audit.max_turns` | int | 20 | default turns per audit |
| `athena.log.level` | enum | `LOG_LEVEL` env | log verbosity |

### Thinking archive
- Every cycle is stored in-memory (ring buffer, configurable max) and pushed to Archive
- Archive entity type: `athena_thinking` under domain `cognition`
- Clients can query `/api/athena/thinking` to see "what Athena is thinking"

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/logs` | Service logs (filterable) |
| GET | `/api/athena/status` | Runtime status (ticks, emissions, strategist state) |
| POST | `/api/athena/trigger` | Manual trigger with custom signals |
| GET | `/api/athena/tasks` | Task lifecycle records |
| GET | `/api/athena/tasks/{task_id}` | Single task detail |
| GET | `/api/athena/commitments` | Active commitments (action items tracked) |
| POST | `/api/athena/commitments/{brief_id}/resolve` | Resolve a commitment |
| GET | `/api/athena/thinking` | Recent thinking records (new in Phase 3) |
| GET | `/api/athena/observation` | Most recent observation snapshot (new in Phase 3) |

### When Athena works = assistant agenda windows

Registered at boot in Hestia's agenda (Chronos), editable by you (move, skip a day, pause). The default
hours are constants in code (`runtime.py`, `consolidator.py`), not env vars nor settings: the agenda already
makes them user-editable and Chronos keeps your edits over the registered defaults.

| Window | Default | Effect |
|---|---|---|
| `athena.consolidation` | daily 03–05 | memory consolidation, once per day inside the window |
| `athena.skill_curation` | daily 05–07 | skill curation, once per day inside the window |
| `athena.thinking` | all day | idle thinking cycles (observe → think → propose); skip/pause = Athena silent |

Missing window or Chronos down → default hours (consolidation 03–05) / always (skills, thinking). Skipped or paused
window = closed (your decision). Thinking still requires the idle gate (`athena.loop.idle_seconds`).

## Environment

Only infrastructure and model routing stay in env (tunables are central settings, see above).

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_NAME` / `SERVICE_BASE_URL` / `SERVICE_VERSION` / `SERVICE_TYPE` / `SERVICE_TAGS` / `SERVICE_TOPOLOGY_TAGS` | see `.env.example` | Hub registration |
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub base URL |
| `HUB_KEEPALIVE_SECONDS` | `60` | Hub re-registration period |
| `ATHENA_ORACLE_HINT_ROUTE` | `api/athena/hints` | Oracle path for hints (route) |
| `ATHENA_STRATEGIST_MODEL` / `ATHENA_STRATEGIST_PROVIDER` | (Oracle default) | Model override for strategist + consolidation (to move to Oracle settings) |
| `ATHENA_AUDITOR_MODEL` / `ATHENA_AUDITOR_PROVIDER` | (Oracle default) | Model override for the auditor (to move to Oracle settings) |
| `LOG_LEVEL` | `INFO` | Boot log level only (live: `athena.log.level`) |

## Resource-conscious design
- Single Oracle LLM call per cycle (no multi-step chain-of-thought)
- Compact prompts — never stuff full entity payloads
- Observation timeout prevents hanging on unavailable services
- Source-level failure isolation — one down service never blocks the full cycle
- Strategist can be disabled (setting `athena.strategist.enabled`) for debugging; returns empty
- Domains discovered dynamically from Hub topology tags, no hardcoded list

## Scope (Phase 3)
- [x] Real system observation (Hub, Archive, Argus)
- [x] LLM-powered reasoning via Oracle
- [x] Structured action candidate generation
- [x] Thinking cycle archiving
- [x] Client-visible thinking history endpoint
- [x] Resource-conscious prompt design

## Out of scope (future phases)
- Multi-cycle planning (today: single cycle, single Oracle call)
- Cross-domain prioritization ranking
- Persistent working memory across restarts
- Static rule-based fallbacks (by design — Oracle is core, no hardcoded substitutes)

## Skill Curator (Plan P3b-10)

Athena now manages the procedural memory lifecycle — creating, evaluating,
and curating skills from Oracle session summaries.

**Daily cycle addition (alongside memory consolidation):**
1. Read session summaries from Archive (`entity_type=session_summary`, last 24h)
2. Cluster by domain + embedding similarity
3. For clusters with ≥3 similar sessions: extract most common tool_sequence, create/update skill in Archive
4. Lifecycle management: deprecate stale (30d unused), hard-delete dead (90d, <3 uses), merge near-duplicates (sim >0.95), promote core (50+ uses, >95% success)

**Configuration:** central settings `athena.skills.*` (see "Central settings"). Embeddings go through
Oracle `/api/embed` via Hub (no Athena embedding config).

**Files:** `app/core/skill_curator.py` (new), `app/core/runtime.py` (wired into daily cycle)

## Oracle alignment
- Athena remains a separate service with its own runtime loop.
- Athena outputs are advisory cognition events, not direct Oracle action execution.
- Oracle can ingest Athena hints as context while preserving execution truth contracts.
- Skills are created by Athena (not Oracle) — the app improves day by day without user prompts.
- Oracle writes session summaries; Athena reads them, creates skills, and manages lifecycle.
- Oracle discovers skills at session start via Archive similarity search and injects them into the agent loop prompt.
- Shared priorities with Oracle:
    - trace propagation across Oracle/Hub/Hermes/Athena
    - typed task lifecycle for background jobs
    - explicit relevance gate observability for focus_brief decisions

## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Assistant presence

Light work (thinking cycles) waits while presence `work.light=defer`; consolidation and skill curation run only with `work.heavy` allow/local (still inside their agenda windows). Thinking runs as activity `athena.thinking` (light, gpu); the observation includes the presence context line. Chronos down → old Oracle-idle check.
