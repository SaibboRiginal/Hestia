# PROGRESS — calendar / skills / Sviluppo page

Spec: `SPEC.md` v2.0 · resume from the first unchecked box.

## D. Process
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG) with version + source
- [x] `CLAUDE.md` work protocol + Forge prompt: Version/Source header, source tags in changelogs

## A. Calendar
- [ ] A1 reproduce nav bug (Playwright + mocked API), fix mini-calendar → anchor, sync mini month
- [ ] A1 header arrows: per-view step + explicit labels; day header / day number opens the day
- [ ] A4 24h everywhere (`hourCycle h23`), kit `<hx-date>` / `<hx-time>`, replace datetime-local in editor
- [ ] A2 window lane rendering (time grid, time range always visible) + month bar + plain-language details + mode setting
- [ ] A3 frequent detection + compact summary chips (grid top row / month) + occurrence list popover
- [ ] A8 Chronos per-occurrence run log (`meta.runs`) + `run` field in occurrences (+ tests later, docs)
- [ ] A5 focused-view policy (manual / frequent / rare / one-off / focused day / past) + "+N nascoste" hint
- [ ] A6 calendar "Vista" settings popover (+ mirror in Impostazioni)
- [ ] A7 `AgendaTemplate` in hestia_common + Chronos `/api/agenda/templates` + module registrations
- [ ] A7 WebUI wizard (split "Nuovo" button, 4 steps, schema form reused from Commands)
- [ ] A9 extras (now line check, Log link, NL quick add, ICS) — pick after the core
- [ ] Docs: hestia-webui.md, hestia-chronos.md, swagger, DESIGN-SYSTEM.md (new kit parts), root CHANGELOG
- [ ] Checks: `ng build` clean, py_compile/ruff, Playwright screenshots; .NET builds locally (user)

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
