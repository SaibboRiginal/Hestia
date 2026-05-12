# Hestia-Hephaestus

Role: Guarded self-healing and coding executor.

P2-2 implementation is intentionally constrained to read-only diagnostics. Hephaestus produces runbook-based plans with explicit consent and dry-run guardrails.

Target role evolution: autonomous remediation executor triggered by Argus/Oracle policy contracts.

## Principles
- Runbook-first
- Explicit consent tiers
- Dry-run default
- Rollback checkpoints required
- No mutating execution in MVP
- Full audit trail for every mutation
- User-visible notifications before and after automated mutation
- Source-control-first remediation (branch/commit/rollback)

## Endpoints
- GET /health
- GET /api/hephaestus/status
- GET /api/hephaestus/runbooks
- POST /api/hephaestus/diagnose
- POST /api/hephaestus/execute-preview
- POST /api/hephaestus/remediate
- POST /api/hephaestus/remediate/{task_id}/approve
- POST /api/hephaestus/remediate/{task_id}/rollback
- GET /api/hephaestus/tasks
- GET /api/hephaestus/tasks/{task_id}

Execution endpoints above are implemented as policy-gated remediation flows (task creation, approval, rollback metadata) with real Hub-routed maintenance execution against target services.

## Safety contract (Current)
- Production mutation requires explicit approval.
- Non-production mutation can be policy-gated via `HEPHAESTUS_REQUIRE_APPROVAL_FOR_MUTATION`.
- Auto-approval can be blocked/enabled via `HEPHAESTUS_ALLOW_AUTO_APPROVE_NON_PROD`.
- execute-preview remains a diagnostic gating endpoint.

## Autonomous Remediation Contract (Target)

1. Triggering:
- Allowed from Argus/Oracle/user command via Hub-routed contract.

2. Source control requirements:
- Branch-per-remediation (`auto/hephaestus/<task-id>` pattern).
- Atomic commits with machine-readable execution metadata.
- Rollback pointer required (baseline commit/tag) before mutation.

3. Notification requirements:
- Notify start of mutation with reason and scope.
- Notify completion with changed files, branch/commit refs, and deployment result.
- Notify rollback when executed or recommended.

4. Deployment requirements:
- Local deploy allowed under policy.
- Remote/cluster deploy requires environment-level policy gates and health verification.

5. Copilot account/runtime note:
- Hephaestus must not depend on opening an interactive personal IDE Copilot session.
- Automation is performed through service/workflow APIs, repository operations, and deterministic runbooks.

## Command Discovery

Hephaestus publishes assistant-executable command metadata through Hub discovery for:
- status
- runbook listing
- task listing
- remediation task creation
- remediation approval
- remediation rollback


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
