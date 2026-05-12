# Hestia-Athena

Role: Proactive planning and cognition service.

Athena runs a periodic focus_brief loop, applies a relevance gate, and emits structured events to Hermes when the brief is worth interrupting the user.

## Event contract
- Event type: athena.focus_brief
- Destination: Hermes /api/events/ingest
- Domain: cognition
- Payload: brief + gate decision and component signals

## Gate factors
- urgency
- usefulness
- novelty
- interruption_cost
- confidence

## Scope (P2-1 scaffold)
- Hub registration + health endpoint
- Background loop
- Manual trigger endpoint
- Runtime status endpoint

## Out of scope for scaffold
- Deep planner integrations
- Persistent working memory
- Multi-brief ranking queues

## Oracle alignment (next phase)
- Athena remains a separate service/module with its own runtime loop.
- Athena outputs are advisory cognition events, not direct Oracle action execution.
- Oracle can ingest Athena hints as context while preserving execution truth contracts.
- Shared priorities with Oracle:
	- trace propagation across Oracle/Hub/Hermes/Athena
	- typed task lifecycle for background jobs
	- explicit relevance gate observability for focus_brief decisions

## Phase 2 implementation status
- Retrospective loop hardened:
	- score inputs now include recent outcomes, repeated failure streak, unresolved commitments
	- effective signals are tracked separately from base signals for auditability
- Advisory hints channel enabled:
	- Athena publishes advisory hints to Oracle through Hub route `POST /route/oracle/api/athena/hints`
	- hints include trace id, gate score, and retrospective metadata
- Commitment lifecycle endpoints:
	- `GET /api/athena/commitments`
	- `POST /api/athena/commitments/{brief_id}/resolve`

## Phase 2 pointers
- Cross-service roadmap lives in `../Hestia-Oracle/ref/ORACLE_ATHENA_PHASE2_PLAN.md`.
- Operational Oracle runbook lives in `../Hestia-Oracle/ref/ORACLE_UPGRADE_RUNBOOK.md`.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
