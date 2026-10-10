# SPEC — Hermes global notifications (every client) + WebUI notifications page

| Version | Source | Status |
|---|---|---|
| 1.3 | user via external chat (project thread "Notifiche su tutti i client", 2026-10-10) | Proposed — waiting for user approval |

## 1. Goal
A notification from Hestia reaches **every client** the user has (Telegram, WebUI, future ones), not only
Telegram. Each client renders it its own way. Answers (buttons) from any client go to the module that asked;
the first answer wins and the other clients show the notification as already handled. The WebUI gets a
proper notifications page (inbox) and a clean way to read, answer and manage notifications.

## 2. Current state (checked 2026-10-10)
- `Hestia-Hermes/src/modules/dispatch.py` `DispatchService.send` knows only `channel == "telegram"`; any other
  channel → `unsupported channel`. The WebUI never receives anything from Hermes.
- Subscriptions store `channels: [{"type": "telegram", "target": "$chat_id"|"owner"}]`: Archive seed commands
  (`iscriviti_calendario`, `iscriviti_sistema`, …), Hermes' system subscription, Oracle `memory_parsers`
  fallback. None of them was *meant* to be Telegram-only: Telegram was simply the only channel.
- One `outbound_events` row per subscription × channel; lifecycle `created/queued/delivered/seen/answered/
  failed/dead/superseded` already exists in Archive.
- Actions today: `_actions: [{text, command}]` → Telegram button `run:<command>` → Telegram executes the Hub
  command. No answer is recorded, nothing stops a second answer, no other client is told.
- Entity alerts without `_message` (e.g. a single Scout listing) are narrated **by Telegram** (it calls Oracle
  `/api/format`); batches are narrated by Hermes. So two clients would narrate twice, differently.
- WebUI: toasts + Oracle `notice` packets inside chat only; prefs per browser (`notice-prefs.service.ts`).
  Registers on Hub with `layer:client`, but declares no delivery endpoint.

## 3. Scope
In: Hermes multi-client delivery + answer handling; client delivery contract; Telegram and WebUI adapters;
WebUI notifications page + bell/badge + toasts; migration of existing subscriptions; docs/swagger.
Out: quiet hours / do-not-disturb (assistant-presence dossier decides *when*; Hermes only asks it later);
browser push when the WebUI tab is closed (possible later phase, §6.6); settings storage (Themis dossier).

## 4. Acceptance criteria
1. A notification emitted to `owner` is delivered to Telegram **and** WebUI; a client that is offline or
   fails is retried on its own, without re-sending to the clients that already got it.
2. A notification aimed at one client (`target_clients: ["telegram"]`) reaches only that client.
3. Pressing a button on any client sends the answer to the module that asked; a second answer from another
   client (or the same) is refused with "già gestita (da Telegram/WebUI)"; the other clients update the
   notification to "gestita" (Telegram removes the buttons and appends the outcome; WebUI updates live).
4. WebUI page **Notifiche**: list newest first, unread badge in the sidebar, filters (Da leggere, Da
   rispondere, Tutte), filter by module, mark read / mark all read, answer buttons, outcome shown.
   Notifications that arrived while the WebUI was closed are there when it opens.
5. New notification while the WebUI is open → toast (with buttons when it has actions) + badge, following the
   WebUI's display preferences.
6. Adding a future client = register on Hub with `layer:client` + `capabilities.notify_endpoint`; no Hermes
   code change.
7. Themis confirmations (Approva / Rifiuta) work through this exactly as SPEC central-settings v2.1 §3.6 says.

## 5. Design decisions

### 5.1 One notification, many deliveries
- A **notification** = one logical message (one `outbound_events` row, id = `notification_id`) with
  `title`, `message`, `level` (info/success/warning/error), `source` module, `domain`, `event_type`,
  `actions`, `target_clients` (`["*"]` = all) and per-client `deliveries: {client: {state, attempts, at,
  detail, ref}}` stored in the row payload. Lifecycle of the row: `created → delivered` (≥1 client) →
  `seen` → `answered` (or `dismissed` / `expired`); `failed`/`dead` only if **no** client got it.
