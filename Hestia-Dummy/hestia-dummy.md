# Hestia-Dummy

Role: dedicated generic testing module for integration, execution, and orchestration validation.

This service exists to provide a safe, deterministic target that can run in Docker and be exercised through Hub routing by any service (not tied to Hephaestus).

## Endpoints
- GET /health
- GET /api/logs
- GET /api/dummy/status
- POST /api/module/maintenance/reconcile
- POST /api/maintenance/reconcile
- GET /api/module/recap — reference daily recap piece («Test»: the reconciles of the day), capability `recap_endpoint`

## Behavior
- `dry_run=true`: returns a reconciliation preview without mutating internal state.
- `dry_run=false`: applies a deterministic in-memory mutation and reports a concrete outcome.
- Intended usage is generic system testing: command routing, policy flows, retries, and integration checks.

## Documentation Synchronization (Required)
1. Any endpoint or schema change must update Hestia-Swagger/swagger.yml in the same change.
2. Any capability metadata change must remain consistent with Hub discovery payloads.

**2026-11-16 (no Italian in the code, dossier `docs/work/2026-11-14-backend-inglese` v2.0)**: every text is English in the code; Italian lives only in `Hestia-Shared/hestia_common/locales/it/messages.json`. Labels declared at registration (manifest, capabilities, agenda rules, settings) are plain English, translated at the edge.
