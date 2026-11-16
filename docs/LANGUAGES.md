# Languages — the standard for every module

Read this before you write any text, in Python, in the WebUI or in a plugin. Dossier with the history:
`docs/work/2026-11-14-backend-inglese/`. Owner's decision: `docs/REGOLE-DI-MARKO.md` R9.

## The rule in one line

**What the model reads is English. What a person reads is a fixed text in the owner's language.**

Languages today: **Italian** (the source) and **English**. «Lingua» = `themis.personal.language` (`it` | `en`).

| Text | Where it lives | Language |
|---|---|---|
| Prompts, tool and field descriptions, `response_prompt`, module manuals, hidden context | in the code | English, always |
| Chat answer | written by the model | the language of the owner's last message |
| Notifications, recaps, messages she writes first, texts the model writes for a person | written by the model | «Lingua»: put `{owner_language}` or `identity.LANGUAGES[i18n.language(settings.get)]` in the English prompt |
| Buttons, labels, cards, notices, error `detail`s, setting labels and help, tool titles | fixed texts | Italian in the code, translated through the catalog |
| SQL, headers, ids, CSS, SVG paths, log lines | in the code | never translated |

## Fixed texts: how to write them

The Italian text in the code **is the key**. Wrap it, then add its English text to the one catalog
`Hestia-Shared/hestia_common/locales/en/messages.json` (Italian needs no entry).

**Python module**

```python
from hestia_common.i18n import t as tr
raise HTTPException(404, tr("Spesa non trovata"))
note = tr("{0} spese nuove", count)          # placeholders {0} or {name}, same in the translation
```

- The module calls `settings.follow_personal()` once (ModuleKit does it for you): `tr` then knows «Lingua».
- A module-level constant is translated where it is used: `LABEL = "Salva"` … `tr(LABEL)`.
- Settings: write label, help, group and option labels in Italian in `setting(...)`; Themis translates them when it
  serves them. Never call `tr` there.
- Tools: the model description is English in the tool; the people text (summary, field help) is in
  `locales/it/tools.json` and `locales/en/tools.json`.

**WebUI shell (Angular)**

```ts
import { tr, TrPipe } from '../../core/i18n';   // add TrPipe to the component's imports
toast(tr('Salvato'));  tr('{0} file', n);
```
```html
<button>{{ 'Salva' | tr }}</button>  <input [placeholder]="'Cerca…' | tr">
```

**Plugin (Lit, `Hestia-<Name>/ui/src`)**

```ts
import { tr } from '@hestia/webui-sdk';
html`<hxk-button>${tr('Aggiungi')}</hxk-button>`
```

The WebUI loads the catalog before any bundle (`/api/webui/i18n.js`), so constants at module level work too.
Saving «Lingua» reloads the page.

## Check before pushing

```
python tools/governance/check_i18n.py                     # lists every text without English (precheck and CI run it)
python tools/governance/check_i18n.py --todo todo.json    # writes {"Testo": ""} for what is missing
python tools/governance/check_i18n.py --merge todo.json   # after filling it in: adds them to the English catalog
```

Placeholders must match between source and translation (`Hestia-Telegram/tests/test_language.py` checks it).

**The assistant's name** (`docs/work/2026-11-16-nome-ovunque`): where a text speaks of the assistant as a person,
write `{assistant}` and, for gendered words, `{g:lei|lui}` («Chiedi a {assistant}», «Cosa pensa da {g:sola|solo}»),
in the source and in the translation. `tr` / `t` fill them with the name and she/he the owner chose. Where «Hestia»
is the app (version, updates, files, installation, the whole system) write «Hestia».

## Don't

- Don't write a language name or «Sei Hestia…» in a prompt: use `{owner_language}` and the identity tokens.
- Don't write «Hestia» in a text that means the assistant as a person (`{assistant}`).
- Don't translate with the model at runtime, and don't keep a second catalog in a module: one catalog for all.
- Don't put an English sentence in the code for a person (it would never be Italian), and don't wrap technical
  strings in `tr`.
- Don't change a stored value or a key when a label changes: only the text is translated.
- Keyword detectors on what the owner writes (mood, intents) read his words: keep them as they are.

## A new language (only when the owner asks for it)

1. Add the code to `identity.LANGUAGES` (`Hestia-Shared/hestia_common/identity.py`) and to the options of
   `themis.personal.language` (`settings_client.py`, `PERSONAL`), and to `LANGUAGES` in
   `Hestia-WebUI/frontend/src/app/services/identity.service.ts`.
2. Create `locales/<code>/messages.json` and `locales/<code>/tools.json` with the same keys as the English ones
   (texts not translated yet fall back to English, then Italian).
3. Telegram's bottom keyboard and commands follow automatically; check `Hestia-Telegram/tests/test_language.py`.
