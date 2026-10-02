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
`/api/email/inbox` and `/api/email/messages` → `GET /api/gateway/mail/messages` (`q` free text or IMAP criteria,
`since` ISO date); `/api/email/send` → `POST /api/gateway/mail/send` (adds `Re:` when `thread_id` is given);
`/api/email/threads/{thread_id}` → messages sharing the normalized subject. Hecate unreachable → 503, provider
not configured → Hecate's 503 detail.

Previously Iris kept an in-memory list (lost on restart): nothing was read from or sent to a real mailbox.
