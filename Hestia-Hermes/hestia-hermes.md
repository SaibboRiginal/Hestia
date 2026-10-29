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
- **Link** `_link: {module, page, params?}` (client plugins): stored as `notification.link`, sent to clients and in
  the inbox view; the WebUI shows "Apri" → `/p/<module>/<page>`. Batched domains: one entity → its link; several from
  one module with `_link.list` → that list page.
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

## One live reminder per thing (2026-10-17, dossier `docs/work/2026-10-17-hermes-repeat-notifications`)

- A module that nudges about the same thing again sends `replaces: "<key>"` in the event payload (alias
  `_replaces`; the key names the thing, e.g. `selfcare.reminder.<routine_id>`). The key is the row's `dedupe_key`;
  such events are **never deduped**.
- Hermes reads the latest row with that key: every still-open occurrence becomes `superseded` (compare-and-set,
  a concurrent answer wins) and every client gets `update {state: "superseded", superseded_by}` (Telegram deletes
  the message, over 48 h «↻ Sostituito»; WebUI removes it). A late answer on it → `409 already_handled`.
- Counter in `payload.notification.repeat {count, skipped, since}`: previous not resolved → +1 / +1, else
  fresh. Clients get `repeat: {count, skipped, since, text}` from the 2nd occurrence («Saltato 2 volte · dal 12 ott»,
  readable aloud). The module's own text never counts skips.
- The chain ends (`payload.repeat_resolved`) when the user answers with an action flagged `resolves: true`
  («Fatto») or the module sends `closes: <key>` with `decision` `done`/`resolved`. Other answers («Salta») count
  as skipped. A chain idle longer than `hermes.repeat.reset_after_days` starts from zero.
- The inbox lists every state but `superseded`: only the live occurrence is shown.
- When to nudge stays with the module (e.g. Self care max 2/week).

## Notifications also as voice (2026-10-20, dossier `docs/work/2026-10-20-modulo-voce` §7.3)

- The module decides with its own setting `<module>.notifiche.voce` (`hestia_common.reminders.voice_setting`) and puts
  `_voice: true` in the event payload (`reminder_event(voice=…)`; batched domains keep the flag for the batch).
- Hermes publishes the written notification as always, then in the background asks Echo (`VoiceClient.speak`, use
  `hermes.notifica` declared in `voice_usecases`, `ogg_opus`, kept as class `notification`), stores
  `payload.voice {blob_id, duration_s, mime_type}` and sends every client an `update {voice: {blob_id, duration_s,
  mime_type, audio_b64}}`: Telegram sends a voice message replying to the notification; the WebUI inbox shows
  «Ascolta» (`view.voice`, bytes via `GET /api/ui/inbox/{id}/voice`).
- Echo down → `[🔄]`, the text stays the only form. Superseded (or superseded before the audio is ready) → the audio is
  dropped in Echo (`forget`).

## Da decidere, active client, secret form, Web Push (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy` W2)

- **«Da decidere»** (Cindy 5): agenda job `hermes.notifications.remind_pending` (hourly) → `POST
  /api/notifications/remind-pending`. Notifications still waiting for an answer after `hermes.attesa.richiamo_ore`
  (default 4 h) get ONE grouped reminder «Da decidere: N» (repeat chain `hermes.pending_reminder`, so the previous
  reminder is replaced), each notification recalled once (`reminded_at`). The link opens the inbox filter `pending`.
- **Rings only where the owner is** (Cindy 20): if the presence says the owner used a client (`last_interaction_client`)
  within `hermes.consegna.client_attivo_minuti` (default 10, 0 = everywhere), the other clients get the notification
  `silent` (inbox only). Urgent ones (`_urgent`) and `origin` notifications keep their own rule; an unknown client
  (one Hermes does not deliver to) rings everywhere.
- **Secret form** (Cindy 4): an event with `_secret: {service, path, fields: [{name, label, type password|text|token}]}`
  shows a form (WebUI; Telegram gets an «Inserisci» Mini App button, never asks in the chat). `POST
  /api/notifications/{id}/secret {client, values}` claims it (first answer wins) and forwards `{values, client}` to
  the module through the Hub. Hermes never stores or logs the values (only the field names); clients see only the
  fields (`secret: {fields}`). A secret notification counts as pending.
