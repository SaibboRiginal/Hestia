# Hestia-Hub Blueprint

## Mission
Provide a generic control plane for service registration, discovery, and internal routing.

## Scope (MVP)
- In-memory service registry
- Module-tools discovery aggregation
- Generic route proxy endpoint
- Health endpoint

## Non-Goals
- No persistence
- No business/domain rules
- No notification logic

## Contracts
- `POST /api/registry/register`
- `POST /api/registry/deregister`
- `GET /api/registry/services`
- `GET /api/discovery/module-tools`
- `POST /api/route/{service}/{path:path}`

## Quality Targets
- Deterministic routing errors
- Structured logging for register/discovery/proxy
- Stateless restart behavior
