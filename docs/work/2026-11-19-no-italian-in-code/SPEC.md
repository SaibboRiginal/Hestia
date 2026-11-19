# No Italian in the code

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (Marko 2026-11-19, 5th time) | in progress |

## Goal

«What a person never sees: English. Everything else translatable, never fixed in one language.»
Zero Italian words in the code: identifiers, tool names, page ids and routes, query keys, setting keys, stored values
and states, use-case ids, comments, log lines, prompts, scripts in `tools/`, dossier folder names. Hestia is not in
production, so stored data compatibility is never a reason to keep a value.

## Scope

- Every module, the WebUI (backend + frontend), plugins, Shared, `tools/`.
- Words a parser looks for in what the owner writes → `locales/<lang>/words.json` (`hestia_common.i18n.words`).
- Words of an outside source in one language (an Italian bank mail, a real-estate site) → that source's profile, as data.
- Visible texts still fixed in Italian → English source in `tr` + Italian in the catalog.

## Acceptance

- `tools/governance/check_english.py` passes with an empty baseline.
- CI green on every wave (tests updated with the new names).

## Design

- Gate with a ratchet baseline per file (only goes down), in precheck and CI.
- Renames are done with exact-token maps over code, tests, docs (not dossier history, not CHANGELOG).
- Telegram commands: English ids; the command a person types comes from the owner's language.
