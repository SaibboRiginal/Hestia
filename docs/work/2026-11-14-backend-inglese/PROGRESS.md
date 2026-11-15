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
- [x] Phase 2b: settings labels/help/groups/options translated by Themis (`settings_client.translated`), tool titles
      (MCP `ui_tools`), English `locales/en/tools.json` (276 tools), `follow_personal()` in every module showing texts
- [x] Phase 2c: notices and errors of every module (Oracle warnings, llm_setup details, Forge, backup, health,
      wardrobe, expenses, mood…) through `tr`; English catalog +1128 texts; model-facing leftovers (Forge export
      for an AI, reaction lines, presence lines) rewritten in English; test `test_every_module_text_has_an_english_translation`
- [ ] Phase 2d: WebUI
- [ ] German, French, Spanish catalogs
