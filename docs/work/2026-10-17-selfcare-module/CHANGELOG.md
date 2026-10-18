# CHANGELOG — Self care module SPEC

- v1.0 — 2026-10-17 — first draft (products, routines with versions, logs, journal, stats, reminders, MCP, UI plugin) — new request — user via external chat
- v1.1 — 2026-10-17 — photos via shared Archive blob store `/api/blobs` (Guardaroba owns it); common `GET /api/module/context` endpoint — alignment with Guardaroba/Coach threads — ai
- v1.2 — 2026-10-17 — context endpoint shape and ModuleContext helper, photo upload rule — alignment with Guardaroba thread — ai
- v2.0 — 2026-10-17 — routines as goals (times per period + constraints, auto not-same-day from actives) instead of fixed days; planner; reminders off by default, max 2/week, one live reminder per routine with skip counter (generic version proposed for Hermes); journal per body part; start after plugin contract — user answers to §13 — user via external chat
- v2.1 — 2026-10-17 — cadence is a per-routine option (daily/fixed days mandatory, at least N per week/month, as needed); favourites + one-tap 'fatta oggi' widget on WebUI Home as top UI priority; journal optional and off by default — user message in Guardaroba thread relayed by channel session — user via external chat
- v2.2 — 2026-10-17 — Home quick log mapped to plugin contract v2.3 quick actions (§4.2b), manifest at /api/ui/manifest — plugin thread update — ai
- v2.3 — 2026-10-17 — reminders use Hermes 'replaces' chains (skip counter by Hermes), interim closes+new-event workaround dropped — Hermes reminders thread on main — ai
- v2.4 — 2026-10-18 — storage as one generic records table (Hercules protocol) instead of typed tables; settings/agenda keys `hygieia.*` (Themis owner = service name); step pause `paused_until`; reminder actions mapped to real endpoints; §14 implementation notes — implementation — ai
- v2.5 — 2026-10-18 — diary always available, setting `hygieia.journal.enabled` (and the planned `journal.prompt`) removed — Marko: "o c'è una feature o non c'è" — user via external chat
- v2.6 — 2026-10-18 — common reminder settings `hygieia.reminder.*` (hestia_common.reminders, off by default like every module); week start and currency are the shared personal settings `themis.personal.*` — Marko: rules common to every module — user via external chat
