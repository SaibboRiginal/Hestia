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
- [ ] P6 of central settings for Oracle / Chronos / Telegram (docs/work/2026-10-10-central-settings)
- [ ] Marko: ok to merge branch `claude/project-thread-w9loez` into main, then `up-all.bat --build themis hercules hygieia wardrobe scout`
- [ ] Later (optional): one generic Archive module store instead of three copies
