# Languages — the standard for every module

Read this before you write any text, in Python, in the WebUI or in a plugin. Dossier with the history:
`docs/work/2026-11-14-backend-inglese/`. Owner's decision: `docs/MARKO-RULES.md` R9.

## The rule in one line

**All the code is English. Italian lives only in the catalog. Every module follows «Lingua».**

Languages today: **English** (the source, in the code) and **Italian** (the catalog).
«Lingua» = `themis.personal.language` (`it` | `en`, default `it`).

| Text | Where it lives | Language |
|---|---|---|
| Prompts, tool and field descriptions, `response_prompt`, module manuals, hidden context, assistant hints | in the code | English, never wrapped in `tr` |
| Chat answer | written by the model | the language of the owner's last message |
| Notifications, recaps, messages she writes first, texts the model writes for a person | written by the model | «Lingua»: put `{owner_language}` or `identity.LANGUAGES[i18n.language(settings.get)]` in the English prompt |
| Buttons, labels, cards, notices, error `detail`s, setting labels and help, tool titles | fixed texts | English in the code, Italian from `locales/it/messages.json` |
| SQL, headers, ids, stored values, CSS, SVG paths, log lines | in the code | never translated |

The one catalog: `Hestia-Shared/hestia_common/locales/it/messages.json` (English source → Italian).
English needs no catalog: the source is already English. Tool texts for people: `locales/<lang>/tools.json`.

## Fixed texts: how to write them

The English text in the code **is the key**. Wrap it, then add its Italian text to the catalog.

**Python module**

```python
from hestia_common.i18n import t as tr
raise HTTPException(404, tr("Expense not found"))
note = tr("{0} new expenses", count)              # placeholders {0} or {name}, same in the translation
line = tr("Recheck {0}", tr(module_label(name)))  # a label passed as argument is translated too
```

- The module follows «Lingua» once at startup: ModuleKit does it (`self.settings.follow_personal()`); a module
  without ModuleKit calls `SettingsClient("<name>").follow_personal()` itself (Iris, Atlas, Telegram…). Then `tr`
  answers in the owner's language.
- **Texts declared once at import or registration** (manifests, pages, widgets, capabilities, `llm_usecases`,
  agenda rules, setting definitions, area and module labels, catalog constants): write plain English, **never**
  `tr`. `tr` at import freezes the language of that moment. These are translated at the edge:
  `i18n.localize(payload)` translates every string that is a catalog key (except under `KEEP_KEYS`: id, key,
  value, status…); the WebUI HTTP interceptor and Telegram run it; Themis serves settings through
  `settings_client.translated(definition, lang)`.
- A module-level constant shown at runtime is translated where it is used: `LABEL = "Save"` … `tr(LABEL)`.
- Data seeded once for the owner (default categories, accounts) is written with `tr(label)` at seeding time: it is
  the owner's data from then on, he can rename it.
- Dates: `i18n.month_name(m)`, `i18n.weekday_name(wd)` (Monday = 0); money: `display.money(value)`
  («1.234,50 €» · «€1,234.50»).

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
new Intl.NumberFormat(locale(), ...)          // 'it-IT' | 'en-GB', never a literal locale
```

Plurals: two keys (`n === 1 ? tr('1 file') : tr('{0} files', n)`) or the SDK `plural`.
The WebUI loads the catalog before any bundle (`/api/webui/i18n.js`, from Themis `GET /api/settings/i18n`), so
constants at module level work too. Saving «Lingua» reloads the page.

## Same English word, different Italian: tags

When one English text needs two Italian texts, prefix a context tag: `tr("pl::Transport")` → «Trasporti»,
`tr("Transport")` → «Trasporto». Tags in use: `alt::` `f::` (feminine) `m::` (masculine) `pl::` `abbr::` `dev::`
`v::` (verb) `run::` `mood::` `lang::`. `i18n.bare()` strips the tag, so English shows the plain word.

## Italian that stays in the code (on purpose)

- **Stored values and ids**: route/page ids, query keys, states (`running`, `done`), track ids
  (`life`/`system`/`talk`), setting keys, Plutus category ids, mood values (`giù`), use-case ids. Changing them
  would break the owner's data; only their labels are translated.
- **Parsers of the owner's words**: keyword detectors, regexes on bank or PayPal mails, Italian date words in
  Telegram inputs. They read what people write; keep both languages there.
- **Tool names** like `food_*`, `home_*`, `deadlines_*`: renaming them is a separate decision of the owner.

## Check before pushing

```
python tools/governance/check_i18n.py                     # lists every text without Italian (precheck and CI run it)
python tools/governance/check_i18n.py --todo todo.json    # writes {"Text": ""} for what is missing
python tools/governance/check_i18n.py --merge todo.json   # after filling it in: adds them to the Italian catalog
```

Placeholders must match between source and translation (`Hestia-Telegram/tests/test_language.py` checks it, and
that every `tr` literal of modules, WebUI and plugins has its Italian).

**The assistant's name** (`docs/work/2026-11-16-nome-ovunque`): where a text speaks of the assistant as a person,
write `{assistant}` and, for gendered words, `{g:her-form|his-form}` (source «What {assistant} thinks on {g:her|his}
own», Italian «Cosa pensa {assistant} da {g:sola|solo}»), in the source and in the translation; `localize` fills them
too. `tr` / `t` fill them with the name and she/he the owner chose. Where «Hestia»
is the app (version, updates, files, installation, the whole system) write «Hestia».

## Don't

- Don't write a language name or «Sei Hestia…» in a prompt: use `{owner_language}` and the identity tokens.
- Don't write «Hestia» in a text that means the assistant as a person (`{assistant}`).
- Don't translate with the model at runtime, and don't keep a second catalog in a module: one catalog for all.
- Don't write Italian in the code for a person: it would never be English. Write English and add the Italian.
- Don't call `tr` at import or registration time, and don't wrap technical strings or hidden prompts in `tr`.
- Don't change a stored value or a key when a label changes: only the text is translated.
- Don't hardcode `'it-IT'` or «€» after the number: use `locale()` and `display.money`.

## A new language (only when the owner asks for it)

1. Add the code to `identity.LANGUAGES` (`Hestia-Shared/hestia_common/identity.py`) and to the options of
   `themis.personal.language` (`settings_client.py`, `PERSONAL`), and to `LANGUAGES` in
   `Hestia-WebUI/frontend/src/app/services/identity.service.ts`; add its `locale()` in both `i18n.ts`.
2. Create `locales/<code>/messages.json` and `locales/<code>/tools.json` with the same keys as the Italian ones
   (texts not translated yet stay in English).
3. Telegram's bottom keyboard and commands follow automatically; check `Hestia-Telegram/tests/test_language.py`.
