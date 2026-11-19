# SPEC — The chosen name everywhere, and her first message in the conversation

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Hestia viva», Marko 2026-11-13 «e ti sembra corretto??», 2026-11-16 «vai fai continua») |
| **Status** | Implemented |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
Follows `docs/work/2026-11-12-identity-and-proactivity` (name, she/he and owner chosen once at setup) and
`docs/work/2026-11-14-english-backend` (fixed texts through `hestia_common.i18n`).

## 1. Today (main 0a19768)

- Prompts already use the chosen name; the fixed texts people read did not: «Chiedi a Hestia», «Crea con Hestia»,
  «Agenda di Hestia», «Ciao, sono Hestia» in the voice try, Telegram «parlare con Hestia», module help and
  setting labels. Renaming her changed nothing of these.
- Transcripts the model reads (history, compaction) marked her turns «Hestia:».
- The voice recognition did not know her name, so a new name could be written wrong.
- The message she writes first («parla con te») lived only in Hermes: his answer had its context through the
  awareness line, and only on the same day; the chat did not show it.

## 2. Goal and scope

1. Every fixed text where «Hestia» is the assistant as a person says the chosen name and gender: Python
   (`i18n.t`), settings (`settings_client.translated`, Italian too), WebUI shell (`tr`), plugins (SDK `tr`) and
   plugin manifests (page labels, help, descriptions: `plugins.service.ts` `namedCatalog`).
2. Where «Hestia» is the app (version, updates, files, installation, «per tutta Hestia», the login brand, page
   titles, «Apri Hestia») it stays.
3. Voice: the «Ascolta» sample says her name (Portuguese article by gender, scripts other than Latin keep their
   spelling only for the default name); the recognition hint starts with her name and the owner's.
4. Oracle transcripts mark her turns with her name.
5. Her first message is saved in the conversation where he next writes, as her message with the time she wrote
   it, before his: once, within 3 days, never twice.

## 3. Design

- `hestia_common.identity.named(text, ident)` fills only `{assistant}` and `{g:lei|lui}`; every other brace stays
  for `str.format`. `hestia_common.i18n.identity_now()` reads it through the reader `follow_personal()` registered;
  `t()` applies it to the translation and to the source.
- Themis registers `themis.personal` as its i18n reader (the old lambda returned the language for any key) and
  `/api/settings/i18n` returns `assistant` and `gender` too (only her name, never the owner's: the endpoint is
  public through the WebUI). WebUI and SDK `tr` fill the tokens from the catalog; changing name or she/he reloads
  the page (not during the setup).
- Catalog keys (`locales/en/messages.json`) are the Italian sources with `{assistant}`.
- `core/services/opener_history.py` (Oracle), called at an owner's chat turn that saves history: newest Hermes
  notification of kind `athena.talk` within 3 days; skipped when any conversation has a message after it (he
  already answered or chatted since), when the conversation list cannot be read, or when the text is already in
  this conversation; saved through Archive `/chat/history` with `timestamp` = when she wrote it. Failures never
  block the turn (`[🔄]` log; the awareness line still says what she wrote today).

## 4. Acceptance criteria

- Name «Leo», he: «Chiedi a Leo», «Pianificato da Leo», «Agenda di Leo» (Italian and English), setting labels in
  Italian say Leo, the voice try says «Ciao, sono Leo», the hint starts «Leo, …».
- She writes first on Monday, he answers on Tuesday from Telegram: the conversation has her message (Monday's
  time) then his, and the model reads «Leo: …» before his line; a second message of his does not add it again.

## 5. New-feature checklist

- No new setting, env var, endpoint or loop. One field pair added to an existing response (swagger).
- Hub is the only door (Hermes and Archive through Hub). Logs `event=…`, fallbacks `[🔄]`.
- Hidden text English; texts people read in the owner's language.
