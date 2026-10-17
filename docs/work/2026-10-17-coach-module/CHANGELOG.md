# CHANGELOG (spec) — Coach module

- v1.0 — 2026-10-17 — spec created: domain module Coach (fitness), Archive coach-store, live workout,
  records/stats, progression + adaptation engines in Coach, MCP tools, agenda/Hermes, Themis settings,
  WebUI via plugin contract, phases P1–P5 — source: user via external chat (project thread).
- v1.1 — 2026-10-17 — port 19019, shared `GET /api/module/context`, shared media store owned by Guardaroba —
  reason: alignment with sibling threads Guardaroba / Self care — source: coordination between project threads.
- v1.2 — 2026-10-17 — §8 aligned to the plugin contract (parent sub-pages, widget params, native live components) — reason: contract draft on main — source: thread Plugin dei moduli nei client.
- v1.3 — 2026-10-17 — §9 context contract detailed (ModuleContext helper, response shape) — reason: Guardaroba SPEC v1.1 — source: thread Modulo Guardaroba.
- v1.4 — 2026-10-17 — §8/§11 follow plugin contract v2.0 (UI bundle in Hestia-Coach/ui/, ui_manifest, host.notify) — reason: contract changed after Marko's feedback — source: thread Plugin dei moduli nei client.
- v2.0 — 2026-10-17 — module renamed Hercules (Hestia-Hercules, tools/settings `hercules_*`/`hercules.*`); gym only
  (cardio/sports stay on Garmin); offline first with outbox sync (§8.0); adaptation and template changes are a
  conversation with the assistant + feedback tool, no Hermes proposals; reminders off by default, one live max —
  reason: Marko's answers to §13 — source: user in project thread.
- v2.1 — 2026-10-17 — §8.0 uses plugin contract v2.2 offline support (PWA cache, host.online, host.store) — reason: contract update — source: thread Plugin dei moduli nei client.
- v2.2 — 2026-10-17 — §8.2b quick actions (start today, resume, log bodyweight, skip today) — reason: plugin contract v2.3 — source: thread Plugin dei moduli nei client.
- v2.3 — 2026-10-17 — §6.2b optional training goals (generic N per day/week/month, then per template/muscle), one-tap 'fatto oggi' from Home with favourites, reminders only when behind (max 2/week, one live); implementation waits for plugin contract — reason: Marko's messages (this thread + Guardaroba thread, applies to all modules) — source: user in project threads.
- v2.4 — 2026-10-17 — §6.3 reminder uses Hermes replaces/resolves contract (skip counter by Hermes) — reason: Hermes reminders on main (040f1f6) — source: coordinator relay.
