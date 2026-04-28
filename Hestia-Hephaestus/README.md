# Hestia-Hephaestus

Hephaestus is the guarded self-healing and coding executor service.

## P2-2 scope
- Runbook-first diagnostics and planning
- Explicit consent tiers
- Dry-run by default
- Rollback checkpoints in plan steps
- Read-only MVP (no mutating execution)

## API
- GET /health
- GET /api/hephaestus/status
- GET /api/hephaestus/runbooks
- POST /api/hephaestus/diagnose
- POST /api/hephaestus/execute-preview

## Guardrails
- Production execution disabled in MVP
- Non-dry-run execution disabled in MVP
- Execution endpoint returns preview decisions only

## Environment
- SERVICE_NAME=hephaestus
- SERVICE_BASE_URL=http://hestia_hephaestus:19010
- SERVICE_TYPE=core
- HUB_API_URL=http://hestia_hub:19001/api
- HEPHAESTUS_READ_ONLY_MODE=1
- HEPHAESTUS_ALLOW_PROD_EXECUTION=0
