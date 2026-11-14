# SPEC — One personal language for what she writes on her own

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Migliorare i prompt per ogni situazione», Marko 2026-11-13 and 2026-11-14) |
| **Status** | Implemented; PR open |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
Follows `docs/work/2026-11-12-prompt-ogni-situazione` (every hidden text English, answer in the language of the
owner's last message).

## 1. Today (verified on main d728bd1)

- Module texts for the owner (notification, alert, recap, weekly plan, expense summary, setup hello, update notes)
  said «in Italian» inside their prompt: a fixed language, unrelated to the owner.
- The opener said «in the language of what you know about them (Italian if unsure)»: a guess.
- `/api/format` defaulted to `locale = "it"`.
- Telegram had its own `telegram.chat.locale` (it/en/de/fr/es), read by nobody.

## 2. Marko's decisions

1. «TUTTO IN INGLESE IN BACKGROUND»: every text the model reads is English; only the final answer is in the
   owner's language (2026-11-12, 2026-11-14).
2. In chat he switches freely between Italian and English: the chat answer follows the language of his last
   message (unchanged, `language_rule`).
3. Notifications must not change language now and then: one general language setting (2026-11-13).
4. Translating the fixed texts of the clients (buttons, setting names) is a separate choice still open with him;
   this SPEC does not touch them.

## 3. Design

- New personal setting `themis.personal.language` («Lingua», group «Tu e l'assistente», order 5): `it` (default)
  · `en` · `de` · `fr` · `es`. Themis owns it like the other personal settings; modules read it with
  `follow_personal()`.
- `hestia_common.identity`: `read()` returns `language` (unknown value → `it`), `language_name()` gives its English
  name, and `render()` fills the new token `{owner_language}` («Italian», «English»…).
- Oracle: `module_voice_instruction` (every `/api/llm/generate {voice:true}`) says «Write in {owner_language} …,
  whatever the language of the data, unless the request names another language». The opener uses the same
  language. `prompt_config.owner_language()` gives the code. `/api/format` with no `locale` uses it; a caller can
  still pass one.
- Modules no longer name a language: Hermes (item notification, listings batch), Argus (alert, back online),
  Athena (recap), Chronos (weekly plan), Plutus (month summary), Hephaestus (setup hello; update notes now go
  through `voice:true` with an English prompt).
- Telegram drops `telegram.chat.locale` (the personal language covers it; no duplicate setting).
- WebUI: the setup step «Tu e io» gets «La tua lingua»; `IdentityService` reads and saves it. Impostazioni →
  Personali shows it like every personal setting.

## 4. Acceptance

1. Language `en` → `module_voice_instruction` says «Write in English»; `/api/format` without locale asks for `en`;
   with `locale=de` it asks for `de`.
2. Unknown stored value → Italian.
3. No module prompt says «in Italian».
4. `telegram.chat.locale` is no longer declared.
5. Chat: the language rule still follows the owner's last message.
