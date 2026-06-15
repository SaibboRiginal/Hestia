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
  - No hardcoded domain list — `ATHENA_OBSERVE_DOMAINS_FALLBACK` is used only when Hub is unreachable
- **Self-state**: active commitments, unresolved commitments, failure streaks

### Strategist (LLM reasoning)
- Single Oracle round-trip per cycle via Hub routing (`POST /route/oracle/api/llm/generate`)
- Compact prompt format optimized for local models
- Structured `AZIONE:/TIPO:/PRIORITA:/DOMINIO:/MOTIVO:/RIASSUNTO:` output format
- Graceful responses: `NESSUNA_AZIONE` when nothing actionable, empty list on Oracle failure
- Oracle is a **core dependency** — if it is unreachable, Athena returns no candidates
  (the observation cycle still runs and is archived, but no static rules are substituted)

### Action candidate kinds
- `advisory` — suggestion for user consideration
- `remediation` — fix action for Hephaestus
- `notification` — user-facing alert
- `maintenance` — routine housekeeping

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

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `ATHENA_LOOP_ENABLED` | `1` | Enable the periodic thinking loop |
| `ATHENA_BRIEF_INTERVAL_SECONDS` | `300` | Seconds between thinking cycles |
| `ATHENA_RELEVANCE_THRESHOLD` | `0.55` | Minimum score to emit an action |
| `ATHENA_OBSERVE_TIMEOUT_SECONDS` | `8` | Timeout for Hub-routed observation calls |
| `ATHENA_OBSERVE_ENTITY_WINDOW_HOURS` | `24` | Window for "recent" entity detection |
| `ATHENA_OBSERVE_DOMAINS_FALLBACK` | `real_estate,calendar` | Static fallback domains when Hub unreachable |
| `ATHENA_STRATEGIST_ENABLED` | `1` | Enable LLM reasoning via Oracle |
| `ATHENA_STRATEGIST_TIMEOUT_SECONDS` | `20` | Timeout for Oracle LLM calls |
| `ATHENA_STRATEGIST_MAX_CANDIDATES` | `3` | Max action candidates per cycle |
| `ATHENA_STRATEGIST_MODEL` | (Oracle default) | Override LLM model |
| `ATHENA_STRATEGIST_PROVIDER` | (Oracle default) | Override LLM provider |
| `ATHENA_THINKING_ARCHIVE_ENABLED` | `1` | Push thinking records to Archive |
| `ATHENA_THINKING_STORE_MAX` | `100` | Max in-memory thinking records |
| `ATHENA_COMMITMENT_TTL_SECONDS` | `86400` | Commitment expiry (24h) |
| `ATHENA_RETROSPECTIVE_WINDOW` | `24` | Outcome history window for boosts |
| `ATHENA_RETRO_FAILURE_URGENCY_BOOST` | `0.07` | Urgency boost per consecutive failure |
| `ATHENA_RETRO_UNRESOLVED_URGENCY_BOOST` | `0.04` | Urgency boost per unresolved commitment |
| `ATHENA_RETRO_UNRESOLVED_USEFULNESS_BOOST` | `0.03` | Usefulness boost per unresolved commitment |
| `ATHENA_ORACLE_HINT_ENABLED` | `1` | Publish advisory hints to Oracle |
| `ATHENA_ORACLE_HINT_TIMEOUT_SECONDS` | `8` | Timeout for Oracle hint calls |
| `ATHENA_TASK_STORE_MAX` | `500` | Max task lifecycle records |

## Resource-conscious design
- Single Oracle LLM call per cycle (no multi-step chain-of-thought)
- Compact prompts — never stuff full entity payloads
- Observation timeout prevents hanging on unavailable services
- Source-level failure isolation — one down service never blocks the full cycle
- Strategist can be disabled (`ATHENA_STRATEGIST_ENABLED=0`) for debugging; returns empty
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
- Autonomous Hephaestus task queuing (contract defined, not wired)
- Cross-domain prioritization ranking
- Persistent working memory across restarts
- Static rule-based fallbacks (by design — Oracle is core, no hardcoded substitutes)

## Oracle alignment
- Athena remains a separate service with its own runtime loop.
- Athena outputs are advisory cognition events, not direct Oracle action execution.
- Oracle can ingest Athena hints as context while preserving execution truth contracts.
- Shared priorities with Oracle:
    - trace propagation across Oracle/Hub/Hermes/Athena
    - typed task lifecycle for background jobs
    - explicit relevance gate observability for focus_brief decisions

## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
