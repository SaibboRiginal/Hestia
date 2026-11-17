# SPEC — Sidebar con una regola sola, conversazioni, bolla, microfono, divisori

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Sistemare i feedback sulla WebUI», points 1–8, 11, 12 of the plan agreed there) |
| **Status** | Implemented (owner's real run pending) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, before this work)

- Sidebar (`layout/shell.component.ts`): «Crea con Hestia», «Cerca» and «Parla» on top as three different things; Chat
  inside «Generale»; the system modules' pages behind ONE bottom entry «Sistema» (a page that lists them), so Voce,
  Notifiche, Download were two clicks away and never marked as «where I am». Only sections fold; a module with
  sub-pages does not. No breadcrumb. Unread notifications only as a number on «Sistema».
- Conversations: rename/pin only in the «Cronologia» panel; nothing deletes one (Archive `DELETE /chat/history/{id}`
  exists but it is what history compaction uses, and it leaves title/tags/pin behind).
- Chat: the microphone shows only while the box is empty; «Detta» is a second button with a note icon.
- «Ascolta» under an answer: `VoiceService.toggle` has no catch, a failure shows nothing.
- «Scarica le voci» is a button of the Download page, a page with no sidebar entry.
- No sign of a new day or of another model answering, in any client; the model reads the history without times.

## 2. Goal

One rule for the sidebar, every page reachable and marked; conversations managed where they are listed; the two ways
to reach the assistant from any page in one place with one line each; one microphone; failures said; time and model
visible to the owner and time visible to the model.

## 3. Design

### 3.1 Sidebar (points 1, 2, 4)
- Fixed top: logo, **bell with the unread count** (→ Notifiche), collapse; then **Chat** and **Cerca**.
- Scroll area, sections that all fold the same way: Generale (Home, Scopri) · Fissati · Conversazioni · Dashboard ·
  Moduli · **Sistema** (Panoramica = the old Sistema page, the system modules' pages, Aggiornamenti, Macchine, Download).
- A module with sub-pages has a chevron that folds them (`webui.sidebar.collapsed`, key `m:<entry id>`); folded, its
  counter is the sum of its pages'.
- Where I am: the entry of the page on screen is marked (longest link that starts the address; a detail page marks
  its module's first page), its parent too (`within`), a folded section or module opens by itself while the page is
  inside it, the entry is scrolled into view, and above the page «Sezione › Modulo › Pagina» for pages of Fissati,
  Dashboard, Moduli, Sistema.
- Fixed bottom: Impostazioni, Esci, state. On phones the menu button carries the unread count.

### 3.2 Bell (point 3)
`NotificationsService.badge` (unread) on the bell in the sidebar and on the phone's menu button.

### 3.3 Conversations (point 5)
- «…» on each conversation of the sidebar: Rinomina (in place), Fissa in cima / Togli, Elimina (asks first). The menu
  is drawn in the viewport (`.hx-ctx`, global): the sidebar clips what overflows it.
- «Cronologia»: the same three under «…» (its edit panel gains «Elimina conversazione»); both lists follow each other
  (`ChatsService.changed`).
- Delete = Archive `DELETE /api/chat/sessions/{id}` (messages + title/tags/pin) through Oracle
  `DELETE /api/ui/chats/{id}`, which also drops the saved training turns. Deleting the one on screen starts a new one.
  `DELETE /chat/history/{id}` is unchanged (compaction).

### 3.4 Bubble (point 6)
`layout/quick-bubble.component.ts`, bottom right of every page: «Scrivi qui» (the side panel, Ctrl+J) and «Parla»
(continuous voice, Ctrl+Shift+Space), each with one line that says what it does. Both leave the sidebar. Hidden on
the Chat page (it has both) and while the side panel is open.

### 3.5 One microphone (point 8)
Always in the composer, next to «Invia» when there is text. Tap = dictation into the box (tap again to stop);
hold (350 ms) = voice message, release sends, slide left cancels; keyboard = dictation. The «Detta» button is gone.

### 3.6 «Ascolta» and «Prepara la voce adesso» (points 7, 11)
- `VoiceService.toggle` never fails silently: a spinner while the voice is prepared, and on failure a message with
  the cause the server gave + «Apri Voce». The CSP is not touched here (the setup thread adds `media-src`).
- The Voce page (Echo plugin, «Prova») gets «Prepara la voce adesso» with what it does; the Download page links to
  Voce instead of the button.

### 3.7 Dividers and time (point 12)
- WebUI chat: a wavy divider (`.hx-divider`, global) with the day when it changes (Oggi, Ieri, «mer 5 nov») and one
  with the model's name where another model starts answering.
- Telegram: one line above the answer when another model than last time answers (days are already Telegram's).
- The model that answered: Oracle `final.model` (last counted call of the conversation), saved with the answer
  (`chat_history.model`, additive column), returned by `/api/ui/chats/{id}/messages`.
- To the model: every message of the owner in the history starts with when it was written, `User [Thu 6 Nov 21:14]:`
  (owner's time zone, English like every hidden text). A message written again by compaction keeps its own time and
  model (`POST /chat/history` accepts `timestamp`, `model`).

## 4. Acceptance
- Voce opens from the sidebar in one click, is marked, and the page says «Sistema › Voce».
- A conversation can be renamed, pinned, deleted from the sidebar and from Cronologia; deleted = gone from Archive.
- No «Parla» / «Crea con Hestia» in the sidebar; the bubble opens both.
- The microphone stays visible while typing.
- «Ascolta» with the voice down shows the reason.
- Tests: Archive, Oracle, Telegram suites green; browser check with a mocked API.

## 5. Not in this work
- The `/setup` pages and the CSP (setup thread). The contextual «Crea con Hestia» buttons inside pages (Home, Agenda).
