# Backend all English, people texts in the owner's language

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (Marko, 2026-11-14: «utente lingua che usa, backend tutto inglese») | phase 1 done |

## Goal
Every text the model reads is English; every fixed text a person reads comes from translation files in the
owner's language (`themis.personal.language`). The chat answer follows the language the owner writes in;
what the assistant writes on its own follows the language setting (dossier `2026-11-14-lingua-personale`).

## Scope (phase 1, this PR)
- Tool `description`, parameter descriptions and `response_prompt` of every tool (MCPTool and the old Archive
  command manifest) in English.
- Internal module prompts in English: Athena (strategist, reflection, learning, docs check, auditor,
  consolidator), Chronos (agenda parse, routine wrapper), Forge (review, plan, fix, resume), Oracle (loop
  guard, turn guards, conversation goal and its tools, queued messages, agent loop notes, user questions,
  memory notes, image description, payload summary, default file messages), Plutus (PayPal mail, categories,
  statements), Scout (extraction), Wardrobe (photo), Demeter, Kairos, Metis, origin lines and write refusals in
  `hestia_common.origin`, Themis unknown-key hint.
- Module manuals (`manual`, `when_to_use`) read by `module_manual` in English.
- New `hestia_common.i18n` + `hestia_common/locales/<lang>/tools.json`: the people texts of each tool
  (summary, field help) — the original Italian texts, so «Scopri», «Comandi» and the Telegram forms stay in
  the owner's language. Fallback Italian.
- `areas.for_people(tool, lang)` and Telegram `inputs.fields` read the catalog first.

## Phase 2 (next PR)
Translation files for the other fixed people texts (WebUI, Telegram, settings labels and help, tool titles,
error messages, notices), following `themis.personal.language`.

## Acceptance criteria
- No Italian sentence in a prompt, tool description, parameter description or `response_prompt`.
- People still read the same Italian texts on tools (summary and field help) when the language is Italian.
- Parsers accept the old Italian keys too (strategist `AZIONE`, review `alta/media/bassa`, Forge
  `semplice/difficile`, loop check `aspetta`), and stored values do not change.
- All module test suites green; precheck 0 failed.

## Design decisions
- Model-generated text meant for people (memory facts, Athena proposals, review issues, clothing names) is asked
  in the owner's language (`identity.LANGUAGES[i18n.language(settings.get)]`), facts in the language of the
  owner's own words.
- Keyword detectors on what the owner writes (mood, memory intent, user control) stay as they are: they read
  the owner's words, not a prompt.
- Routine instructions are the owner's own text and stay in the owner's language; the wrapper is English and
  says to answer in the instruction's language.
