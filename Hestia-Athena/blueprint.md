# Athena Blueprint

## Goal
Create a proactive cognition node that proposes timely focus briefs without spamming.

## Inputs
- Internal timers (periodic cycle)
- Manual trigger requests
- Future: user context and goals from Archive/Oracle

## Processing
1. Build brief candidate.
2. Compute relevance score using urgency, usefulness, novelty, interruption_cost, confidence.
3. Emit only if score passes threshold.

## Output
- Structured Hermes event: athena.focus_brief

## Contracts
- Health: GET /health
- Status: GET /api/athena/status
- Trigger: POST /api/athena/trigger
