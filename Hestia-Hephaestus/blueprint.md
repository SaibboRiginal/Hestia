# Hephaestus Blueprint

## Goal
Deliver a guarded operations assistant that plans remediation safely before any execution.

## P2-2 MVP
1. Receive issue context.
2. Select an internal runbook.
3. Produce diagnostics plan with rollback checkpoints.
4. Evaluate consent tier and environment constraints.
5. Return preview-only execution decision.

## Out of scope in P2-2
- Applying live code edits automatically
- Restarting production services
- Running mutating shell commands
- Autonomous deploys
