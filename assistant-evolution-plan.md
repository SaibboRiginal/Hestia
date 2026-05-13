# Hestia Assistant Evolution Plan

## Goal
Design and stage a scalable evolution of command execution, client-specific rendering, Oracle self-awareness, Athena proactivity, and module re-evaluation controls before implementation.

## Why This Plan Exists
You requested broad behavioral upgrades that touch multiple services and contracts. This plan sequences changes so we avoid regressions and keep docs, service contracts, and runtime behavior aligned.

## Implementation Status Snapshot (2026-05-12)

| Phase | Status | Acceptance Outcome |
|---|---|---|
| Phase 1 - Capability Inventory and Contracts | Complete | Pass: inventory artifacts present, governance rules added, docs-sync automation added |
| Phase 2 - Oracle Self-Awareness Core | Complete | Pass: deterministic read fallback and capability-aware execution paths active |
| Phase 3 - Client Policy Standardization | Complete | Pass: Telegram minimal/compact/rich rendering policy implemented and documented |
| Phase 4 - Athena Proactivity Upgrade | Complete | Pass: retrospective scoring, hint channel, and task/commitment observability endpoints in place |
| Phase 5 - Module Re-Evaluation On Demand | Partial | Open: generic module maintenance endpoint contract not yet standardized across eligible modules |

## Acceptance Check Evidence

1. Phase 1 checks:
- Pass: capability inventory artifacts exist (`capability-inventory.md`, `capability-inventory.json`).
- Pass: governance mandates added in root documentation and rulebook.
- Pass: PR automation added for docs/contract drift gates (`tools/governance/check_docs_sync.py`, `tools/governance/check_command_contracts.py`, `.github/workflows/governance-checks.yml`).

2. Phase 2 checks:
- Pass: Oracle includes deterministic query/action precheck flows and capability-aware orchestration.
- Pass: assistant-facing capabilities and execution metadata are now integrated into operational paths.

3. Phase 3 checks:
- Pass: Telegram signal rendering policy supports minimal/compact/rich behavior with family overrides.
- Pass: policy knobs are documented and wired through runtime configuration.

4. Phase 4 checks:
- Pass: Athena retrospective scoring and bounded proactivity telemetry are implemented.
- Pass: Oracle-Athena advisory hint ingestion and query APIs are available.
- Pass: task lifecycle visibility endpoints are available for Oracle and Athena runtime operations.

5. Phase 5 checks:
- Partial: re-evaluation and reconcile behavior exists in specific modules, but a single generic module maintenance contract is not yet uniformly exposed via Hub-routable command metadata.
- Open: standard endpoint naming, command catalog shape, and retriable lifecycle semantics need final normalization across eligible modules.

## Current Behavior Baseline
1. Command source is dynamic:
- Services register commands under capabilities.commands in Hub registry.
- Hub exposes aggregated discovery at /api/discovery/commands.
- Oracle fetches commands through Hub client and can route execution through Hub route envelopes.
- Telegram builds visible command surfaces from Hub discovery and local command catalog.

2. Client rendering is client-owned:
- Canonical payloads/signals are rich.
- Telegram applies its own render policy (now style-mapped for minimal, compact, rich).

3. Athena behavior today:
- Periodic focus-brief loop with relevance gate and threshold.
- Default cadence controlled by ATHENA_BRIEF_INTERVAL_SECONDS.
- Produces advisory hints and runtime telemetry, but it is not yet a full conversational autonomy governor.

## Target Architecture
### A. Canonical Capabilities + Client Policy
1. Keep command payloads and signal payloads rich and canonical.
2. Add strict client policy profiles so each client chooses display density without backend data loss.
3. Keep execution and audit independent from display.

### B. Command Reliability and Discoverability
1. Treat Hub discovery as single source of truth for executable commands.
2. Add deterministic prechecks in Oracle for high-frequency read operations when LLM routing is uncertain.
3. Expose command introspection to users in a controlled way (what exists, what is executable now, what requires inputs).

### C. Oracle Self-Awareness Layer
1. Add a capabilities-awareness toolset in Oracle that merges:
- Generic core services capabilities.
- Module-specific capabilities and maintenance endpoints.
2. Add a runtime summary endpoint and internal cache for:
- Available commands.
- Available modules.
- Required arguments and interactive constraints.
- Health/readiness snapshot from Hub.

### D. Athena as Balanced Proactivity Engine
1. Evolve Athena from periodic scorer to bounded autonomy orchestrator.
2. Keep proactive behavior controlled by policy guardrails:
- Frequency caps.
- Domain sensitivity.
- User control preferences.
- Silence windows.
3. Keep Athena advisory, not authority override.

### E. On-Demand Module Re-Evaluation
1. Introduce a generic maintenance contract for modules.
2. Every eligible module exposes a standard reconcile/re-evaluate endpoint.
3. Oracle can trigger module maintenance via Hub routing on explicit user request.

## Governance Rule Additions (Implemented)
These are implemented in repository governance docs and automation:
1. Documentation synchronization rule:
- Any behavior or contract change must update readme.md and the impacted service markdown files in the same change set.

2. Capabilities contract rule:
- Every executable command intended for assistants must be discoverable through Hub capabilities.commands with complete argument metadata.

