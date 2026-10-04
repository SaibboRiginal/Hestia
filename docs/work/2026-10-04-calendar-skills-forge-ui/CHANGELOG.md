# CHANGELOG (spec) — calendar / skills / Sviluppo page

- v1.0 — 2026-10-04 — spec created from the user's request (calendar bugs & views, module wizards,
  prompt-generated reusable Skills with linked non-blocking generation, Forge/Repo page, version+source
  in dossiers) — source: user via external chat (Claude Code cloud session).
- v2.0 — 2026-10-04 — B replaced: no prompt→plugin "Skills"; instead a contextual "Crea con Hestia" chat
  drawer usable from every page + new capabilities built as MCP tools by Forge, with linked non-blocking
  agenda items. A2: window time range must stay visible in hour views. C2: Codex/Claude-like layout
  (chat + files/diff/branch/md panels). Manual items always visible (A5 confirmed). — reason: user
  feedback on v1.0 — source: user via external chat.
- v2.1 — 2026-10-04 — A1: mini-calendar click from month view opens the day view (root cause: in month view a
  click inside the same month changed nothing visible); A6: calendar settings live only in the calendar "Vista"
  popover (not mirrored in Impostazioni) — reason: implementation, one place for calendar-specific options —
  source: AI (implementation decision, ext-chat session).
- v2.2 — 2026-10-04 — A7: templates kept in Chronos memory and re-asserted with the rules (no DB); wizard has 3
  steps with a simple repeat instead of the full RRULE builder; first templates Scout/Athena/Argus/Hephaestus —
  reason: implementation (keep Archive the only DB, simpler UX) — source: AI (implementation, ext-chat session).
- v2.3 — 2026-10-04 — C: raw Claude stream written live by Oracle on the shared worktree mount and normalized by
  Hephaestus; context panel merged with the task tabs, Repository as a mode of the Sviluppo page; follow-up via
  `parent_task`; retry endpoint; polling for live updates — reason: implementation (keep Oracle the only Claude
  Code owner, one place per piece of information, engines are headless) — source: AI (implementation, ext-chat session).
