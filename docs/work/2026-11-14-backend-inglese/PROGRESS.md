# Progress

- [x] Collect every hidden Italian text (tools, parameters, response prompts, module prompts)
- [x] Tool and parameter descriptions, response prompts in English (28 files + Archive manifest)
- [x] `hestia_common.i18n` + `locales/it/tools.json` (people texts of the tools), wired in `areas.for_people`,
      MCP `ui_tools`, Telegram forms
- [x] Internal module prompts in English (Athena, Chronos, Forge, Oracle, Plutus, Scout, Wardrobe, Demeter,
      Kairos, Metis, origin, Themis)
- [x] Module manuals and `when_to_use` in English
- [x] Tests updated where they pinned Italian prompt text; all module suites green
- [x] Docs: hestia-shared.md, ARCHITECTURE rule 13, telegram, mcp, root CHANGELOG
- [x] Phase 2a: `i18n.t` + `locales/en/messages.json`; Telegram texts wrapped (codemod on function-body literals,
      edge translation in `ui`, keyboard, commands, labels, dates); test `Hestia-Telegram/tests/test_language.py`
- [ ] Phase 2b: settings labels/help where Themis serves them, tool titles, notices and errors of the modules
- [ ] Phase 2c: WebUI
- [ ] German, French, Spanish catalogs
