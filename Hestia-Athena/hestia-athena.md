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
