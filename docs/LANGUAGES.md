# Languages — the standard for every module

Read this before you write any text, in Python, C#, the WebUI, a plugin, a host tool or an installer. Dossier with
the history: `docs/work/2026-11-14-english-backend/`. Owner's decision: `docs/MARKO-RULES.md` R9.

## The rule in one line

**All the code is English, everything stored is English, and every text a person reads or hears follows the
owner's language.** The model thinks in English; whatever reaches the owner (chat, notifications, buttons, voice,
installer, errors) is in his language. No exceptions «for compatibility»: nothing is in production yet.

Languages today: **English** (the source, in the code) and **Italian** (the catalogs). The code knows no language
by name: a language is a folder `Hestia-Shared/hestia_common/locales/<code>/`.
«Language» = `themis.personal.language` (options = every folder with a `language.json`, default `it`).

| Text | Where it lives | Language |
|---|---|---|
| Prompts, tool and field descriptions, `response_prompt`, module manuals, hidden context, assistant hints | in the code | English, never wrapped in `tr` |
| Ids, stored values and enums, keys, tool names, use cases, file names, query params, comments | in the code and in the data | English, never translated |
| Chat answer | written by the model | the language of the owner's last message |
| Notifications, recaps, messages she writes first, texts the model writes for a person | written by the model | «Language»: `{owner_language}` or `identity.LANGUAGES[i18n.language(settings.get)]` in the English prompt |
| Buttons, labels, cards, notices, error `detail`s, setting labels and help, tool titles | fixed texts | English in the code, the owner's language from `locales/<code>/messages.json` |
| What the owner types or says (yes/no, dates, moods, categories, commands, greetings) | parsers | every language at once, from `locales/<code>/words.json` |
| Host tools (`tools/*.py`), installers (`install.sh`, `install.ps1`, `up-all.*`) | fixed texts | English in the code, the system language from the catalogs |

## The files of a language (`Hestia-Shared/hestia_common/locales/<code>/`)

