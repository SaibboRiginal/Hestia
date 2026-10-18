# PROGRESS — Self care module (Hestia-Hygieia)

Read SPEC.md first. Resume from the first unchecked box.

- [x] Study repo, module patterns (Scout, Dummy, Archive presence store, Themis, agenda, Hermes actions)
- [x] Agree ports/storage with parallel threads (Guardaroba 19017, Self care 19018, Coach 19019; shared media store owned by Guardaroba)
- [x] SPEC v1.0 written
- [x] Marko confirmed SPEC (v2.0: flexible goals, few non-stacking reminders, journal per body part)
- [ ] ON HOLD (Marko 2026-10-17 20:24): wait until he finishes the core topics AND the plugin contract is on main, then start phase 1. Note: plugin contract v2.6 phase 1 is on main (fbbba6b: hestia_common.plugin_client, Hub /api/discovery/catalog, SDK Hestia-Shared/webui-sdk, kit hxk-*, quick log <hxk-quicklog>; UI goes in Hestia-Hygieia/ui/). Plugin P2 on main (9192e19): WebUI loads bundles, Home quick-action strip, pages /p/<module>/<page>; how-to Hestia-Shared/webui-sdk/README.md + DESIGN-SYSTEM.md §9; Scout P3 = reference module. Journal: kept optional, off by default (his answer pending)
- [ ] Phase 1 — backend core (skeleton, Archive tables + store, products/areas/lists, routines+versions, logs, today, MCP tools, tests)
- [ ] Phase 2 — tracking & insight (events, stats, prediction, alerts, conflicts, timeline, journal, shopping)
- [ ] Phase 3 — reminders (agenda jobs, Hermes buttons, snooze)
- [ ] Phase 4 — UI plugin (after plugin contract on main): page 6 tabs + widgets
- [ ] Phase 5 — extras (photos, barcode/Open Beauty Facts, import/export)
- [ ] Docs: hestia-hygieia.md, swagger, AI-GUIDE table, root CHANGELOG
