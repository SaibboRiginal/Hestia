# Telegram from scratch: look, emoji, layout, commands

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via Project thread (Marko 2026-10-23: «dobbiamo aprire uno specifico per rivedere tutto telegram, le emoji e come mostra le cose è veramente brutto... dobbiamo rivederlo da 0») |
| **Status** | Draft — waiting for Marko's approval (no code before it) |

## Goal
Telegram looks like one product, calm and readable: a small, fixed visual grammar shared by every message
(chat answers, command results, notifications, questions, wizards, errors), almost no emoji, one message per
interaction edited in place, and a short command menu in plain Italian. Same features as today; only how they are
shown and reached changes.

## 1. Audit of today's client (main @ af732d7)

| # | Problem | Where | Numbers |
|---|---|---|---|
| A1 | **Emoji on everything**: every title, button, step, error, settings label, menu group. Same meaning drawn with different emoji (errors: ⚠️ ❌ ⛔; waiting: ⏳ ⌛; done: ✅ ✓). | `Hestia-Telegram/app/**` | ~210 emoji in strings |
| A2 | **Emoji inside tool titles of the modules**, shown in the `/` menu, help, pending lines: 🏋️ ×8, 👕 ×7, ✨ ×8, 💶 ×5 repeated on every title of the same area. | `Hestia-*/app/main.py` `MCPTool(title=…)` | ~80 visible tools |
| A3 | **Command menu of ~100 entries** (Telegram's hard limit is 100), sorted alphabetically, English tool names (`/fitness_next_workout`, `/gateway_auth_poll`, `/metis_loRA_train`), technical ones (riconcilia, remediation, LoRA, stato Forge), module names in titles («Stato Forge», «Riconcilia Scout»). | `registry.setup_commands` | 80 module + 22 local |
| A4 | **Command results written by the LLM**: almost every command is `oracle_natural`, so the JSON goes to Oracle `/api/format` to be turned into text: slow (one model call per command), different every time, and prompts that ask for emoji («Usa emoji appropriate 🏠 📍 💶 📐»). Offline → raw fallback. | `formatters.render_direct_command_output`, `control_service` | — |
| A5 | **Too many messages per interaction**: «⌛ Titolo…» then edited into «**Titolo**», then the result as a new message; feedback as a separate «⚡ Valuta questa risposta» message; wizard = one message per step; notices in a separate message. | executor, chat_service, calendar_wizard | 2–6 msgs per action |
| A6 | **Technical text to the user**: raw exceptions in `<code>`, «Connessione all'Oracle fallita», «ALLOWED_USER_ID», `key=value`, «Impostazione sessione aggiornata: tone=warm», notification ids. | chat_service, executor | ~25 strings |
| A7 | **Settings panel of 13 knobs**, half of them presentation switches (`split_mode`, `notice_style`, 4 × `notice_<family>`, `stream_answer`) — against «no feature switches». Plus Themis keys `telegram.signals.style*` for a legacy path. | chat_settings, telegram_settings | 13 + 5 |
| A8 | **Two homes**: `/start` («🏛️ Hestia pronta») and `/help` («📘 Guida comandi», a flat list of 100 lines); two groups both «⚙️»; a group key that contains an emoji (`"🌐 webui"`). | executor, registry | — |
| A9 | **Chat style asked to the model**: «personale e caldo… prima persona femminile», Markdown then converted to HTML by regex, no rule on emoji, 6–8 lines max even when a list is asked. | `DEFAULT_CLIENT_INSTRUCTIONS` | — |
| A10 | **Notifications**: all buttons on one row (cramped, cut at 40 chars), status lines mixing ✓ and ✅. | notifications.py | — |

## 2. Design principles
1. **One message per interaction.** The bot answers by editing one message: status → result. Buttons live on that
   message. A second message only when the text is longer than Telegram allows, or when it is a different thing (a
   voice note, a file).
2. **Text first, symbols second.** Hierarchy comes from Telegram's own formatting: **bold** title, normal body,
   *italic* for secondary info and outcomes, `<blockquote expandable>` for long or optional detail, `code` only for
   things to copy. No emoji as decoration.
3. **One marker per message at most**, from a fixed set (section 3.1), on the title line. Never on detail lines; on buttons only for areas.
4. **Plain Italian, no internals.** No module names, no ids, no exceptions, no `key=value`. Sentence case, no «!»,
   no «...» on finished text.
5. **Deterministic output.** A command shows data with the same layout every time, without calling the model.
   The model writes only chat answers.
6. **Few, clear entry points.** A short `/` menu; everything else in a «Comandi» browser and in plain chat.

## 3. Visual grammar

### 3.1 Markers — hybrid (Marko 2026-10-23: «farei una cosa ibrida»)
Telegram cannot colour text or draw icons. Three kinds of marker, each with its own place, and **at most one marker
per message, only on its title line**:

| Kind | Where | Set |
|---|---|---|
| **Tone dot** | notifications, outcomes, errors (what needs attention) | 🔴 danger · 🟠 warning · 🟢 success · 🔵 info — the same `tone` the WebUI colours icons with |
| **Area emoji** | «Comandi» area buttons and the title of a command result | one fixed emoji per area (5.2), declared once by Telegram, never repeated in lines |
| **Nothing** | chat answers, lists, detail lines, settings, wizards, every other button | typographic symbols only: `•` items, `·` separator, `›` «go to», `—` in titles |

- A notification of an area shows the dot, not the area emoji (urgency wins); its `emoji` field is no longer shown.
- Data that carries `tone` (Hermes level, presence states, recap pieces) maps to the dot.
- 👍/👎 stay as the vote buttons.

### 3.2 Building blocks (one helper, `telegram_bot/ui.py`)
`card(title, lines=[], detail=None, tone=None)` · `item(title, meta=[], url=None)` · `outcome(text, tone)` ·
`error(what)` · `buttons(rows)` · `paged(items, page)`. Every message in the client is built with these; no
hand-written HTML in handlers. Lists: max 8 items, then «Altri 12 ›» button (page edited in place).

### 3.3 Buttons
Verb or noun, no emoji, max 2 per row (3 for short ones such as Oggi/Domani/Dopodomani), destructive action last
and spelled out («Elimina»). Standard labels: `Conferma` · `Annulla` · `Indietro` · `Chiudi` · `Altro ›`.
Selected option in a picker: `• Caldo` (bullet), not ✓.

### 3.4 Error wording
`🔴 <b>Non sono riuscita a {azione}</b>` + one line of what to do («Riprova tra poco»). The exception goes only to the
log (`event=…`). Unavailable assistant keeps today's «Non disponibile» wording.

## 4. Screens — before → after

**Chat answer** (with reasoning compact and a memory notice):
```
BEFORE                                    AFTER
⏳ Sto lavorando…                          (same message, live)
▸ 💭 Ragionamento · 3 passi                ▸ Ragionamento · 3 passi          ← expandable
Certo Marko! 😊 Ecco **domani**:           Domani hai due impegni:
- 9:00 dentista                            • 9:00 dentista
- 18:00 palestra 🏋️                        • 18:00 palestra
                                           <i>Ricordato: il dentista è il dott. Rossi</i>
[ 🔊 Ascolta ]                             [ Ascolta ]  [ 👍 ]  [ 👎 ]        ← one row, same message
⚡ Valuta questa risposta  (new message)
[👍][👎]
```
👍/👎 stay as the only emoji buttons: the universal «vote» glyph, no text alternative as short.
They appear with the same rate as today (`telegram.feedback.prompt_rate`) and vanish when pressed.

**Command result** (`Allenamento di oggi`, no LLM):
```
BEFORE                                    AFTER
⌛ 🏋️ Allenamento di oggi...               🏋️ <b>Allenamento di oggi</b> — Push A
🏋️ Allenamento di oggi                     <i>Martedì · 5 esercizi · ~55 min</i>
(new msg, written by the model, emoji)    • Panca piana  4×8 · 62,5 kg
                                          • Lento avanti  3×10 · 30 kg
                                          • …
                                          [ Inizia ]  [ Salta oggi ]
```

**Notification**:
```
BEFORE                                    AFTER
<b>Promemoria</b>                          🟠 <b>Crema solare</b>
Ricordati la crema solare                  Oggi UV alto alle 13.
↻ Saltato 2 volte                          <i>Saltato 2 volte</i>
[✅ Fatto][Più tardi][Salta]               [ Fatto ]  [ Più tardi ]
                                           [ Salta ]
after the answer: «✅ Fatto · da WebUI»     after: buttons removed, last line <i>Fatto · da WebUI</i>
```

**Home `/start`** (one message, edited while navigating):
```
<b>Ciao Marko</b>
<i>Giovedì 23 ottobre</i>
• Prossimo: 18:00 palestra
• 2 notifiche da vedere
[ Oggi ]  [ Comandi ]
[ Notifiche ]  [ Impostazioni ]
```
«Comandi» opens areas → commands of an area → runs it, all in the same message with `Indietro`.

**Wizard** (new event): one message, «Passo 2 di 4», the question, quick buttons, typed answer accepted; the
message is edited at each step and ends as the summary with `Crea` / `Annulla`.

**Error**: `🔴 <b>Non sono riuscita a creare l'evento</b>` / `Il calendario non risponde, riprova tra poco.`

## 5. Commands

### 5.1 The `/` menu (setMyCommands) — 8 entries
| Command | What |
|---|---|
| `/start` | Home (above) |
| `/oggi` | Today: agenda + what is due (existing `agenda_today` / recap tools) |
| `/comandi` | Browse every command by area |
| `/notifiche` | Notifications to see / answer |
| `/nuova` | New conversation (today `/clear`, with confirm) |
| `/voce` | Voice answers on/off (today `/live` + `/chat`) |
| `/stato` | Assistant status |
| `/impostazioni` | Settings panel |

Old names (`/clear`, `/live`, `/chat`, `/settings`, `/help`, every module command) still work when typed; they are
just not listed. `/help` = `/comandi`.

### 5.2 Areas in «Comandi»
Fixed order, Italian names, one emoji each (only on the area button and on result titles): 📅 Giornata (agenda,
meteo, recap) · 🏋️ Allenamento · ✨ Cura di sé · 👕 Guardaroba · 💶 Spese · 🏠 Case · ✉️ Posta · 📎 Documenti ·
⚙️ Sistema. An area appears only if it has a visible command. A module declares its
area with the existing `telegram_group` (values renamed to these keys); unknown → «Altro».

### 5.3 What is shown at all
- A tool is shown in Telegram only if it has `clients` with `telegram` **and** is meant for a person. Maintenance and
  internal tools become `telegram_visible=False`: `*_reconcile`, `gateway_auth_poll`, `gateway_auth_complete`,
  `hephaestus_*` except status, `metis_*`, `forge_settings`, `forge_set_claude_schedule`. They remain reachable from
  WebUI and from chat («ripara il servizio…»).
- Titles in modules lose the emoji (`"🏋️ Allenamento di oggi"` → `"Allenamento di oggi"`); Telegram also strips a
  leading emoji from any title as a safety net. `tools/governance/check_icons.py` extended: no emoji in `MCPTool`
  titles.
- Module names leave titles: «Stato Forge» → «Stato sviluppo», «Riconcilia Scout» → hidden, «Agenda di Hestia» →
  «Agenda dell'assistente».

## 6. Command results without the model
- Default response mode becomes `display`: Telegram renders the JSON itself with a **generic renderer**: a dict →
  title + «Etichetta: valore» lines (keys humanised, empty values omitted, no «n/d»); a list of dicts → items with
  the first of `title|name|label` as title and up to 2 short fields as meta; URLs → linked title; booleans/dates
  formatted in Italian.
- A module can make it nicer by returning an optional **`display` block** next to its data (shared helper
  `hestia_common.display`: `title`, `subtitle`, `items[{title, meta, url, tone}]`, `actions[{label, command}]`).
  WebUI ignores it; the MCP text for models is unchanged. First modules to add it: Hercules, Chronos (agenda),
  Hygieia, Plutus, Wardrobe, Scout — the ones with visible commands.
- `oracle_natural` stays only for tools that explicitly ask it (none by default). The Scout proactive «ho trovato
  una casa» text becomes a `display` card too (no model, no emoji prompt).
- The legacy notification-compile «signal cards» path and its 5 Themis keys (`telegram.signals.*`) are removed.

## 7. Chat answers and settings
- **Client instructions** (Themis `telegram.chat.client_instructions`, new default): answer in Telegram HTML
  subset directly (`<b> <i> <a> <code> <blockquote>`), lists with `•`, **no emoji**, no headings, short unless a list
  or detail is asked. Tone and gender stay with Oracle's personal settings (not in the client contract). The
  Markdown→HTML regex stays only as a safety net.
- **Notices** under the answer, inside the same message, one italic line each, no emoji: «Ricordato: …»,
  «Fatto: …», «Non riuscito: …» (🔴 only for this one), «Notifica attivata: …».
- **Settings panel** (`/impostazioni`, one message edited in place) keeps only what changes the experience:
  Tono · Modalità · Ragionamento (nascosto / compatto / dettagliato / in diretta) · Messaggi di sistema (sotto la
  risposta / solo importanti / nascosti) · Voce · Istruzioni personali. Removed: `split_mode` (always split only when
  too long), `stream_answer` (always on), `notice_style`, the 4 per-family notice switches.

## 8. Phases
| Phase | Content |
|---|---|
| T1 | `ui.py` grammar (cards, markers, buttons, errors, paging) + tests; rewrite every local string (A1, A5, A6) |
| T2 | Commands: 8-entry menu, Home, «Comandi» browser by area, aliases; module titles without emoji, hidden technical tools, area keys; governance check (A2, A3, A8) |
| T3 | Results without the model: generic renderer, `hestia_common.display`, `display` in the 6 modules, Scout card, signal path removed (A4) |
| T4 | Chat: new client instructions, notices inside the answer, feedback + Ascolta on the answer, slim settings (A7, A9) |
| T5 | Notifications, assistant questions, wizards, chat queue texts on the new grammar (A10) |
| T6 | Docs (`hestia-telegram.md`, `docs/ARCHITECTURE.md` Telegram rules, swagger if a contract changes, module docs, `.env.example` untouched), root CHANGELOG, bench screenshots of a real bot conversation if possible |

Each phase is a PR merged when CI is green. Old callback data keep working for messages already in the chat.

## 9. Open choices (Marko)
1. ~~Markers~~ — decided v1.1: hybrid (3.1).
2. Command names in the menu as in 5.1 (`/oggi`, `/nuova`, `/voce`…) — ok or other names?
3. Areas list of 5.2 — anything to add, merge or rename?

## Acceptance criteria
- No emoji in any Telegram text or button except the 4 tone dots, the area emoji (area buttons + result titles) and 👍/👎 (test scans the client strings).
- `/` menu has the 8 entries; every visible module command reachable from «Comandi» in ≤ 3 taps.
- Running a command produces exactly one message, same layout each time, with Oracle stopped.
- No module name, id, exception text or `key=value` in user texts (test on the string table).
- Settings panel has 6 entries; removed keys gone from Themis declarations and docs.
- Existing tests green, new tests for `ui.py`, renderer, menu and every screen of section 4.
