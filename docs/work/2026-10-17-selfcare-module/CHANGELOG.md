# CHANGELOG — Self care module SPEC

- v1.0 — 2026-10-17 — first draft (products, routines with versions, logs, journal, stats, reminders, MCP, UI plugin) — new request — user via external chat
- v1.1 — 2026-10-17 — photos via shared Archive blob store `/api/blobs` (Guardaroba owns it); common `GET /api/module/context` endpoint — alignment with Guardaroba/Coach threads — ai
- v1.2 — 2026-10-17 — context endpoint shape and ModuleContext helper, photo upload rule — alignment with Guardaroba thread — ai
- v2.0 — 2026-10-17 — routines as goals (times per period + constraints, auto not-same-day from actives) instead of fixed days; planner; reminders off by default, max 2/week, one live reminder per routine with skip counter (generic version proposed for Hermes); journal per body part; start after plugin contract — user answers to §13 — user via external chat
- v2.1 — 2026-10-17 — cadence is a per-routine option (daily/fixed days mandatory, at least N per week/month, as needed); favourites + one-tap 'fatta oggi' widget on WebUI Home as top UI priority; journal optional and off by default — user message in Guardaroba thread relayed by channel session — user via external chat
- v2.2 — 2026-10-17 — Home quick log mapped to plugin contract v2.3 quick actions (§4.2b), manifest at /api/ui/manifest — plugin thread update — ai