3. Client render policy rule:
- Canonical payloads remain rich; clients must apply policy-based rendering (minimal, compact, rich) without mutating source semantics.

4. Maintenance contract rule:
- Reconciliation and re-evaluation endpoints for modules must follow a generic pattern and be exposed through Hub-routable capabilities.

## Phased Implementation Plan
### Phase 1 - Capability Inventory and Contracts
Scope:
1. Build a machine-readable capability inventory document across services.
2. Define required command metadata quality checks.
3. Define generic module maintenance endpoint contract.

Deliverables:
1. Capability inventory markdown plus JSON schema.
2. Contract updates in copilot-instructions.md.
3. Service-by-service gap report.

Acceptance criteria:
1. All executable assistant commands are discoverable via Hub and validated.
2. Missing argument schemas are identified and tracked.

### Phase 2 - Oracle Self-Awareness Core
Scope:
1. Add Oracle internal capability index service.
2. Add deterministic fallback selection for key read operations and introspection prompts.
3. Add assistant-facing introspection responses: what can be done now.

Deliverables:
1. New Oracle capability awareness module.
2. New Oracle endpoint for capability snapshot.
3. Prompt and planner integration with capability context.

Acceptance criteria:
1. Oracle no longer says manual is required when a valid command exists and is routable.
2. Oracle can explain available commands per domain and required inputs.

### Phase 3 - Client Policy Standardization
Scope:
1. Finalize Telegram signal and command display policy map.
2. Add profile support for other clients (future-ready contract, even if not implemented yet).
3. Keep audit detail out of chat unless policy requests compact or rich.

Deliverables:
1. Global policy specification section in readme.md.
2. Telegram service markdown updates with examples.
3. Policy test matrix.

Acceptance criteria:
1. Minimal mode remains one-line for operational events.
2. Compact and rich modes are deterministic and documented.

### Phase 4 - Athena Proactivity Upgrade
Scope:
1. Add bounded reflection cycle (retrospective + planning memory).
2. Add controlled proactive chat prompts with limits and user preferences.
3. Add observability for proactive decisions and suppressions.

Deliverables:
1. Athena policy config set for proactive behavior.
2. Oracle integration for Athena advisory narrative without spam.
3. Telemetry dashboards/log query recipes.

Acceptance criteria:
1. Proactive events remain useful and non-intrusive.
2. Clear explainability: why Athena decided to speak or stay silent.

### Phase 5 - Module Re-Evaluation On Demand
Scope:
1. Add generic maintenance endpoints in eligible modules.
2. Expose commands through capabilities.commands for assistant use.
3. Add Oracle execution paths for user-triggered full reconcile tasks.

Deliverables:
1. Standard endpoint pattern across modules.
2. Command catalog entries and response prompts.
3. Task lifecycle visibility in Oracle and module logs.

Acceptance criteria:
1. User can request full module re-evaluation and get execution confirmation.
2. Jobs are tracked and queryable; failures are retriable.

## Documentation Rollout Plan
Files to keep synchronized in implementation phases:
1. Root docs:
- readme.md
- .github/copilot-instructions.md

2. Service summaries:
- Hestia-Archive/hestia-archive.md
- Hestia-Argus/hestia-argus.md
- Hestia-Athena/hestia-athena.md
- Hestia-Atlas/hestia-atlas.md
- Hestia-Chronos/hestia-chronos.md
- Hestia-Hephaestus/hestia-hephaestus.md
- Hestia-Hermes/hestia-hermes.md
- Hestia-Hub/hestia-hub.md
- Hestia-Hecate/hestia-hecate.md
- Hestia-Oracle/hestia-oracle.md
- Hestia-Scout/hestia-scout.md
- Hestia-Telegram/hestia-telegram.md

3. API reference:
- Hestia-Swagger/swagger.yml for any endpoint or schema change.

## Risks and Controls
1. Risk: Over-proactive assistant behavior.
- Control: hard frequency limits, user-level suppressions, domain gates, quiet hours.

2. Risk: Command mis-execution from ambiguous requests.
- Control: deterministic prechecks, confidence thresholds, explicit confirmation for sensitive actions.

3. Risk: Documentation drift.
- Control: rulebook mandate plus per-phase doc checklist and release gate.

4. Risk: Service coupling.
- Control: all interactions routed through Hub contracts and capability metadata.

## Validation Strategy
1. Functional tests:
- Command discovery and execution path tests.
- Client policy rendering tests (minimal, compact, rich).
- Athena decision policy tests.

2. Integration tests:
- Hub discovery to Oracle to target service execution.
- Telegram end-to-end chat with signal rendering profiles.
- Module re-evaluation trigger and lifecycle tracking.

3. Operational checks:
- Health and readiness.
- Logs with event-first format.
- Swagger consistency for changed APIs.

## Execution Order Recommendation
1. Phase 1 and Phase 2 first.
2. Phase 3 next (stabilize user-visible behavior).
3. Phase 4 and Phase 5 after capability and policy foundations are proven.

## Immediate Next Step
If approved, close Phase 5 with a single cross-module maintenance contract by:
1. Defining one standard Hub-routable maintenance endpoint pattern for eligible modules.
2. Publishing uniform command metadata for maintenance/re-evaluation operations.
3. Adding contract-validation checks for maintenance command discoverability and retry semantics.
