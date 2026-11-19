# SPEC — Questions in notifications, like in the chat

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (Marko, 2026-10-30: «2) sì. 4) verifica. ok») |
| **Status** | Implemented |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code)

- In a chat the assistant asks with the tool `ask_user` (`Hestia-Oracle/app/core/services/user_questions.py`):
  confirm, single choice, multiple choice, free text, `allow_other`. Oracle streams a `question` frame; WebUI draws
  `hx-question-card`, Telegram inline buttons (`assistant_questions.py`). The answer goes to
  `POST /api/chat/question-answer` and comes back as `resume.message`, the next chat turn. Module confirmations
  (Themis proposal from the chat) use the same frame with `actions`.
- Outside a chat a module reaches the owner only through a Hermes notification: fixed buttons (`_actions`) or a
  secret form (`_secret`). No multiple choice, no free answer.
- A **routine** (Chronos `routines.py`) runs an assistant turn with origin `routine:<key>`. If the model calls
  `ask_user` there, the `question` frame is dropped: the question text goes out as a plain notification and the
  answer has nowhere to go. A Themis confirmation asked inside a routine turn is lost the same way.
- Live voice (WebUI): the question text is read aloud and the spoken answer goes as a normal message. The options of
  a choice are not read. The answer does not close the question in Oracle: it stays open in Archive until
  `oracle.ask.timeout`, so after a reload the card comes back although it was answered. Same when the owner types an
  answer in the chat box instead of the card (WebUI) or writes a message instead of tapping (Telegram).

## 2. Goal

1. A notification can carry a **question** exactly like the chat card: confirm, single choice, multiple choice, free
   text, «Altro…». Same look in the WebUI inbox and on Telegram; first answer wins on every client.
2. Routines use it: a question the assistant asks while running a routine reaches the owner as such a notification,
   and the answer continues the routine.
3. A question answered by voice or by just writing is closed: it never comes back after a reload; live voice also
   reads the options.

## 3. Scope and design

### 3.1 Hermes — `_question` in an event (R1: Hermes delivers and claims, the module decides)
- Event payload `_question: {kind, options, allow_other, service, method?, path, body?}`. `kind` =
  `confirm | single_choice | multi_choice | free_text`; `options` = labels or `{value, label}` (2–8; confirm without
  options = Sì/No). Malformed = ignored.
- Stored as `notification.question`; clients see only `{kind, options, allow_other}` (`question` in the client body
  and in the inbox view). A question notification counts as **pending** («Da decidere», reminders, never retracted
  while open, not held by presence).
- `POST /api/notifications/{id}/reply {client, answer}` (plugin door `POST /api/ui/inbox/{id}/reply`): claim with
  compare-and-set like an action (409 `already_handled`), route `{...body, answer, answers, client,
  notification_id}` to the module (`answers` = list, one per line for multiple choice), then `update answered` to
  every client with the answer shown (labels, not values). Module error → claim released (502).

### 3.2 Clients
- **WebUI** (Hermes plugin *Notifiche*): the card shows the question like the chat card: buttons for single choice,
  toggles + «Invia» for multiple, a field for free text / «Altro…». Shell toast: a question counts as pending
  («Rispondi»).
- **Telegram**: the same keyboard as the chat question (`assistant_questions.py` reused): single choice answers at
  once, multiple toggles then «Invia». Free text is never taken from whatever the owner writes next (a notification
  arrives unasked): «Rispondi…» / «Altro…» button starts the text answer, or a reply to the notification message.

### 3.3 Shared and Chronos
- `hestia_common.reminders.reminder_event(question=…)` adds `_question` (same shape) for any module.
- Chronos routines: the `question` frames of the routine turn become notifications with `_question` routed to
  `POST /api/routines/{key}/answer {question_id, answer, client}`. Chronos passes the answer to Oracle
  (`/api/chat/question-answer`); a module confirmation runs its action there; an `ask_user` answer gives
  `resume.message`, run in the background as the next turn of the same routine session, delivered like a run.

### 3.4 Oracle — an answer by voice or by writing closes the question
- A new owner turn (origin `utente`) in a session closes that session's open `ask_user` questions (resolved, removed
  from Archive): the message itself is the answer, the question is in the history. Clients' cards go away; a late
  tap gets «Questa domanda non è più aperta».
- WebUI live voice: when the answer is a choice question, after the text it says the options («Puoi dire: A, B o C»).

### Out of scope
- New producers in other modules (they can now pass `question=`); the mood diary SPEC may use it.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: answer the assistant's questions from wherever he is, also when no chat is open.
2. Owner module (R1): Hermes delivers/claims, the asking module decides; Oracle only asks.
3. Configuration: none new (existing `oracle.ask.timeout`, `hermes.attesa.richiamo_ore`).
4. Push: Hermes pushes to clients; the answer is pushed back to the module.
5. Who confirms: the owner answers; nothing is done without the answer.
6. WebUI icons, no emoji; Telegram buttons without emoji.
7. Stop/undo: first answer wins, a late one is told «Già gestita»; the routine can be paused as before.
8. Docs: hestia-hermes, hestia-telegram, hestia-chronos, hestia-oracle, hestia-shared, swagger, ARCHITECTURE (messaging).

## 5. Acceptance criteria
- An event with `_question` single/multi/free text shows the question on WebUI and Telegram; the answer reaches the
  module once; the other client shows «… · da Telegram/WebUI».
- A routine whose turn calls `ask_user` sends a question notification; the answer continues the routine and its
  result arrives as a notification.
- After answering a chat question by voice or by typing, a reload does not show the card again.
- Live voice reads the options of a choice question.
- Unit tests for Hermes, Telegram, Chronos, Oracle, shared; precheck 0 failed; CI green.
