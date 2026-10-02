# Hestia-Hermes 📨

**Role:** Generic Proactive Dispatch Core
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

Hermes receives generic domain events, matches them against active subscriptions, and dispatches alerts via configured channels.

Hermes is core and generic: no domain-specific rules are implemented in Hermes.

---

## Event Flow

1. Domain module emits event (example: `entity.upserted`).
2. Hermes loads active subscriptions from Archive.
3. Hermes performs generic matching + dedupe checks.
4. Hermes dispatches alert via channel adapter.
5. Hermes writes delivery outcome to Archive dispatch log.

### Deduplication

Hermes deduplicates outbound events by `dedupe_key` (compound of event type, domain,
entity ID, and subscription ID). Only events in an "active" lifecycle state
(`created`, `queued`, `delivered`, `seen`, `answered`) block re-delivery.

**Time-based expiry for recurring events:** For event types listed in
`HERMES_RECURRING_EVENT_TYPES` (default: `service.action_required,service.health`),
delivered events older than `HERMES_RECURRING_EVENT_MAX_AGE_SECONDS` (default 3600 s)
are treated as stale and do NOT block re-delivery. This prevents persistent issues
like auth failures from being permanently silenced while still suppressing spam
within the cooldown window.

---

## API (MVP)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/events/ingest` | Ingest one event and evaluate subscriptions |
| `POST` | `/api/dispatch/send` | Direct dispatch command (internal use) |
| `GET` | `/health` | Hermes health |

---

## Constraints

- No domain-specific ranking logic.
- No DB access outside Archive APIs.
- No chat orchestration (Oracle responsibility).
- No connector/data-fetching logic (Hecate/module responsibility).


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Delivery semantics (dedupe + retry)

- **Dedupe key:** `payload.dedupe_key` → `question_id`/`brief_id` → for pre-formatted messages (`_message`)
  `event_type:domain:entity_id:<hash of text>` → else `event_type:domain:entity_id`.
  Before, a fixed `entity_id` (e.g. Argus `argus-batch`) deduped every later alert against the first delivered one.
- **Retry (rule 7):** failed deliveries are retried every `HERMES_RETRY_INTERVAL_SECONDS` (120) up to
  `HERMES_MAX_DELIVERY_ATTEMPTS` (6), then marked `dead`. Attempts are stored in the outbound event payload.
- **Batches (real_estate):** a failed batch is re-queued with exponential backoff (`ENTITY_BATCH_MAX_ATTEMPTS`, 6),
  merged with entities that arrived meanwhile.
- **Narration** uses Oracle `/api/llm/generate` (plain generation), not the full `/api/chat` pipeline.
