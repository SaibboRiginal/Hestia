# Spec changelog

- v1.0 — 2026-10-20 — first draft (Open-Meteo provider in Hecate, `weather_*` tools, personal city, Wardrobe fallback) — brainstorm item 7 — user via external chat
- v1.1 — 2026-10-20 — Hecate adds tomorrow's forecast to the daily recap via the per-module contract `GET /api/module/recap` — alignment with the Recap giornaliero thread — Hestia AI (coordinator)
- v2.0 — 2026-10-20 — several personal places (`themis.personal.places`) instead of one city; weather in the agenda (14 days, events with a location); outdoor activities in Hercules (plan with forecast + free time, confirm, log) — scope change — user via project thread
- v2.1 — 2026-10-20 — Marko approves; adds Google calendar «Allenamenti» owned by Hercules (activities + finished gym sessions as history, Hecate generic `calendars` endpoint), feedback question after each slot, morning coach nudge (agenda job `hercules.activity_morning`) — approval + refinement — user via project thread
- v2.2 — 2026-10-21 — as built: Hermes `closes` instead of a resolve call; weekly coach plan merged meanwhile → open intentions become `outdoor` needs and the planner avoids rain/dark (rule left to this thread by the coach dossier); P5 waits for the recap PR — implementation — Hestia AI
- v2.3 — 2026-10-22 — P5 as built: Hecate recap piece «Meteo», outdoor lines in the training piece — implementation after the recap contract reached main — Hestia AI