| File | What | Read by |
|---|---|---|
| `language.json` | `{"english": "Italian", "native": "Italiano"}`: the language exists | `identity.LANGUAGES` (code → English name, for prompts), `identity.NATIVE_NAMES` (the setting's options) |
| `messages.json` | English source text → translation (every fixed text) | `i18n.t` / `tr`, `i18n.localize`, WebUI shell and SDK, C# `Texts.Tr`, `tools/_texts.py` |
| `tools.json` | `{tool: {summary, params}}`: what a person reads about a tool | `i18n.tool_text`, WebUI, Telegram |
| `words.json` | `{list: [words or regex fragments]}`: what people write, per list | `i18n.words`, `word_regex`, `word_set`, `is_yes`, `weekday_of` |
| `voice.json` | sample sentences for the voices of that language | Echo |
| `installer.tsv` | `English<TAB>translation`, one line per installer text | `install.sh`, `install.ps1`, `up-all.sh`, `up-all.bat` |

English has no `messages.json` (the source is English) but has its own `words.json`, `tools.json` and
`language.json`.

## Fixed texts: how to write them

The English text in the code **is the key**. Wrap it, then add its translation to every `messages.json`.

**Python module**

```python
from hestia_common.i18n import t as tr
raise HTTPException(404, tr("Expense not found"))
note = tr("{0} new expenses", count)              # placeholders {0} or {name}, same in the translation
line = tr("Recheck {0}", tr(module_label(name)))  # a label passed as argument is translated too
hidden = tr("Self care: ", lang="en")             # a fixed text forced to one language
```

- The module follows «Language» once at startup: ModuleKit does it (`self.settings.follow_personal()`); a module
  without ModuleKit calls `SettingsClient("<name>").follow_personal()` itself (Iris, Atlas, Telegram…). Then `tr`
  answers in the owner's language.
- **Texts declared once at import or registration** (manifests, pages, widgets, capabilities, `llm_usecases`,
  agenda rules, setting definitions, area and module labels, catalog constants): write plain English, **never**
  `tr`. `tr` at import freezes the language of that moment. These are translated at the edge:
  `i18n.localize(payload)` translates every string that is a catalog key (except under `KEEP_KEYS`: id, key,
  value, status…); the WebUI HTTP interceptor and Telegram run it; Themis serves settings through
  `settings_client.translated(definition, lang)`.
- A stored value is shown through its label: `tr(f"mood::{label}")`, `tr(KINDS[kind])`. Never store the label.
- **Whole sentences, not glued nouns**: «Great day for running» and «Great day for a walk» are two keys; a noun
  dropped into one sentence breaks the grammar of other languages (gender, articles).
- Data seeded once for the owner (default categories, accounts) is written with `tr(label)` at seeding time: it is
  the owner's data from then on, he can rename it.
- Dates: `i18n.month_name(m)`, `i18n.weekday_name(wd)` (Monday = 0); money: `display.money(value)`
  («1.234,50 €» · «€1,234.50»).

**WebUI backend (C#)**: `Texts.Tr("Session expired")`, `Texts.Tr("{0} files", n)` (`Services/Texts.cs`, catalog
from Themis `/api/settings/i18n`, cached 5 minutes; unreachable → the English source).

**WebUI shell (Angular)**

```ts
import { tr, locale, TrPipe } from '../../core/i18n';   // add TrPipe to the component's imports
toast(tr('Saved'));  tr('{0} files', n);  d.toLocaleDateString(locale(), {...});
```
```html
<button>{{ 'Save' | tr }}</button>  <input [placeholder]="'Search…' | tr">  {{ '{0} proposes:' | tr: who }}
```

**Plugin (Lit, `Hestia-<Name>/ui/src`)**

```ts
import { tr, locale, plural } from '@hestia/webui-sdk';
html`<hxk-button>${tr('Add')}</hxk-button>`
plural(n, 'exercise', 'exercises')            // «3 esercizi» · «3 exercises»
new Intl.NumberFormat(locale(), ...)          // the owner's language code ('en' → 'en-GB'), never a literal locale
```

Plurals: two keys (`n === 1 ? tr('1 file') : tr('{0} files', n)`) or the SDK `plural`.
The WebUI loads the catalog before any bundle (`/api/webui/i18n.js`, from Themis `GET /api/settings/i18n`), so
constants at module level work too; `<html lang>` follows it. Saving «Language» reloads the page.

**Host tools** (`tools/*.py`, `tools/cloud_test/*`): `from _texts import tr, is_yes` (`tools/_texts.py`). The host
has no Themis: the language is `HESTIA_LANGUAGE`, else the system locale (`LC_ALL`, `LC_MESSAGES`, `LANG`), else
English.

**Installers**: one argument, English: `t "Installing {0}" "$name"` (bash), `(T 'Installing {0}' $name)`
(PowerShell, the file stays ASCII), `say` / `:say` in `up-all`. The translation comes from
`locales/<code>/installer.tsv`, found next to the script or downloaded from `HESTIA_RAW_URL`; any two-letter code
works (`--lang CODE`, `-Lang CODE`, else the system language); no file → English.

## What people write: words, never Italian in the code

A parser of the owner's words reads **every language at once** from `words.json`:

```python
from hestia_common.i18n import word_regex, word_set, is_yes, weekday_of
_DELETE = word_regex(r"\b(?:{0})\b", "oracle.delete_ask")   # alternation of the list in every language
if text.lower() in word_set("common.greeting"): ...
if is_yes(answer): ...                                       # 1, true, yes, sì, s, vero…
weekday_of("mer")                                            # → 2
```

A value the owner may type in his words is matched against the stored English value **and** its label in every
catalog (Psyche moods and causes, Oracle chat modes «Rapida» → `quick`, Kairos categories «bollo» → `car_tax`).
Literal braces in a fragment are written `{{ }}` (the list goes through `str.format`).

## Same English word, different translation: tags

When one English text needs two translations, prefix a context tag: `tr("pl::Transport")`, `tr("Transport")`.
Tags in use: `alt::` `f::` (feminine) `m::` (masculine) `pl::` `abbr::` `dev::` `v::` (verb) `run::` `mood::`
`cause::` `lang::`. `i18n.bare()` strips the tag, so English shows the plain word.

## What is not ours

External sites keep their own words: listing URLs and page markup Scout reads (`/annunci/`, `/immobile/`,
`id='caratteristiche'`), senders like `noreply@notifiche.immobiliare.it`. Test inputs keep the owner's own phrases
(«oggi sono stanco»), next to English ones: both must work.

## Check before pushing

```
python tools/governance/check_i18n.py                     # lists every text without its Italian (precheck and CI run it)
python tools/governance/check_i18n.py --todo todo.json    # writes {"Text": ""} for what is missing
python tools/governance/check_i18n.py --merge todo.json   # after filling it in: adds them to the Italian catalog
```

It scans modules, WebUI, plugins, `tools/*.py` and `tools/cloud_test/*.py`. Placeholders must match between
source and translation (`Hestia-Telegram/tests/test_language.py` checks it).

**The assistant's name** (`docs/work/2026-11-16-name-everywhere`): where a text speaks of the assistant as a person,
write `{assistant}` and, for gendered words, `{g:her-form|his-form}` (source «What {assistant} thinks on {g:her|his}
own», Italian «Cosa pensa {assistant} da {g:sola|solo}»), in the source and in the translation; `localize` fills them
too. `tr` / `t` fill them with the name and she/he the owner chose. Where «Hestia»
is the app (version, updates, files, installation, the whole system) write «Hestia».

## Don't

- Don't write a language name or «Sei Hestia…» in a prompt: use `{owner_language}` and the identity tokens.
- Don't write «Hestia» in a text that means the assistant as a person (`{assistant}`).
- Don't translate with the model at runtime, and don't keep a second catalog in a module: one catalog per language.
- Don't write any Italian in the code: not for a person, not as an id, a stored value, a key, a file name or a
  comment. Write English and add the translation; the owner's words go in `words.json`.
- Don't call `tr` at import or registration time, and don't wrap technical strings or hidden prompts in `tr`.
- Don't change a stored value or a key when a label changes: only the text is translated.
- Don't hardcode `'it-IT'` or «€» after the number: use `locale()` and `display.money`.

## A new language (only when the owner asks for it)

1. Create `locales/<code>/language.json` (`{"english": "German", "native": "Deutsch"}`): it appears in the
   «Language» options of the setup and the settings, the prompts call it by its English name. No code to change.
2. Add `messages.json`, `tools.json` and `words.json` with the same keys as the Italian ones (a text not translated
   yet stays English), `voice.json` for the voices, `installer.tsv` for the installers.
3. Telegram's bottom keyboard and commands follow automatically; check `Hestia-Telegram/tests/test_language.py`.
