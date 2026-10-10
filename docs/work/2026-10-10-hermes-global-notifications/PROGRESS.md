# PROGRESS — Hermes global notifications

Spec: `SPEC.md` v1.3 · resume from the first unchecked box.

- [x] Current state studied (Hermes dispatch, subscriptions, Telegram actions, WebUI notices)
- [x] Dossier created (SPEC v1.0 → v1.3 with the user)
- [x] User approves SPEC; existing Telegram subscriptions become global (user, 2026-10-10)
- [x] P1 Archive: compare-and-set state update (`only_if_states`, `payload_merge`), list filters, states `dead`/`expired`
- [x] P1 Hermes: `clients.py` (Hub discovery), `notifications.py` (one notification, fan-out, per-client retry,
      answer claim + routing, global seen, close by dedupe key, inbox, retract job), batch publisher, legacy direct send
- [x] P1 Subscriptions global: Hermes system subscription, Archive seed commands, Oracle parser (`{"type": "all"}`)
- [x] P1 Forge: requester chat → origin client; no target → every client (WebUI tasks were notified nowhere)
- [x] P2 Telegram adapter (`/api/notify`, `ntf:` callbacks, seen on user activity, edit on update, delete on retract)
- [x] P3 WebUI backend (`/api/notify` internal-only, SignalR `ReceiveNotification`, `/api/webui/notifications*`)
- [x] P4 WebUI frontend (Notifiche page, sidebar badge, toasts with per-browser preference) — `ng build` clean
- [x] P5 Docs: hestia-hermes.md, hestia-telegram.md, hestia-webui.md, swagger, ARCHITECTURE rule
- [ ] Marko: .NET build + real run (WebUI backend not buildable in the cloud container); pytest per user rule not run by Claude
- [ ] When Hermes moves to central settings: retract delay (6 h) becomes Themis setting `hermes.retract_after`