- Dedupe stays as today (dedupe key without the channel part).
- No new table: Archive's `outbound_events` already fits; only list/query by state is needed (Archive owns DB).

### 5.2 Client discovery (Hub)
- Hermes reads the Hub registry: every service with topology tag `layer:client` **and**
  `capabilities.notify_endpoint` is a delivery target, addressed by its Hub name (`telegram`, `webui`).
  Cached, refreshed on Hub registry revision change. Delivery = `POST {HUB}/route/<client>/<notify_endpoint>`.
- Subscription channels become **targets**: `{"type": "all"}` (default) or `{"type": "client", "client":
  "telegram"}`. The old `{"type": "telegram"}` is read as legacy (see §5.6).

### 5.3 Client delivery contract (`POST <notify_endpoint>`)
```json
{ "notification_id": "…", "target": "owner", "title": "…", "message": "<HTML-safe text>",
  "level": "warning", "source": "themis", "domain": "settings", "event_type": "settings.proposal",
  "created_at": "…", "actions": [{"id": "approve", "text": "Approva", "style": "primary"}],
  "payload": {…optional raw entity…} }
```
→ `{"delivered": true, "ref": "<client message id>"}`. The client renders it (Telegram message + inline
buttons `ntf:<notification_id>:<action_id>`; WebUI SignalR push + inbox). `target: "owner"` is resolved by
the client (Telegram → first `ALLOWED_USER_ID`, as today).
Update contract (same endpoint, `"kind": "update"`): `{notification_id, state: "answered", answered_by,
action_id, outcome_text}` → clients mark it handled.

### 5.4 Answers: first wins, routed to the asking module
- Action definition by the emitting module (in `_actions`), agreed with the central-settings thread:
  `{"id":"approve","label":"Approva","style":"primary|danger|default","service":"themis","method":"POST",
  "path":"/api/settings/proposals/<id>/approve","body":{"by":"<client>"}}` (`text` accepted as alias of
  `label`; legacy `{text, command}` = Hub command, still supported). Hermes stores the actions on the
  notification; buttons carry only `<notification_id>:<action_id>` (Telegram 64-byte callback limit).
- Client → Hermes `POST /api/notifications/{id}/answer {action_id, client}`. Hermes claims the answer
  atomically (Archive state `answered` only if not already answered/expired) — first wins; a late answer gets
  `409 {answered_by, action_id}`.
- After the claim Hermes routes the action to the asking module through Hub (`<client>` in body replaced by
  the answering client name) and returns the module's response to the client; a module 409 (e.g. Themis
  `already_decided`) is passed through as "già gestita". Legacy `command` actions are executed by the
  answering client as today, which then reports the outcome (`/answer/outcome`). Hermes then sends the
  `update` to every other client. Hermes keeps no domain logic: it only claims, forwards and informs.
- **Closing from the module side:** an event whose payload has `closes: "<dedupe_key>"` (+ `decision`,
  `outcome_text`) — e.g. Themis `settings.proposal_closed` with `settings.proposal:<id>` — marks the matching
  notification answered/expired and fans out the `update`; it is not shown as a new notification unless it
  carries its own `_message`.

### 5.5 One narration for all clients
Entity payloads without `_message` are narrated **once** in Hermes (Oracle `/api/llm/generate`, as batches
already are) before fan-out, so every client shows the same text; Telegram's own Oracle formatting of
dispatched entities is removed (fallback text kept in Hermes).

### 5.6 Migration of existing subscriptions
Proposed default: existing `{"type": "telegram"}` channels become `{"type": "all"}` (they were never meant to
be Telegram-only). Done once by Hermes at startup via Archive (idempotent, logged); seed commands in Archive
and Oracle's `memory_parsers` fallback switch to `{"type": "all"}`. *(Open question for the user.)*

