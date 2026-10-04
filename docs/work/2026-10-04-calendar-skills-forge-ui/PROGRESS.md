# PROGRESS — calendar / skills / Sviluppo page

Spec: `SPEC.md` v2.4 · resume from the first unchecked box.

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
- [x] A9 extras: now line (existed) + working-hours shading, occurrence "Log del modulo", "Aggiungi rapido" (Chronos `/api/agenda/parse` via Oracle → editor prefilled), ICS feed (`/api/agenda/ics`, WebUI `feed.ics` + `WEBUI_ICS_KEY`)
- [x] Docs: hestia-webui.md, hestia-chronos.md, hestia-shared.md, swagger, DESIGN-SYSTEM.md, root CHANGELOG
- [x] Checks: `ng build` clean, py_compile/ruff, Playwright screenshots (mocked API). Pending on user side: .NET build + real run

## B. "Crea con Hestia"
- [x] Drawer `<hx-assistant>` (`features/assistant/`, lazy) + `AssistantService` (context packet, `changed$`); own ChatService channel/session; ChatHub `context` → client instructions
- [x] Entry points: sidebar + Ctrl/⌘+J; calendar (Nuovo → Crea con Hestia…, editor "Chiedi a Hestia", details "Chiedi a Hestia"); Sviluppo; Comandi
- [x] Oracle agenda tools coverage (+ ripristina, sposta_occorrenza, modelli, da_modello, collega) + `agenda.planned` / `forge.task` notices; calendar and Sviluppo reload on notices
- [x] Agenda links + cascade (`meta.parent`, cancel cascade, child fail/cancel marks parent, `/link` `/fail` `/links`); Forge `agenda_parent` (mirror linked, failed task → `/fail`, cancelled link → proposed task rejected)
- [x] Oracle analyst rule 8: no tool → propose Forge task, ask, `forge_develop` (+ `agenda_parent`)
- [x] Docs: hestia-chronos/webui/hephaestus/oracle/shared.md, DESIGN-SYSTEM.md, swagger, compose (`WEBUI_ICS_KEY`), root CHANGELOG
- [x] Checks: `ng build` clean (initial < budget), ruff (only pre-existing findings), ad-hoc check of cascade/cycle/fail with a fake Archive, parse/ICS helpers, Playwright screenshots (drawer wide/phone dark, details, logs, ICS)
- [ ] Pending on user side: .NET build + real run (drawer with Oracle, agenda tools, quick add, ICS on a phone)

## C. Sviluppo page
- [x] Oracle claude runner `stream-json` → live raw file on the shared mount, imported as normalized transcript per task; local/cloud engines emit the same events
- [x] Hephaestus endpoints: transcript, files, workdoc, tests, logs, events, retry, `parent_task`; repo branches/tags/log/commits/compare/tree/file/dossiers (swagger) — manual check on this repo's git (tests: not run, user rule)
- [x] WebUI backend proxy `ForgeController` (`/api/webui/forge/*`) — .NET build pending on user side
- [x] Frontend `features/forge/`: task list, conversation (transcript viewer), composer "Chiedi una modifica", context panel (Panoramica/File/Diff/Dossier/Test/Log/Ramo), new-task modal, repository mode (graph log, commit, files, branches, compare, tags, dossiers); kit `hx-diff` + `hx-markdown`
- [x] Calendar: Forge items → "Apri in Sviluppo" (Log link → A9)
- [x] Docs: hestia-hephaestus.md, hestia-oracle.md, hestia-webui.md, DESIGN-SYSTEM.md, swagger, root CHANGELOG
- [x] Checks: `ng build` clean, ruff on changed Python, Playwright screenshots (mocked API with real repo data; wide/phone/dark)
- [ ] Pending on user side: .NET build + real run with a Forge task (Claude and local engine)
- [ ] Later: SignalR push instead of polling
