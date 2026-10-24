# CHANGELOG — Everything from the brainstorm and Cindy

- v1.0 — 2026-10-24 — first plan: inventory, owners, shared decisions, 8 waves — Marko «tutto one shot» — user via project thread
- v1.1 — 2026-10-24 — origin set by the caller (+ Hestia-MCP for external AIs) instead of stamped by the Hub; `changes` is its own frame after `final` — the Hub forwards headers and cannot tell a user client from a module; a separate frame keeps `final` unchanged for old clients — implementation W1
- v1.2 — 2026-10-24 — W2: a routine run by an event is an agenda `event` (never fired by the tick) with `on`; the secret form is a `_secret` field of the notification, not an action; Web Push rides on the WebUI delivery (rings only when the WebUI rings) — keeps one scheduler and one delivery rule — implementation W2
