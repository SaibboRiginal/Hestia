# Progress

- [x] Read dossiers (client plugins, coach, self care, wardrobe, Hermes repeat) and compare code on main
- [x] Typecheck + build the four plugin bundles; py_compile the touched services; CI green on 182d68d
- [x] Small fixes (see SPEC «Fixed»)
- [x] v1.1 Marko's answers: personal settings `themis.personal.*` (Themis owns, modules `follow_personal()`),
      common reminders `hestia_common.reminders` in Hercules/Hygieia/Wardrobe, tools renamed `fitness_*`/`wardrobe_*`
- [x] Docs: ARCHITECTURE rules, service docs, Themis doc, swagger register `follows`, dossiers; Themis unit test
      `tests/test_themis_personal.py` (not run by the suite here; checked by calling it directly)
- [x] All Python suites, .NET + Angular builds, local real run of the stack (SPEC «Verified»)
- [x] Fixes from the real run (SPEC «Fixed after the real run») with regression tests
- [x] P6 of central settings for Oracle / Chronos / Telegram + Scout/Athena models as Oracle use cases
      (docs/work/2026-10-10-central-settings v2.4); all suites green again; Oracle live: 94 settings registered, live change applied
- [x] Other dossiers: .NET build ticks / notes, Hermes retract item closed
- [ ] Merge into main (or PR), then Marko: `up-all.bat --build` (whole stack: shared lib and many modules changed)
- [ ] Later (optional): one generic Archive module store instead of three copies
