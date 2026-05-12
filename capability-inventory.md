# Hestia Capability Inventory (Draft)

Last updated: 2026-05-12

## Scope

This draft maps service ownership and command/capability discovery expectations across the workspace.

## Discovery and Execution Baseline

1. Hub is the canonical registry and routing layer for cross-service execution.
2. Assistant-executable commands must be discoverable via Hub (`/api/discovery/commands`).
3. Service-to-service behavior contracts are documented in service markdown files and synchronized with `Hestia-Swagger/swagger.yml`.

## Services

| Service | Workspace Folder | Primary Role | Hub Command Discovery Source | Notes |
|---|---|---|---|---|
| Archive | Hestia-Archive | Persistence and storage workflows | `capabilities.commands` -> Hub discovery | Owns archive data lifecycle |
| Argus | Hestia-Argus | Alerting, monitoring, remediation intent emission | `capabilities.commands` -> Hub discovery | Sole monitoring authority; emits policy-gated remediation intents to Hephaestus |
| Athena | Hestia-Athena | Proactive intelligence/planning orchestration | `capabilities.commands` -> Hub discovery | Strategy and proactive reasoning layer |
| Atlas | Hestia-Atlas | External fetch/aggregation | `capabilities.commands` -> Hub discovery | Ingestion-facing fetch workflows |
| Chronos | Hestia-Chronos | Time/calendar and scheduling integrations | `capabilities.commands` -> Hub discovery | Credentialed calendar routines |
| Dummy | Hestia-Dummy | Deterministic maintenance test module for remediation execution | `capabilities.commands` -> Hub discovery | Dedicated safe target for Hephaestus remediation integration tests |
| Hephaestus | Hestia-Hephaestus | Autonomous remediation orchestration and execution | `capabilities.commands` -> Hub discovery | Owns remediation tasks/approval/rollback APIs and Hub-routed maintenance execution contract |
| Hermes | Hestia-Hermes | Dispatch/executor workflows | `capabilities.commands` -> Hub discovery | Command dispatch and execution support |
| Hub | Hestia-Hub | Registry, discovery, routing | Native owner of `/api/discovery/commands` and `/route/{service}/...` | Single source of truth for cross-service command lookup |
| Ingest | Hestia-Ingest | Ingestion and feed pipelines | `capabilities.commands` -> Hub discovery | Fetchers and stateful ingest control |
| Oracle | Hestia-Oracle | LLM reasoning and tool-call orchestration | Consumes Hub discovery to execute tools | Must prefer deterministic command execution when metadata is complete |
| Scout | Hestia-Scout | Exploration/scouting intelligence | `capabilities.commands` -> Hub discovery | Discovery and reconnaissance support |
| Telegram | Hestia-Telegram | User interface and delivery channel | Consumes Hub discovery for command catalog | Client display policy (`minimal|compact|rich`) applies at rendering layer |
| Shared | Hestia-Shared | Shared libraries/utilities | N/A (library package) | Common logging and startup utilities |
| Swagger | Hestia-Swagger | API documentation aggregator | N/A (documentation source) | `swagger.yml` must track API/contract changes in same change set |

## Current Gaps to Track

1. Expand Hephaestus skeleton executor from metadata-only execution to real branch/commit/deploy operations with strict policy gates.
2. Add structured post-remediation verification loop (Argus confirms recovery and can trigger rollback recommendations).
3. Add command-level schema conformance checks between Hub discovery payloads and canonical OpenAPI schemas.
