# Hestia-Hephaestus

Role: Guarded self-healing and coding executor.

P2-2 implementation is intentionally constrained to read-only diagnostics. Hephaestus produces runbook-based plans with explicit consent and dry-run guardrails.

## Principles
- Runbook-first
- Explicit consent tiers
- Dry-run default
- Rollback checkpoints required
- No mutating execution in MVP

## Endpoints
- GET /health
- GET /api/hephaestus/status
- GET /api/hephaestus/runbooks
- POST /api/hephaestus/diagnose
- POST /api/hephaestus/execute-preview

## Safety contract (MVP)
- Production execution disabled
- Non-dry-run execution disabled
- execute-preview returns allow/deny with blocked reasons only
