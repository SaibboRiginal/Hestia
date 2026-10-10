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

**Time-based expiry for recurring events:** For event types listed in the setting
`hermes.dedupe.recurring_types` (default: `service.action_required`, `service.health`),
delivered events older than `hermes.dedupe.recurring_max_age` (default 3600 s)
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
  clients to drop messages seen/handled more than `hermes.retract.after` hours ago (default 6; window 47 h,
  Telegram deletes only < 48 h; never while still waiting for an answer).
- **Retry**: per client — only the clients that failed are retried (`hermes.delivery.max_attempts`), then `dead`.
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
- **Retry (rule 7):** failed client deliveries are retried every `hermes.delivery.retry_interval` (120 s) up to
  `hermes.delivery.max_attempts` (6) per client, then that client is marked `dead` (the row is `dead` only if
  no client got it). Attempts are stored in `payload.deliveries`.
- **Batches (real_estate):** a failed batch is re-queued with exponential backoff (`hermes.batch.max_attempts`, 6; settling window `hermes.batch.window`, 30 s),
  merged with entities that arrived meanwhile.
- **Narration** uses Oracle `/api/llm/generate` (plain generation), not the full `/api/chat` pipeline.

## Central settings (Themis)

Declared in `src/modules/hermes_settings.py` (`SettingsClient("hermes")`, router `GET /api/settings/effective`,
`POST /api/settings/reload`). All are `apply=live` (read at use time); Themis down → defaults with a `[🔄]` log.

| Key | Type / default | Effect |
|---|---|---|
| `hermes.delivery.max_attempts` | int 6 | Delivery attempts per client before that client is `dead` |
| `hermes.delivery.retry_interval` | int 120 s (min 15) | Pause between retry passes of failed deliveries |
| `hermes.dedupe.recurring_max_age` | int 3600 s | After this age a delivered recurring alert no longer blocks a new one |
| `hermes.dedupe.recurring_types` | list `service.action_required`, `service.health` | Event types with time-limited dedupe |
| `hermes.batch.window` | int 30 s | Settling window for batched entity alerts (also backoff base) |
| `hermes.batch.max_attempts` | int 6 | Attempts for a failed batch before giving up |
| `hermes.retract.after` | int 6 h (1–46) | Handled notifications are retracted from Telegram after this delay |
| `hermes.log.level` | enum (boot = `LOG_LEVEL`) | Log verbosity |

Env keeps only infrastructure: `HUB_API_URL`, `ARCHIVE_API_URL`, `HERMES_SERVICE_BASE_URL`,
`HERMES_SERVICE_VERSION`, `HERMES_HUB_REGISTER_RETRIES`, `HERMES_HUB_REGISTER_RETRY_DELAY`,
`STARTUP_WAIT_TIMEOUT_SECONDS`, `LOG_LEVEL` (boot default only).
