# Hestia-Iris

Email domain service for Hestia.

## Purpose

Iris provides domain-level email operations and publishes command metadata for Oracle/Telegram discovery through Hub.

## Endpoints

- GET /health
- GET /api/logs
- GET /api/email/inbox
- GET /api/email/messages
- POST /api/email/send
- GET /api/email/threads/{thread_id}

## Hub Registration

- name: iris
- service_type: module
- topology_tags: layer:domain, domain:email, status:experimental
- commands: email_search, email_send, email_thread
