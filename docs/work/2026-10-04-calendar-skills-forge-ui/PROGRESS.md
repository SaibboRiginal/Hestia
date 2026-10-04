# PROGRESS — calendar / skills / Sviluppo page

Spec: `SPEC.md` v2.1 · resume from the first unchecked box.

## D. Process
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG) with version + source
- [x] `CLAUDE.md` work protocol + Forge prompt: Version/Source header, source tags in changelogs

## A. Calendar
- [x] A1 reproduced: mini/arrows work in week/day; in **month view** a mini click inside the same month changed nothing visible and arrows move by month → `focusDay()` (month → day view), selected day highlighted in all views
- [x] A1 header arrows: per-view step + explicit labels; day header / day number opens the day
- [x] A4 24h everywhere (`fmt.time` manual HH:mm), kit `hx-date`/`hx-time`/`hx-datetime`, editor migrated (verified with en-US browser locale)
- [x] A2 window lane (strip + sticky time-range label + tint) / band / hidden; plain-language details; month bar tooltip
- [x] A3 frequent from RRULE (fallback: count), "Ricorrenti" row, popover with every time + ok/failed, failed never compacted
- [x] A8 Chronos `meta.runs` (last 50) + `run`/`created_by` in occurrences; swagger + hestia-chronos.md (tests: not run, user rule)
- [x] A5 focused-view policy + "N nascoste" bar (upcoming only) with Mostra tutto / Regole…
- [x] A6 calendar "Vista" popover (v2.1: not mirrored in Impostazioni)
- [x] A7 `template()` in hestia_common + `register_async(templates=)`; Chronos `/api/agenda/templates` (+create); Scout, Athena, Argus, Hephaestus register templates
- [x] A7 WebUI wizard (split "Nuovo", 3 steps: scegli · dettagli · conferma; own small schema form) + backend proxy
- [ ] A9 extras (now line check, Log link, NL quick add, ICS) — pick after the core
- [x] Docs: hestia-webui.md, hestia-chronos.md, hestia-shared.md, swagger, DESIGN-SYSTEM.md, root CHANGELOG
- [x] Checks: `ng build` clean, py_compile/ruff, Playwright screenshots (mocked API). Pending on user side: .NET build + real run

## B. "Crea con Hestia"
- [ ] Kit `<hx-assistant>` drawer (SignalR chat, packets, context packet → client instructions)
- [ ] Entry points: calendar (Nuovo split, empty slot, event details), Commands, Sviluppo, global shortcut
- [ ] Oracle agenda tools coverage (create/update/skip/move/cancel) + `agenda.planned` notices; page refresh on notices
- [ ] Agenda links + cascade (`meta.links`, cancel/error propagation) — used by Forge tasks
- [ ] Assistant proposes a Forge task when no tool can do it (prompt rule in Oracle)
- [ ] Docs

## C. Sviluppo page
- [ ] Oracle claude runner `stream-json` → transcript saved per task; local engines log turns
- [ ] Hephaestus endpoints: transcript, tests, files, workdoc, events, logs, repo/* (swagger)
- [ ] WebUI backend proxy controller
- [ ] Frontend: tasks list, task detail tabs, diff viewer, transcript viewer, repo browser
- [ ] Calendar links to Sviluppo/Log; docs
