# Hestia-Athena

Athena is the proactive planning and cognition service.

## Responsibilities
- Run a periodic focus_brief loop.
- Apply a relevance gate over each candidate brief.
- Emit accepted briefs to Hermes as structured events.
- Expose lightweight status and manual trigger APIs.

## API
- GET /health
- GET /api/athena/status
- POST /api/athena/trigger

## Relevance Gate
Athena scores each brief using five normalized signals in [0, 1]:
- urgency
- usefulness
- novelty
- interruption_cost
- confidence

Weighted score:
- 0.30 * urgency
- 0.25 * usefulness
- 0.20 * novelty
- 0.15 * confidence
- 0.10 * (1 - interruption_cost)

Briefs are emitted only when score >= ATHENA_RELEVANCE_THRESHOLD.

## Environment
- SERVICE_NAME=athena
- SERVICE_BASE_URL=http://hestia_athena:19009
- SERVICE_TYPE=core
- HUB_API_URL=http://hestia_hub:19001/api
- HERMES_API_URL=http://hestia_hermes:19005
- ATHENA_LOOP_ENABLED=1
- ATHENA_BRIEF_INTERVAL_SECONDS=300
- ATHENA_RELEVANCE_THRESHOLD=0.55

## Run
1. docker compose up --build -d
2. Check health at http://localhost:19009/health
