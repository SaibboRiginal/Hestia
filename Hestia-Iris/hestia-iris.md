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
- POST /api/module/maintenance/reconcile
- POST /api/maintenance/reconcile

## Hub Registration

- name: iris
- service_type: module
- topology_tags: layer:domain, domain:email, status:experimental
- commands: email_search, email_send, email_thread, iris_reconcile

## Mail backend (via Hecate)

Iris holds no mail and no credentials. Every endpoint calls Hecate through Hub:
`/api/email/inbox` and `/api/email/messages` → `GET /api/gateway/email/messages` (`q` free text, Gmail
syntax or IMAP criteria, `since` ISO date; Hecate uses the Gmail API with the OAuth token, no IMAP); `/api/email/send` →
`POST /api/gateway/email/send` (adds `Re:` when `thread_id` is given); `/api/email/threads/{thread_id}` →
messages sharing the normalized subject; `/api/email/ingest` → Hecate `/api/ingest/trigger` (domain
modules such as Scout ask Iris, which owns the email domain). Search errors are soft
(`status=error`, `error`, `action_required=reauth_google` when Google must be re-authorized: Hecate
also pushes the Telegram re-auth button); send errors propagate Hecate's 503.

Previously Iris kept an in-memory list (lost on restart): nothing was read from or sent to a real mailbox.
