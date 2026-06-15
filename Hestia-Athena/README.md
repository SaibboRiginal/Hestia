# Hestia-Athena

Athena is the proactive cognition and advisory strategy engine for Hestia.

## What Athena Does

Athena runs a periodic **observe → think → score → act → archive** loop:

1. **Observe** — gathers system state via Hub routing:
   - Registered services and their health (from Hub + Argus)
   - Entity domain summaries (from Archive: counts, recent activity, pending steps)
   - Self-state (active commitments, failure streaks)

2. **Think** — calls Oracle LLM (Strategist) with a compact observation prompt to
   generate structured action candidates. Each candidate specifies: domain, kind
   (advisory/remediation/notification/maintenance), priority, and reasoning.

3. **Score** — runs each candidate through a 5-signal relevance gate (urgency,
   usefulness, novelty, interruption_cost, confidence) with retrospective
   boosting from past outcomes.

4. **Act** — emits accepted candidates to Hermes as `athena.focus_brief` events
   and publishes advisory hints to Oracle.

5. **Archive** — stores the complete thinking record (observation + candidates +
   decisions) for audit and client display.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/logs` | Service logs |
| GET | `/api/athena/status` | Runtime status |
| POST | `/api/athena/trigger` | Manual trigger |
| GET | `/api/athena/tasks` | Task lifecycle records |
| GET | `/api/athena/tasks/{id}` | Single task |
| GET | `/api/athena/commitments` | Active commitments |
| POST | `/api/athena/commitments/{id}/resolve` | Resolve commitment |
| GET | `/api/athena/thinking` | Recent thinking records |
| GET | `/api/athena/observation` | Latest observation snapshot |

## Environment

See [hestia-athena.md](hestia-athena.md) for the full variable reference.

Key controls:
- `ATHENA_LOOP_ENABLED=1` — enable the thinking loop
- `ATHENA_BRIEF_INTERVAL_SECONDS=300` — how often Athena thinks
- `ATHENA_STRATEGIST_ENABLED=1` — enable LLM reasoning (set 0 for signal-only mode)
- `ATHENA_RELEVANCE_THRESHOLD=0.55` — minimum score to act

## Resource-Conscious Design

- Single Oracle LLM call per cycle
- Compact prompts — never stuff full payloads
- Source-level failure isolation
- Can disable strategist for pure signal-based gating
- Observation capped at 6 domains