### 5.7 WebUI
- Backend (.NET): `POST /api/notify` (internal, reachable only through Hub; same guard style as the admin
  exception) → pushes `{"type":"notification"|"notification_update"}` on SignalR to every open browser.
  Registers `capabilities.notify_endpoint: "/api/notify"`. Proxy endpoints for the page:
  `GET /api/webui/notifications?state=&source=&limit=&before=`, `POST …/{id}/read`, `POST …/read-all`,
  `POST …/{id}/answer` → Hermes via Hub. Inbox data lives in Archive (via Hermes), not in the WebUI.
- Frontend: new module `notifiche` in `app.modules.ts` (icon `bell`), sidebar badge with unread count,
  `NotificationsService` (signals, SignalR), page with `hx-page-header`, segmented filter
  (Da leggere / Da rispondere / Tutte), module filter, grouped by day, each card: module icon, level colour,
  title, text, time, action buttons or outcome chip ("Approvata da Telegram · 10:42"), mark read.
  Toast on arrival with the same buttons; display preferences (toast on/off, only important) join the existing
  notice preferences in Impostazioni → Personali → Avvisi.
- Follows `DESIGN-SYSTEM.md`.

### 5.8 Telegram
Declares `notify_endpoint: "/api/notify"`; keeps `/api/dispatch/send` as a thin alias during the switch.
New callback `ntf:<id>:<action>` → Hermes answer; on 409 shows "già gestita da …" and removes buttons.
Handles `update` by editing the original message (needs `ref` = Telegram message id, stored by Hermes).

### 5.9 Module boundaries
Hermes = delivery, answer claim, fan-out of updates. Clients = rendering + collecting the answer. The asking
module (Themis, Forge, …) = acting on the answer. Archive = storage. Nobody else sends to the user.

### 5.10 Global vs per-client (user, v1.2)
- **Audience** of a notification: `global` (default: autonomous work, alerts, proposals) or `origin` — it
  answers something the user asked in a client session (e.g. "avvisami quando Forge finisce" from Telegram):
  then it carries `origin: {client, session_id}` and is **pushed only there**. Explicit "mandamelo su X"
  → that client. The origin comes from the request: subscriptions/jobs created from a chat store
  `origin_client` + `session_id` (clients already pass their session context to Oracle/commands).
- Every notification is still stored once and listed in every client's inbox: other clients show
  origin-only ones without toast/sound, under the filter "Anche da altri client" (WebUI) so nothing is lost.
- **Read state is global** (one row in Archive): seen on one client → Hermes marks it `seen` and sends the
  `update` to the others. WebUI: read live, badge drops. Telegram: the Bot API cannot mark a message read in
  the app, so Hermes' update edits the message (small "✓ vista su WebUI" mark; answered → buttons removed
  + outcome). When is it "seen"? WebUI: shown in a visible tab (toast/page) or marked read. Telegram: a button
  press, or any user message in that chat after delivery (the user opened the chat).

- **Telegram cleanup (user, v1.3, hybrid):** seen elsewhere → the message is edited at once ("✓ vista su
  WebUI"); after a delay it is deleted from the chat (still in the WebUI inbox). Delay = Hermes setting in
  Themis `hermes.telegram_cleanup_after` (default 6 h, capped at 47 h because a bot can delete its own
  messages only within 48 h; 0 = never delete). Never deleted while it still waits for an answer. The cleanup
  runs as an agenda job (Chronos), not a Hermes loop: Hermes deletes through Telegram's notify endpoint
  (`kind: "delete"`, `ref`).

## 6. Phases
1. Hermes: notification model, Hub client discovery, multi-client fan-out with per-client retry, answer
   claim + update fan-out, narration once, subscription migration; Archive query support; swagger.
2. Telegram adapter: `notify_endpoint`, `ntf:` callbacks, message edit on update.
3. WebUI backend: `/api/notify`, SignalR push, notifications proxy API, Hub capability.
4. WebUI frontend: Notifiche page, badge, toasts, preferences.
5. Docs: hestia-hermes.md, hestia-telegram.md, hestia-webui.md, swagger, ARCHITECTURE rule
   ("notifications are global; clients declare `notify_endpoint`").
6. (Later, optional) browser Web Push for the WebUI when no tab is open.
