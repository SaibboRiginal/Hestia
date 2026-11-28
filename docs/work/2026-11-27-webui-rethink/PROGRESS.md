# PROGRESS — WebUI rethought

## Piece 1 — navigation and look
- [x] SPEC v1.0 approved
- [x] `page(place=…)` in hestia_common.plugin_client + SDK types + docs
- [x] Manifests: place for agenda / assistant / notifications / system pages; labels (House hunting, Documents, Shared files)
- [x] Shell: icon rail + context panel (resizable, closable) + phone bottom bar; tabs for sub-pages on module pages
- [x] Settings → System: people's names, no module names; Search: no module names
- [x] Home: no System status tab, no Talk / Write here in the header
- [x] Theme Aurora (light/dark) default + Glass default; Claude themes renamed; ring logo + favicon
- [x] Translations (it + other catalogs) for every new text
- [x] DESIGN-SYSTEM.md, hestia-webui.md, ARCHITECTURE, root CHANGELOG
- [x] ng build: no errors (the two budget warnings are already on main)
- [x] bench screenshots (`/mnt/project-files/webui-ripensata/pezzo1/`), precheck, PR #141
- [x] merged by the thread once CI is green (Marko's standing rule)

## Piece 2 — one page pattern
- [x] SDK kit: `hxk-page-head`, `hxk-empty`, `hxk-ask` event caught by `HestiaElement` (opens the assistant on the page)
- [x] Every module list page uses the header (one primary action, icon-only refresh, «Ask»); back links / in-page nav on sub-pages removed
- [x] Empty states with an example to say in chat (Images, Documents, Agenda routines/dates, Supplements, People, Workouts/plans, Deadlines, Accesses, Memory, Shared files, Mood, Wardrobe, Thoughts/learning/recaps)
- [x] Developer text removed (Thoughts scores, thresholds, formula, setting paths); «X not reachable» → «Not available»
- [x] Module names out of people texts + gate `tools/governance/check_module_names.py` (precheck + CI)
- [x] Translations, docs (DESIGN-SYSTEM, SDK README, module docs, root CHANGELOG)
- [x] ng build, bench screenshots (`/mnt/project-files/webui-ripensata/pezzo2/`), precheck, PR

## Piece 3 — search everything + ask on the fly
- [x] Contract: catalog type `search` (plugin_client.search, ModuleKit.search, hestia_common.search, Hub, WebUI catalog)
- [x] Providers: conversations, memory, shared files (Oracle), people, deadlines, documents, workouts, expenses, clothes, email
- [x] Box: Ctrl+K or `/`, providers in parallel (2.5 s each, groups appear as they arrive), quick maths and dates
- [x] Ask on the fly: Tab or «?», `POST /api/webui/chat/quick` (Quick mode), «Quick questions» conversation, «Continue in chat»
- [x] Translations, swagger, docs (DESIGN-SYSTEM, hestia-webui, hestia-shared, Hub and provider modules, root CHANGELOG)
- [x] ng build, bench check, precheck, PR

## Piece 4 — mascot link
- [x] Contract: SDK `host.event(kind, data)`; `MascotService` (fixed rules → `react(kind, text?, action?)`, `reaction` signal, 15 s quiet time)
- [x] Pages emit: mood (Psyche save + tap), workout finished with records (Hercules), deadline done (Kairos), over budget once a month (Plutus)
- [x] Mascot: speech bubble with the reaction text and its button, `data-reaction` pose hook; click = mini chat (current or last conversation, «Open in chat», «Talk»), hold = Talk; the bottom-right bubble steps aside when a mascot is on screen
- [x] Translations, docs (DESIGN-SYSTEM, SDK README, hestia-webui, module docs, root CHANGELOG)
- [ ] ng build, bench screenshots (`/mnt/project-files/webui-ripensata/pezzo4/`), precheck, PR
