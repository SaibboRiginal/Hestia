# Backend all English, people texts in the owner's language

| Version | Source | Status |
|---|---|---|
| 2.0 | user via external chat (Marko, 2026-11-14: «utente lingua che usa, backend tutto inglese»; 2026-11-16: «togli tutto l'italiano!! e devono usare tutti la lingua!!») | phases 1, 2a–2d and 3 (English source, Italian only in the catalog) done |

## Goal
Every text the model reads is English; every fixed text a person reads comes from translation files in the
owner's language (`themis.personal.language`). The chat answer follows the language the owner writes in;
what the assistant writes on its own follows the language setting (dossier `2026-11-14-personal-language`).

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

## Phase 2 (fixed people texts)
- `i18n.t(text, *args, **kw)` (imported as `tr`): the Italian text in the code is the key of catalog
  `locales/<lang>/messages.json`; missing → English → the Italian source; with arguments it is `str.format`-ed.
  `SettingsClient.follow_personal()` registers the process language reader (`i18n.use`).
- **2a Telegram** (done): every literal people read in function bodies goes through `tr(...)`; the `ui` helpers
  (button, card title/subtitle/footer, note, outcome, error), the bottom keyboard (shown and matched in both
  languages), bot commands and description, field labels and dates translate at the edge; English catalog
  for all Telegram texts. A file sent without a caption asks the model in English and to answer in the owner's
  language.
- **2b Settings and tools** (done): Themis serves every setting text translated (`settings_client.translated`);
  tool titles through `tr`; English `locales/en/tools.json`; tool texts fall back lang → English → Italian.
- **2c Module texts** (done): every Italian literal a person reads in the modules' function bodies goes through
  `tr`; technical strings (SQL, headers, document styles) and model-facing lines are never translated: those are
  English in the code.
- **2d WebUI and plugins** (done): the same `locales/<lang>/messages.json`. Themis `GET /api/settings/i18n?lang=`
  → `{language, messages}` (English merged under the language's own; Italian = empty map). The WebUI serves it
  public at `/api/webui/i18n` and as a script `/api/webui/i18n.js` (`globalThis.__hestiaI18n`) that `index.html`
  loads before any bundle, so module-level constants of the shell and of every plugin are translated too.
  Angular: `tr()` and the pipe `{{ 'Testo' | tr }}` (`core/i18n.ts`); plugins: `tr` of `@hestia/webui-sdk`.
  Saving «Lingua» (set, reset, undo) reloads the page. Technical strings (SVG paths, CSS) are never wrapped.
- Languages: Italian and English only (Marko 2026-11-16); German, French and Spanish removed from «Lingua».
  The standard for every module is `docs/LANGUAGES.md`, enforced by `tools/governance/check_i18n.py`.

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

## Phase 3 (v2.0, 2026-11-16): no Italian in the code
Marko: «togli tutto l'italiano!! e devono usare tutti la lingua!!».
- The source flips: every `tr` text in Python, WebUI and plugins is English; the one catalog becomes
  `locales/it/messages.json` (English → Italian); `locales/en/messages.json` is gone. `i18n.SOURCE = "en"`.
- Labels declared at import/registration (manifests, capabilities, `llm_usecases`, agenda rules, settings, areas,
  module labels, catalogs) are plain English, never `tr` (it froze the language at startup); `i18n.localize`
  (WebUI interceptor, Telegram) and `settings_client.translated` translate them at the edge.
- Every module follows «Lingua»: Iris and Atlas too (`SettingsClient(...).follow_personal()`).
- Dates and numbers: `locale()` in the SDK and the WebUI (no `'it-IT'` literal), `i18n.month_name/weekday_name`,
  `display.money` by language; SDK `plural` translates both forms.
- Context tags (`pl::`, `f::`, `abbr::`, `mood::`…) when one English word needs two Italian ones.
- Stays Italian on purpose: stored ids/values, parsers of the owner's words, tool names (`cibo_*`, `casa_*`,
  `scadenze_*`: renaming them goes with the tool merges, his decision).

### Acceptance (phase 3)
- `check_i18n.py`: every text has its Italian; all module suites green (Echo: only `langdetect` missing here).
- Angular build and `tsc` of the SDK and every plugin clean.
- `docs/LANGUAGES.md` rewritten for the English source.
