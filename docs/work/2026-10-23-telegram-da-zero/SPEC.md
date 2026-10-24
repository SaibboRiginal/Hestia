# Telegram from scratch: look, emoji, layout, commands

| | |
|---|---|
| **Version** | 3.1 |
| **Source** | user via Project thread (Marko 2026-10-23: «dobbiamo aprire uno specifico per rivedere tutto telegram, le emoji e come mostra le cose è veramente brutto... dobbiamo rivederlo da 0») |
| **Status** | Approved 2026-10-24 (Marko: «tu imposta per averle tutte, e implementa come me l'hai detto tutto») — implementing |

## Goal
**Every function of the assistant is usable from Telegram — all of them** (Marko 2026-10-24: «anche da telegram
voglio disponibili tutte le funzioni dell'assistente! e intendo tutte!»). Telegram looks like one product, calm and readable: a small, fixed visual grammar shared by every message
(chat answers, command results, notifications, questions, wizards, errors), almost no emoji, one message per
interaction edited in place, and a short command menu in plain Italian. Today Telegram reaches 80 of 165 tools; after
this work it reaches 165 of 165, plus what the WebUI does without a tool (section 5.9).

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
| A11 | **Whole areas missing from the buttons menu**: `build_commands_keyboard` shows only the 8 keys of `GROUP_ORDER`; modules declare `allenamento`, `selfcare`, `guardaroba`, `spese`, `chat`, `sviluppo` → those ~38 commands are reachable only by typing their English name. | `registry.py` | 6 areas |
| A12 | **Fragile buttons and flows**: pending flows, confirmations and picker tokens live in memory dicts (lost at every restart → «Richiesta scaduta»); `callback_data` cut at 64 bytes (`ntf:<id>:<action>`[:64]) can silently break ids; missing input asked by argument name («Inserisci ora il valore per *subscription id*»); `setMyCommands` rebuilt at every registry change (429 debounce). | core, executor, notifications | — |
| A13 | **Half of the functions are not on Telegram**: 85 of 165 tools are `clients=["ui"]` or `telegram_visible=False` (Chronos 22 of 30, Hercules 15 of 26, Hygieia 10 of 18, Oracle memory/documents 9 of 9, Themis 4 of 4, Plutus 6 of 11, Forge review 8 of 19, Wardrobe 5 of 12…). Photos/files cannot be given to an action. A reply to a message is not passed as context. | modules, executor | 85 tools |
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
6. **Few, clear entry points.** Four doors (bottom keyboard), a short `/` menu, area cards; everything else in plain chat.

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

**Home, areas, actions**: see section 5.

**Wizard** (new event): one message, «Passo 2 di 4», the question, quick buttons, typed answer accepted; the
message is edited at each step and ends as the summary with `Crea` / `Annulla`.

**Error**: `🔴 <b>Non sono riuscita a creare l'evento</b>` / `Il calendario non risponde, riprova tra poco.`

## 5. Navigation and menus (v2.0 — Marko: «i menu erano la parte seccante… usando a pieno l'intera potenza di customizzazione… facilmente usabile e navigabile»)

### 5.0 Idea
Chat stays the main way: you write, the assistant answers. Menus exist for what is quicker with a tap: see today,
open an area, run its common actions without remembering any command. Every Telegram surface has one job:

| Surface (Telegram feature) | Job | Always there? |
|---|---|---|
| **Bottom keyboard** (`ReplyKeyboardMarkup`, `is_persistent`, `resize_keyboard`, placeholder «Scrivimi o tocca un pulsante») | the 4 doors, one thumb away | yes, under the input field |
| **`/` menu** (`setMyCommands`, scope = owner's private chat, `it`) | the same doors + quick shortcuts, for who types | yes |
| **Navigation card** (one message with inline keyboard, edited in place) | Home → Area → Action, with breadcrumb and Indietro | one live at a time |
| **Action flow** (same card + `ForceReply` with placeholder for typed values) | fill what an action needs, confirm, show result | while running |
| **Buttons on results/notifications** (inline, URL, copy-text, deep link) | the next sensible step after a result | on that message |
| **Bot profile** (`setMyName/Description/ShortDescription`) | what the bot is, in Italian, set at boot | — |

### 5.1 Bottom keyboard
```
┌──────────────┬──────────────┐
│     Oggi     │     Aree     │
├──────────────┼──────────────┤
│  Notifiche   │ Impostazioni │
└──────────────┴──────────────┘
```
- Taps send exactly these words; Telegram catches them before the chat (they never reach the model). Typed «oggi»
  inside a sentence is chat as usual: only an exact, whole-message match is a button.
- Sent once with the Home card and kept (`is_persistent`); a restart re-sends it on the next Home.
- No counts in labels (Telegram cannot update them without a new message); counts live in the Home card.

### 5.2 `/` menu — 8 entries
| Command | Same as |
|---|---|
| `/oggi` | bottom «Oggi» — day card |
| `/aree` | bottom «Aree» — area list |
| `/notifiche` | bottom «Notifiche» — what to see or answer |
| `/impostazioni` | bottom «Impostazioni» |
| `/nuova` | new conversation (today `/clear`, with confirm) |
| `/voce` | voice answers on/off (today `/live` + `/chat`) |
| `/stato` | assistant status, do-not-disturb buttons |
| `/aiuto` | how to use the bot + every typed shortcut (expandable) |

`/start` is Telegram's own button: it opens Home and re-sends the bottom keyboard. Old names (`/clear`, `/live`,
`/chat`, `/settings`, `/help`, every module command) still work when typed, never listed. The menu is static: set
at boot only (no more rebuild at each registry change, no 429).

### 5.3 Cards (one live navigation message)
```
HOME (/start)                        OGGI                                  AREE
<b>Ciao Marko</b>                    📅 <b>Oggi</b> — giovedì 23 ottobre    <b>Aree</b>
<i>Giovedì 23 ottobre</i>            • 09:00 Dentista                      [ 📅 Giornata ] [ 🏋️ Allenamento ]
• Prossimo: 18:00 palestra           • 18:00 Palestra — Push A             [ ✨ Cura di sé ] [ 👕 Guardaroba ]
• 2 notifiche da vedere              • Da fare: crema solare, bolletta     [ 💶 Spese ]    [ 🏠 Case ]
[ Vedi 2 notifiche ]                 <i>Meteo: 18°, pioggia dalle 17</i>     [ ✉️ Posta ]    [ 📎 Documenti ]
[ Inizia allenamento ]               [ Aggiorna ] [ Domani › ]              [ ⚙️ Sistema ]
                                     [ ‹ Home ]                             [ ‹ Home ]
```
- **Home buttons are contextual**, not a copy of the bottom keyboard: up to 3 «next things» chosen from what is due
  (notifications waiting, today's workout, an event about to start), each one tap to act.
- **Breadcrumb** in the title when deeper than one level: `Aree › Allenamento › Registra peso`.
- Last row always `‹ Indietro` (and `Home` from level 3). Same place on every card.
- **One live card**: opening a new card (from keyboard, `/` or button) strips the buttons of the previous navigation
  card and deletes it when it is younger than 48 h, so the chat does not fill with old menus. Results stay.
- **Fresh on tap**: every tap re-reads the data; «Aggiorna» exists only where data changes during the day.
- Callback answered first (spinner gone in < 1 s), then the edit.

### 5.4 Area card = the area's mini dashboard
```
🏋️ <b>Allenamento</b>
<i>Settimana 2/3 · prossimo: Push A oggi</i>
• Record: panca 65 kg (lunedì)
• Peso: 78,4 kg (−0,6 in 30 giorni)
[ Inizia allenamento ] [ Registra peso ]
[ Registra attività ]  [ Schede ]
[ Tutte le azioni › ]
[ ‹ Aree ]
```
- **Header** = the area's summary tool rendered as a card (section 6), e.g. `fitness_summary`, `finance_summary`.
- **Primary actions**: up to 6, 2 per row, in the module's order. The rest under «Tutte le azioni ›» (paged list, 8 per
  page, «Altre ›»).
- Areas, order and primary actions:

| Area | Header | Primary actions | Then «Tutte le azioni ›», by section |
|---|---|---|---|
| 📅 Giornata | agenda of today | Agenda · Meteo · Recap · Nuovo evento · Nuovo promemoria · Piano della settimana | Calendario (eventi: crea, modifica, sposta, elimina) · Agenda dell'assistente (aggiungi, sposta, salta, modelli, ripristina) · Meteo · Recap |
| 🏋️ Allenamento | summary | Inizia allenamento · Allenamento di oggi · Registra peso · Registra attività · Schede · Salta oggi | Oggi (check-in, adatta, rimanda) · Schede (modifica, annulla) · Attività · Storico e statistiche · Obiettivi |
| ✨ Cura di sé | summary | Oggi · Segna fatto · Routine · Prodotti · Lista spesa | Routine (crea, modifica) · Prodotti · Diario · Statistiche e ciclo |
| 👕 Guardaroba | summary | Cosa mi metto · Indossato · Cerca · Aggiungi capo · Outfit | Capi (dettaglio, modifica, elimina) · Outfit · Valigia · Statistiche |
| 💶 Spese | month summary | Registra spesa · Cerca movimenti · Budget · Abbonamenti | Movimenti (modifica, elimina) · Categorie · Importa estratto conto · Statistiche |
| 🏠 Case | stats | Case disponibili · Cerca · Controlla email | Statistiche · Avanzate |
| ✉️ Posta | — | Cerca messaggi · Invia messaggio · Iscrizioni | Conversazioni · Avanzate |
| 🧠 Memoria | what I know (count) | Ricorda questo · Cosa ricordi di… · Documenti salvati · Cerca sul web | Note e preferenze · Documenti (pin, elimina) · Web (cerca, leggi pagina) |
| 🛠 Sviluppo | open tasks | Sviluppa Hestia · Lavori in corso · Da approvare | Lavoro (dettaglio, differenze, dossier, nota, approva, rifiuta, annulla) · Riparazioni · Dataset e training · Impostazioni sviluppo |
| ⚙️ Sistema | status | Stato · Non disturbare · Accesso WebUI · Collega calendario · Impostazioni | Salute e log · Account collegati · Contesto della chat · Tutte le impostazioni · Avanzate (riconcilia, verifica) |

  Area appears only when it has an action; an unknown area key goes to «Altro», **never dropped** (fixes A11).
- **Sections** inside «Tutte le azioni» come from the module (`telegram_section`); technical tools go in a last
  section «Avanzate», still one tap away. Nothing is hidden.

### 5.5 Action flow (no argument names, no `key=value`)
Inputs come from the tool's own JSON schema, so modules need nothing new for the basics:
- `enum` / boolean → buttons (`• ` on the current one); integer with small `min..max` → quick buttons + typing;
  dates → Oggi / Domani / Dopodomani + typing; existing `arg_picker` sources → buttons with real items.
- free text → the card shows the question in words (schema `title`/`description`, first sentence) and a `ForceReply`
  with **placeholder example** («Es. 12,50 pranzo con Luca»); the typed reply fills it.
- optional values → «Salta»; required ones first; «Passo 2 di 3» in the title.
- **Confirm** when the tool writes or deletes (method ≠ GET, or MCP `destructiveHint`): summary card
  `[ Conferma ] [ Annulla ]`, destructive spelled out («Elimina»). Read-only tools run at once.
- Result replaces the card (one message). Result buttons = the next step the module declares
  (`display.actions`, section 6), e.g. after «Allenamento di oggi» → `[ Inizia ] [ Salta oggi ]`.
- While a flow waits for text, the placeholder says what it waits for; a tap on the keyboard, a `/` command or
  «Annulla» ends it and says so («Ho lasciato perdere: Registra spesa»). Writing a sentence that does not fit (e.g. a
  question) → «Vuoi uscire da Registra spesa?» `[ Sì ] [ No, continuo ]`.
- Typing works too: `/finance_add 12,50 pranzo` or «ho speso 12,50 a pranzo» in chat (the model) — same result.

### 5.6 Other Telegram features used
- **Deep links** `t.me/<bot>?start=<area>` or `=<action>`: a notification can carry «Apri Spese ›»; `/aiuto` lists them.
- **URL buttons** to the WebUI page of the same thing (when `WEBUI_PUBLIC_URL` is set): «Apri nella WebUI».
- **Copy button** (`CopyTextButton`) for the WebUI token and codes, instead of text to select.
- **Link preview** off by default on cards (`link_preview_options`), on for a single house/article result.
- **Expandable blockquote** for long detail (reasoning, list of all shortcuts, logs in Sistema).
- **Typing action** while a command runs (no «⌛ Titolo…» message).

### 5.7 What modules declare (MCP `_meta.hestia`, generic, no Telegram logic in modules)
| Key | Meaning | Default |
|---|---|---|
| `telegram_group` | area key of 5.4 (`giornata`, `allenamento`, `selfcare`, `guardaroba`, `spese`, `case`, `posta`, `memoria`, `sviluppo`, `sistema`) | from service, else `altro` |
| `telegram_section` | section inside «Tutte le azioni» (`avanzate` = last) | none |
| `telegram_order` | position inside the area | declaration order |
| `telegram_primary` | shown on the area card | false |
| `telegram_summary` | this tool is the area card's header | false |
| `telegram_label` | short button label (≤ 24 chars) | `title` |
| `telegram_visible` | **removed**: every tool is on Telegram; `clients` keeps only `external` (outside AIs) as a restriction | — |

Area names and emoji are Telegram's (one table in `telegram_bot/areas.py`), not the modules'.
Every tool of every module is shown: `telegram_visible=False` and `clients=["ui"]` stop meaning «not on Telegram»
(85 tools come in). Maintenance tools (`*_reconcile`, `gateway_auth_poll`, `metis_*`, …) go to the «Avanzate»
section of their area. Internal ones that a person cannot meaningfully run (`feedback_submit`, used by the client
itself) are the only exception, declared with `telegram_section="interno"` and listed in the reachability test. Module names leave titles («Stato Forge» → «Stato sviluppo», «Agenda di Hestia» →
«Agenda dell'assistente»). Titles lose their emoji; `tools/governance/check_icons.py` fails on emoji in `MCPTool`
titles; Telegram also strips a leading one as safety net.

### 5.8 Robustness (the «sempre un sacco di problemi» part)
- **One callback router**: `cb:<kind>:<short id>`; a test asserts that every button the client can draw has a handler.
- **Short ids, persisted**: tool names, notification ids and flow tokens map to 6-char ids stored in the session
  store (file, TTL 7 days) → never cut at 64 bytes, still valid after a restart.
- **Flows persisted** (pending input, confirmations, pickers) in the same store with TTL; after a restart a
  half-filled «Registra spesa» continues.
- **Old buttons** (unknown id, old format) never error: «Questo menu è vecchio» + the current card in its place.
- **Registry changes** update the area cards lazily (next tap), never the `/` menu.
- **Button labels** ≤ 24 chars, cut on a word with «…»; tested on the live catalog.
- **Reachability test**: walks Home → every area → every action for the catalog of all modules (from their
  `MCPTool` declarations) and fails if a visible tool cannot be reached in ≤ 3 taps.

### 5.9 «Tutte» means also what the WebUI does without a tool
- **Parity list**: the governance check of brainstorm idea 22 (plugin actions ↔ MCP tools) gives the list of WebUI
  actions without a tool. Each gap gets a tool in its own module (module boundaries: the module owns it, Telegram
  only shows it). Known today: export/import `.hestia`, backup now/restore, notification subscriptions, Hermes inbox
  answer/history, presence states, plugin quick actions, Athena proposals/thoughts, Argus remediation history.
  The list is filled at T2 start and tracked in PROGRESS.md; a test fails when a new plugin action has no tool.
- **Files in and out**: an action whose schema asks for a file/image (`format: binary`, `contentMediaType`) asks
  «Mandami la foto» and takes the next photo/document (wardrobe photo, bank statement, receipt, document to save).
  Results with images (a garment, an outfit, a house) come as photo + caption, several as an album
  (`sendMediaGroup`); exports come as a document file.
- **Visual pages (Mini App)**: what is a picture rather than an action — charts, the week grid of the agenda,
  photo galleries — opens the same WebUI page **inside Telegram** as a Mini App (`web_app` button: «Apri grafico»,
  plus the chat menu button «Apri Hestia»). Needs the public HTTPS address (`CLOUDFLARE_TUNNEL_HOSTNAME`) and a
  WebUI login with Telegram's signed `initData` (HMAC with the bot token, only the `ALLOWED_USER_ID`). Without a
  public address the buttons are simply not drawn and every action still works with buttons.
- **Chat**: anything can still be asked in words; the assistant already uses every tool in its scope.

### 5.10 Reply to a message = context (brainstorm idea 24, accepted)
- Replying to any message (an answer, a notification, a result card, your own message) or to a **quote** of part of
  it (Telegram `quote`) sends the quoted text to the assistant with the new message: Oracle `/api/chat` gets
  `quoted: {text, from: assistant|user|notification, at, ref}` and shows it to the model as context (not as an
  instruction). Small Oracle contract change (swagger + Oracle doc), same field usable by the WebUI.
- Reply to a notification: the notification id goes with it, so «spostalo a domani» acts on that reminder.
- WebUI shows the quoted context closed under your message (WebUI part done here too, it is small).

### 5.11 The menu is configuration, not code (v3.1 — Marko: «rendi facile rielaborare i menu… configurazione dinamica piuttosto che hard coded»)
Everything you see in the menus comes from **one data structure** built at run time from three layers, later wins:

| Layer | Who writes it | What |
|---|---|---|
| 1. Defaults | Telegram, `telegram_bot/menu/defaults.py` — **data only**, no logic | bottom keyboard, `/` menu, area list (key, label, emoji, order, which services/groups belong) |
| 2. Module hints | each module, in its tool declaration (5.7) | area, section, order, primary, header, short label |
| 3. Your layout | you, Themis setting `telegram.menu.layout` (type `object`, scope user, live) | any override of the above |

Layout shape (every part optional):
```json
{
  "keyboard": [["oggi", "aree"], ["notifiche", "impostazioni"]],
  "commands": ["oggi", "aree", "notifiche", "impostazioni", "nuova", "voce", "stato", "aiuto"],
  "areas": {
    "spese": {"label": "Soldi", "emoji": "💶", "order": 15,
              "header": "finance_summary", "primary": ["finance_add", "finance_budget"]},
    "viaggi": {"label": "Viaggi", "emoji": "🧳", "order": 90}
  },
  "tools": {
    "wardrobe_packing": {"area": "viaggi", "label": "Valigia", "primary": true},
    "fitness_log_measurement": {"section": "Corpo", "order": 1}
  }
}
```
How you change it:
- **From Telegram**: Impostazioni › Menu → choose an area → Azioni principali (add/remove, Su/Giù), Rinomina,
  Emoji, Sposta un'azione in un'altra area, Nuova area, Ripristina predefinito. Each change is saved at once and
  the card you are looking at is redrawn.
- **From the WebUI**: the same setting in Impostazioni (Themis panel), as an editable JSON object.
- **From the assistant**: «metti Registra spesa in alto nelle Spese» → Themis proposal, you confirm (usual rule).

Rules that make it safe:
- A tool that the layout does not mention **still appears** (area from its hints or its service, else «Altro»):
  no layout can lose a function. Unknown tool/area names are ignored and logged (`event=menu_layout_unknown`).
- Areas, keyboard and `/` menu are redrawn at the next tap after a change; the `/` menu and keyboard are re-sent
  only when they actually changed.
- The reachability test runs on defaults **and** on sample layouts.

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
| T2 | Navigation (section 5) as configuration (5.11: defaults + module hints + `telegram.menu.layout`, menu editor in Telegram): bottom keyboard, `/` menu, Home, area cards, action flow from the tool schema, confirmations, deep links, bot profile, robustness 5.8; module meta (`telegram_*`), titles without emoji, technical tools in «Avanzate»; governance + reachability tests (A2, A3, A8, A11, A12) |
| T3 | Results without the model: generic renderer, `hestia_common.display`, `display` in the 6 modules, Scout card, signal path removed (A4) |
| T4 | Chat: new client instructions, notices inside the answer, feedback + Ascolta on the answer, slim settings (A7, A9) |
| T5 | Notifications, assistant questions, wizards, chat queue texts on the new grammar (A10) |
| T5b | All functions (5.9): every tool reachable (85 in), `telegram_section` in modules, files in/out, parity list → missing tools module by module, reply-as-context (5.10, Oracle + WebUI) (A13) |
| T7 | Mini App: WebUI page inside Telegram with `initData` login, menu button, «Apri grafico» buttons — needs the public address |
| T6 | Docs (`hestia-telegram.md`, `docs/ARCHITECTURE.md` Telegram rules, swagger if a contract changes, module docs, `.env.example` untouched), root CHANGELOG, bench screenshots of a real bot conversation if possible |

Each phase is a PR merged when CI is green. Old callback data keep working for messages already in the chat.

## 9. Choices (all decided 2026-10-24: keyboard yes, names and areas as proposed, Mini App yes)
1. ~~Markers~~ — decided v1.1: hybrid (3.1).
2. Bottom keyboard (5.1) always visible — yes (recommended) or only the `/` menu?
3. Command names of 5.2 (`/oggi`, `/aree`, `/nuova`, `/voce`…) — ok or other names?
4. Areas of 5.4 (now 10, with Memoria and Sviluppo) and their primary actions — anything to add, merge or rename?
5. Mini App (5.9, T7) — ok to open WebUI pages inside Telegram for charts, agenda grid and photos?

## Acceptance criteria
- No emoji in any Telegram text or button except the 4 tone dots, the area emoji (area buttons + result titles) and 👍/👎 (test scans the client strings).
- `/` menu has the 8 entries; every visible module command reachable from the bottom keyboard in ≤ 3 taps (test walks
  the whole tree for every tool of the live catalog; no tool dropped because of an unknown area).
- Buttons keep working after a restart of Telegram (persisted ids/flows); an old menu answers with a fresh one.
- An action never asks for an argument by its technical name; choices come as buttons from the tool schema.
- 165 of 165 tools reachable (exception list = `interno` only); every WebUI action has a tool or is on the parity list.
- A reply to a message reaches the assistant with the quoted text.
- Running a command produces exactly one message, same layout each time, with Oracle stopped.
- No module name, id, exception text or `key=value` in user texts (test on the string table).
- Settings panel has 6 entries; removed keys gone from Themis declarations and docs.
- Existing tests green, new tests for `ui.py`, renderer, menu and every screen of section 4.