- **Web Push** (C15, `src/modules/webpush.py`): the WebUI's browsers subscribe with `POST /api/push/subscribe
  {subscription, device}` (`GET /api/push/key` gives the VAPID public key; `DELETE /api/push/subscribe {endpoint}`).
  Subscriptions are rows of Archive `/api/hermes-store` (kind `push`). Every notification that rings on the WebUI is
  also pushed (title, plain text ≤ 300, link, id; never form values); 404/410 subscriptions are dropped. Env
  `HERMES_VAPID_PUBLIC_KEY` / `HERMES_VAPID_PRIVATE_KEY` / `HERMES_VAPID_SUBJECT`; empty = off.

## API (MVP)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/events/ingest` | Ingest one event and evaluate subscriptions |
| `POST` | `/api/dispatch/send` | Legacy direct send: `owner` → every client; concrete target + client name → that client; `metadata.quiet` → inbox only, no push (e.g. an external AI's write, Hestia-MCP) |
| `GET` | `/api/notifications` | Inbox (`filter` all/unread/pending, `source`, `before`, `limit`, `client`) |
| `GET` | `/api/notifications/counts` · `/clients` | Unread/pending counters · discovered clients |
| `POST` | `/api/notifications/{id}/seen` · `/seen-all` | Global read state |
| `POST` | `/api/notifications/{id}/answer` · `/answer/outcome` | First answer wins, routed to the asking module |
| `POST` | `/api/notifications/retract-stale` | Agenda job: retract handled messages from clients |
| `POST` | `/api/notifications/remind-pending` | Agenda job: one grouped «Da decidere» reminder (Cindy 5) |
| `POST` | `/api/notifications/{id}/secret` | Secret form `{client, values}` → forwarded to the module, never stored (Cindy 4) |
| `GET` · `POST` · `DELETE` | `/api/push/key` · `/api/push/subscribe` | Web Push: VAPID public key · browser subscription on/off (C15) |
| `GET` | `/api/ui/deliveries` | Delivery log for the plugin page *Consegne* (`since`, `before` cursor, `limit` ≤200, `flag` held/quiet/retracted/failed/answered/superseded/pending, `client`, `source`) → `{items, summary, next_before}`; every row: per-client `{state, at, attempts, retracted, detail}`, flags, answer, message preview (no event payload). 502 = Archive down |
| `GET` | `/api/ui/subscriptions` · `/api/ui/clients` | Active subscriptions (domain, event type, filters, channels) · clients reached now |
| `GET` | `/api/ui/inbox` · `/api/ui/inbox/counts` | Plugin page *Notifiche*: same as `/api/notifications` · `/counts` with `client=webui` by default; `counts` is the sidebar badge source |
| `GET` | `/api/ui/inbox/{id}/voice?format=mp3` | Audio of a notification sent also as voice (from Echo): `{mime_type, audio_b64, blob_id, duration_s}`; 404 without voice |
| `POST` | `/api/ui/inbox/{id}/seen` · `/api/ui/inbox/seen-all` · `/api/ui/inbox/{id}/answer` | Same logic as the `/api/notifications/*` actions (body `client` optional, default `webui`; answer body `{action_id}`, 409 = already handled) |
| `POST` | `/api/ui/inbox/{id}/secret` | Plugin door of the secret form: same as `/api/notifications/{id}/secret` (body `{values, client?}`; values never logged) |
| `GET` · `POST` · `DELETE` | `/api/ui/push/key` · `/api/ui/push/subscribe` | Plugin doors of Web Push for the WebUI shell (Impostazioni → Personali → Messaggi): same as `/api/push/*` |
| `GET` | `/api/ui/manifest` · `/ui/webui/hermes.js` | WebUI plugin manifest + bundle (plugin contract) |
| `GET` | `/api/module/recap` | Daily recap piece «Notifiche»: how many today, the important ones (warning/error), those still waiting for an answer; the recap itself (`replaces: athena.recap`) is excluded. Capability `recap_endpoint` |

System subscription (`service.action_required`) is bootstrapped at startup for the user (`owner`,
channel `{"type": "all"}` = every client; Telegram resolves `owner` to its `ALLOWED_USER_ID`); older `sys-action-required-<chat id>` subscriptions are
deactivated so alerts are not sent twice.
| `GET` | `/health` | Hermes health |

---

## WebUI plugin — inside view (2026-10-18, dossier `docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. The inbox shows the level icon and hides the emoji that module texts carry for Telegram.

Core module (`kind: "core"`, WebUI *Sistema* section, order 140), `api_prefix` `/api/ui/` (Hermes' own routes
are spread over `/api/notifications`, `/api/events`…, so the pages use small `/api/ui/*` doors instead):
- page **Notifiche** (`hermes-inbox`, order 140, P6 — ported from the WebUI built-in page, which redirects here):
  the inbox shared by every client (read here = read on Telegram). Filters *Da leggere · N* / *Da rispondere · N* /
  *Tutte*, module, *Anche da altri client*; grouped by day (Oggi, Ieri, …); level icon, repeat badge (↻), origin
  client, unread dot, title, message (Telegram-style HTML, sanitised: only b/i/u/s/code/pre/a(http)/br/blockquote);
  *Apri* on the module page of `_link` (marks it seen); the notification's buttons (first answer wins, 409 →
  «Già gestita da …»), the outcome or *Scaduta*, «Vista su Telegram»; *Segna tutte lette*; *Carica altre* (40 per
  page, `before` cursor). Items shown in a visible tab for 1.5 s are marked seen. While visible the page polls
  `/api/ui/inbox/counts` every 20 s and reloads when the counters move (no SignalR in plugins). Sidebar **badge**
  = page badge `{source: /api/ui/inbox/counts, field: unread}`. Deep link `?filter=unread|pending|all&source=`.
  The live toasts stay in the WebUI shell (it is the client); the page's *Avvisi a comparsa* select writes the
  shell's own preference (`localStorage` `hestia_notification_prefs`, same origin) and fires the window event
  `hestia:notification-prefs` `{toast}`.
  Since W7 (dossier 2026-10-24-tutto-brainstorm-cindy) the *Da rispondere* filter reads **Da decidere**; a secret
  notification shows its form in the card (password fields masked, *Invia* → `/api/ui/inbox/{id}/secret`, the
  values leave the page and are never kept); a button whose answer is `{execute: "command", command}` opens that tool
  on the *Comandi* page (`/p/mcp/comandi?command=…`).
