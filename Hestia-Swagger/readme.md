# Hestia-Swagger 📋

**Role:** API Documentation Aggregator
**Type:** Documentation source (not a deployable service)

---

## Responsibility

Canonical source of truth for all Hestia service API contracts in a single OpenAPI 3.0 document (`swagger.yml`).

Served via the Swagger UI aggregator on port `19000`.

---

## Update Contract

Any API endpoint, schema, or Hub-routed command contract change across any service must update `swagger.yml` in the same change set.

---

## Constraints

- Single-file source of truth — no fragmented specs.
- No Python runtime or Docker deployment.
