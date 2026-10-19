# Hestia-Iris

Email domain service for Hestia.

## Purpose

Iris provides domain-level email operations and publishes command metadata for Oracle/Telegram discovery through Hub.

Iris owns email-domain business logic (search/send/thread abstractions). Provider gateway/runtime ownership is centralized in Hecate when provider mediation is required.

## Endpoints

- GET /health
- GET /api/logs
- GET /api/email/inbox
- GET /api/email/messages
- POST /api/email/send
- GET /api/email/threads/{thread_id}
- POST /api/email/subscriptions — a module declares its full rule set `{owner, rules}` (idempotent; new/changed rules → backfill)
- GET /api/email/subscriptions?owner= — list subscriptions
- DELETE /api/email/subscriptions/{owner}/{key}
- POST /api/email/subscriptions/{owner}/{key}/backfill — `{days}`; re-deliver matching mail of the last days (module «controlla ora»)
- POST /api/email/incoming — new mail headers from Hecate's watcher `{messages, source}`; 503 when a matched mail could not be stored
- GET /api/email/dispatch — subscriptions, last deliveries, counters, Hecate watcher state (used by the «Email» page)
- POST /api/email/check — ask Hecate's watcher for one check now
- POST /api/module/maintenance/reconcile
- POST /api/maintenance/reconcile

## Hub Registration

- name: iris
- service_type: module
- topology_tags: layer:domain, domain:email, status:experimental
- commands: email_search, email_send, email_thread, email_subscriptions (read only), iris_reconcile
- capabilities: `mail_dispatch: /api/email/incoming` + WebUI plugin (kind `core`)

## Mail backend (via Hecate)

Iris holds no mail and no credentials. Every endpoint calls Hecate through Hub:
`/api/email/inbox` and `/api/email/messages` → `GET /api/gateway/email/messages` (`q` free text, Gmail
syntax or IMAP criteria, `since` ISO date; Hecate uses the Gmail API with the OAuth token, no IMAP); `/api/email/send` →
`POST /api/gateway/email/send` (adds `Re:` when `thread_id` is given); `/api/email/threads/{thread_id}` →
messages sharing the normalized subject. Search errors are soft
(`status=error`, `error`, `action_required=reauth_google` when Google must be re-authorized: Hecate
also pushes the Telegram re-auth button); send errors propagate Hecate's 503.

## Mail dispatch — push to modules (`app/dispatch.py`)

Modules never poll mail: they **subscribe** to Iris with rules (`hestia_common.mail_client`, re-asserted at boot and
hourly) and Iris pushes matching mail to them. Hecate's watcher (`hecate.mail_watch`) is the only one looking at the
mailbox and posts new mail **headers** to `/api/email/incoming`.

- **Rules** (one per `(owner, key)`, needs `path` + `domain`): `senders` (exact address, or domain / `@domain`,
  subdomains included), `subject_contains` (any word), `labels` (Gmail label), `queries` (Gmail queries, checked by
  asking Hecate). The filled header groups must all match. One mail can match several modules.
- **Storage**: subscriptions in Archive `/api/iris-store` (kind `subscription`, id `<owner>:<key>`), cached in
  memory; loaded at startup (retried every 30 s). Rules removed from an owner's set are deleted.
- **Durable delivery**: for each match Iris fetches the full mail from Hecate and stores it in Archive (`POST
  /api/archive`) under the subscriber's domain with `reference_id = mail:<domain>:<gmail id>` (Archive dedupes), then
  rings the module once via Hub: `POST <path> {owner, key, domain, count, reference_ids, source}`. Module down →
  the mails wait unevaluated in Archive and the module picks them up when it is back. A storage failure answers 503,
  so Hecate keeps its cursor and offers the batch again.
- **Backfill**: a new or changed rule (fingerprint of the match fields) triggers a Hecate search of the last
  `backfill_days` (default 7); also exposed per subscription (`…/backfill`).
- Logs: `event=mail_dispatched owner= key= count=`, `event=mail_incoming count= delivered= unmatched=`,
  `[🔄] event=mail_ring_failed`, `[🔄] event=mail_store_failed`.

## WebUI plugin «Email»

Iris serves a small core plugin (`ui/`, entry `iris.js`): page **Email** (subscriptions, last deliveries, unmatched
count, watcher state) and quick action «Controlla email» (`POST /api/email/check`), so no log reading is needed.