- sub-page **Consegne** (`hermes-deliveries`, order 141, parent `notifiche`): every notification (newest first, paged) with its state on each client
  (consegnata / solo elenco / fallita / abbandonata, attempts, *ritirata* from the chat), *trattenuta* by
  presence (+ released in the digest), *silenziosa* (quiet inbox copy), *sostituita* (repeat chain), the answer
  (action, client, outcome) or the actions still waiting; filters by flag and client; active subscriptions and the
  clients reached. Read-only: the inbox to read and answer is the **Notifiche** page above.
- widget **Consegne oggi** (`hermes-today-widget`, s/m, auto): today's notifications, failed, held, waiting.
- Hermes down → the page shows «Hermes non raggiungibile» (SDK `hxk-state offline`).

Bundle: `ui/` (Lit, `@hestia/webui-sdk`) built in the Dockerfile Node stage →
`/ui/dist/webui/hermes.js` (outside `/code`: the compose dev mount of `src/` must not hide it; env
`HERMES_UI_DIST`, infrastructure). The manifest keys (`ui_manifest`, `ui_version`) go in the Hub registration.

## Hub registration

Registers at startup (retries) and re-registers every 60 s from a daemon thread (`hub-keepalive`), whatever the
first result: the Hub shows a service offline after 180 s without it and forgets it on restart. Until 2026-10-19 the
thread started only when every first attempt failed, so a healthy Hermes looked offline on *Mappa* (found by the
cloud test bench; regression test `TestHubKeepalive`).

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
| `hermes.repeat.reset_after_days` | int 30 days (1–365) | A repeat chain idle longer than this starts again from zero |
| `hermes.log.level` | enum (boot = `LOG_LEVEL`) | Log verbosity |

Env keeps only infrastructure: `HUB_API_URL`, `ARCHIVE_API_URL`, `HERMES_SERVICE_BASE_URL`,
`HERMES_SERVICE_VERSION`, `HERMES_HUB_REGISTER_RETRIES`, `HERMES_HUB_REGISTER_RETRY_DELAY`,
`STARTUP_WAIT_TIMEOUT_SECONDS`, `LOG_LEVEL` (boot default only).

## Assistant presence

Notifications below the presence `notify.level` (all/important/urgent) are **held**: stored, delivered silently, marked `held`. When the level relaxes Chronos calls `POST /api/notifications/release-held` and Hermes sends one digest «Mentre riposavo». `important` holds info/success without actions; `urgent` lets through only errors and events flagged `_urgent`.

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: Plugin title «Notifiche»; deliveries subtitle «Cosa è stato mandato, a chi e com'è andata»; agenda title «Pulisci le notifiche già gestite».
