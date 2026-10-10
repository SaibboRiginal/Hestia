# Hestia-Hermes 📨

**Role:** Generic Proactive Dispatch Core
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

Hermes receives generic domain events, matches them against active subscriptions, and delivers each
notification to **every client** of the user (Telegram, WebUI, future ones). It is the only outbound
messenger to the user's clients.

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

## Global notifications (2026-10-10, dossier `docs/work/2026-10-10-hermes-global-notifications`)

- **Clients** = Hub services with topology tag `layer:client` and `capabilities.notify_endpoint`
  (`modules/clients.py`, cached, reloaded on registry revision change). No client is hardcoded.
- **One notification** = one `outbound_events` row (`channel = "notification"`, id = `notification_id`) with
  `payload.notification` (title, message, level, source, audience, origin, actions), `payload.deliveries`
  (`{client: {state, attempts, ref, retracted}}`), `payload.read`, `payload.answer` (`modules/notifications.py`).
  One notification per event, whatever the number of matching subscriptions.
- **Audience**: `global` (default) or `origin` — `payload._origin: {client, session_id}`, a subscription channel
  `{"type": "client", "client": X, "target": session}`, or a direct send with a concrete target on a named
  client (Forge requester's chat). Origin-only notifications reach the other clients with `silent: true`
  (inbox only; Telegram skips them). Legacy channel `{"type": "telegram"}` = global.
- **Event payload keys**: `_message` (HTML; without it Hermes narrates once via Oracle for every client),
  `_title`, `_level` (info/success/warning/error; `service.action_required`/`service.health` → warning),
  `_source` (module label/filter), `_actions`, `_origin`, `dedupe_key`; `closes: <dedupe_key>` + `decision` +
  `outcome_text` closes an earlier notification (e.g. Themis `settings.proposal_closed`) without subscriptions.
- **Actions** `{id ≤ 20 chars, label|text, style, service, method, path, body}`: the client calls
  `POST /api/notifications/{id}/answer`; Hermes claims it with an Archive compare-and-set (first answer wins,
  late ones get `409 already_handled`), routes the action to the module via Hub (`"<client>"` in body =
  answering client), then sends `update` to every client. Module error → claim released (502). Legacy
  `{text, command}` → the client runs the Hub command and reports `/answer/outcome`.
- **Read state is global**: `/seen` and `/seen-all` (Telegram: any user message in the chat) → `update` to the
  other clients (Telegram replaces the buttons with "✓ Vista su WebUI" / "✅ Approva · da WebUI").
- **Retract**: agenda job `hermes.notifications.retract` (hourly) → `POST /api/notifications/retract-stale` asks
  clients to drop messages seen/handled more than 6 h ago (window 47 h, Telegram deletes only < 48 h; never while
  still waiting for an answer). The delay becomes a Themis setting when Hermes moves to central settings.
- **Retry**: per client — only the clients that failed are retried (`HERMES_MAX_DELIVERY_ATTEMPTS`), then `dead`.
- Client contract (`kind: notification | update | retract`): see `Hestia-Swagger/swagger.yml` `ClientNotifyRequest`.

## API (MVP)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/events/ingest` | Ingest one event and evaluate subscriptions |
| `POST` | `/api/dispatch/send` | Legacy direct send: `owner` → every client; concrete target + client name → that client |
| `GET` | `/api/notifications` | Inbox (`filter` all/unread/pending, `source`, `before`, `limit`, `client`) |
| `GET` | `/api/notifications/counts` · `/clients` | Unread/pending counters · discovered clients |
| `POST` | `/api/notifications/{id}/seen` · `/seen-all` | Global read state |
| `POST` | `/api/notifications/{id}/answer` · `/answer/outcome` | First answer wins, routed to the asking module |
| `POST` | `/api/notifications/retract-stale` | Agenda job: retract handled messages from clients |

System subscription (`service.action_required`) is bootstrapped at startup for the user (`owner`,
channel `{"type": "all"}` = every client; Telegram resolves `owner` to its `ALLOWED_USER_ID`); older `sys-action-required-<chat id>` subscriptions are
deactivated so alerts are not sent twice.
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
- **Retry (rule 7):** failed client deliveries are retried every `HERMES_RETRY_INTERVAL_SECONDS` (120) up to
  `HERMES_MAX_DELIVERY_ATTEMPTS` (6) per client, then that client is marked `dead` (the row is `dead` only if
  no client got it). Attempts are stored in `payload.deliveries`.
- **Batches (real_estate):** a failed batch is re-queued with exponential backoff (`ENTITY_BATCH_MAX_ATTEMPTS`, 6),
  merged with entities that arrived meanwhile.
- **Narration** uses Oracle `/api/llm/generate` (plain generation), not the full `/api/chat` pipeline.
