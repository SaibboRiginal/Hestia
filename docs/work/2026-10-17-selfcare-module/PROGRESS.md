# PROGRESS — Self care module (Hestia-Hygieia)

Read SPEC.md first. Resume from the first unchecked box.

- [x] Study repo, module patterns (Scout, Dummy, Archive presence store, Themis, agenda, Hermes actions)
- [x] Agree ports/storage with parallel threads (Guardaroba 19017, Self care 19018, Coach 19019; shared media store owned by Guardaroba)
- [x] SPEC v1.0 written
- [x] Marko confirmed SPEC (v2.0: flexible goals, few non-stacking reminders, journal per body part)
- [x] Hold lifted (Marko 2026-10-18, "fai partire self care"). Was ON HOLD (Marko 2026-10-17 20:24): wait until he finishes the core topics AND the plugin contract is on main, then start phase 1. Note: plugin contract v2.6 phase 1 is on main (fbbba6b: hestia_common.plugin_client, Hub /api/discovery/catalog, SDK Hestia-Shared/webui-sdk, kit hxk-*, quick log <hxk-quicklog>; UI goes in Hestia-Hygieia/ui/). Plugin P2 on main (9192e19): WebUI loads bundles, Home quick-action strip, pages /p/<module>/<page>; how-to Hestia-Shared/webui-sdk/README.md + DESIGN-SYSTEM.md §9; Scout P3 = reference module. Journal: kept optional, off by default (his answer pending)
- [x] Phase 1 — backend core (Archive `selfcare_records` + `/api/selfcare-store`, Hygieia service, lists, products, routines+versions, logs, today, 18 MCP tools, tests written in `Hestia-Hygieia/tests` — not run, rule: no pytest here)
- [x] Phase 2 — tracking & insight (events, stats, finish prediction, alerts, conflicts + step alternation, timeline, period, journal, shopping)
- [x] Phase 3 — reminders (agenda jobs hygieia.planner / hygieia.alerts, Hermes `replaces` chains, buttons, snooze)
- [x] Phase 4 — UI plugin: 8 pages, 4 widgets, 2 Home quick actions (tsc + esbuild OK locally)
- [x] Phase 5 — extras (photos, barcode/Open Beauty Facts, import/export) — dropped 2026-10-30 (Marko: open items done or dropped)
- [x] Docs: hestia-hygieia.md, swagger, Archive doc, AI-GUIDE table, root CHANGELOG, compose, CI
- [ ] Marko: `up-all.bat --build hygieia archive` and a real run (Docker build of the UI bundle, Themis/agenda registration, Hermes buttons)
- [x] Journal: always available, no on/off setting (Marko 2026-10-18, SPEC v2.5)
- [x] Real run on the cloud bench (2026-10-19, fake LLM): products with PAO, routine with retinol/AHA conflict warning, versions + undo, Home chips + Annulla, chat `selfcare_today` / `selfcare_product_update` → UI + shopping list, reminder once a day in the WebUI inbox, Hermes chain «Saltato 2 volte» + «Fatto» all pass; fixes found: after a retinol evening the AHA came back «suggested», the clash reason did not name the product → `docs/work/2026-10-19-prove-reali-banco/`. Left for Marko: Telegram buttons, real model
