# SPEC — Hermes: one live notification per thing, with a repeat/skip counter

| Version | Source | Status |
|---|---|---|
| 1.1 | user via external chat (project thread "Modulo Self care", 2026-10-17, point 2; split out by the channel session) | Approved 2026-10-17 («deve funzionare con Hermes e per tutti i client») — implemented |

## 1. Goal
Marko: «non voglio avere tipo 999 promemoria se non li risolve ogni giorno, mantiene magari 1 con quante volte sono
state saltate (idea: per tutti i moduli)». A module that nudges about the same thing again (routine to do, shirt to
wash, workout to log, a recurring alert) must never pile notifications up: on every client there is **at most one
live notification for that thing**, and it says **how many times it was skipped**. Generic, owned by Hermes;
Self care, Guardaroba and Coach (and any existing module) only add one key to their event.

## 2. Current state (checked 2026-10-17)
- One notification = one `outbound_events` row (channel `notification`), see dossier
  `2026-10-10-hermes-global-notifications`. `dedupe_key` blocks a new one while the old is active
  (`created/queued/delivered/seen/answered`), so a module either gets **nothing new** (deduped) or, with a fresh
  key, a **second** notification next to the old one. `closes: <dedupe_key>` closes the old one but keeps no count.
- Lifecycle state `superseded` already exists in Archive and is unused by notifications.
- Clients (Telegram, WebUI) handle `notification` / `update` / `retract` (`Hestia-Telegram/.../notifications.py`,
  `Hestia-WebUI/app/Controllers/NotificationsController.cs`, `frontend/.../notifications.service.ts`).

## 3. Scope
In: Hermes `replaces` key, repeat chain + counter, `superseded` fan-out, `resolves` on actions, inbox showing
only the live one; Telegram and WebUI rendering of the counter and removal of the replaced message; swagger, docs.
Out: *when/how often* to nudge (each module: e.g. Self care max 2/week, its planner job); the audio client (it
gets the same fields, nothing special needed); quiet hours (assistant presence, already in Hermes).

## 4. Acceptance criteria
1. Module sends `selfcare.reminder` with `replaces: "selfcare.reminder.r42"` three days in a row and the user never
   answers → on Telegram and WebUI there is **one** notification, the latest, with «Saltato 2 volte»; the older
   messages are gone from the Telegram chat (deleted; if older than 48 h the buttons become «↻ Sostituito») and
   from the WebUI list.
2. A button on an old (replaced) message, if still visible somewhere, answers «già sostituita» (409), nothing runs.
3. User presses **Fatto** (action with `resolves: true`) → the chain closes; the next reminder starts fresh
   (no counter shown). User presses **Salta** (no `resolves`) → that notification is handled, but the next one in
   the chain still counts it: «Saltato 3 volte».
4. Module closes it itself (`closes: <key>`, `decision: "done"`, e.g. routine logged from the WebUI page) → same as
   a resolving answer.
5. A chain idle for more than `hermes.repeat.reset_after_days` (default 30) starts again from zero.
6. A module that does not send `replaces` behaves exactly as today.

## 5. Design decisions

### 5.1 Event contract (module side)
- New payload key **`replaces: "<thread key>"`** (alias `_replaces`). The key names the *thing*
  (`selfcare.reminder.<routine_id>`, `wardrobe.laundry`, `coach.log.<plan_id>`), not the occurrence. It becomes the
  row's `dedupe_key`, so `closes: <same key>` keeps working. An event with `replaces` is **never deduped**: every
  send is a new occurrence of the chain.
- Actions may carry **`resolves: true`** (e.g. «Fatto»): answering with it ends the chain. Other actions
  («Salta», «Dopo») handle only that occurrence.
- `closes: <key>` with `decision` in `done`/`resolved` ends the chain too; other decisions just close the
  current occurrence (counted as skipped).
- The module writes its own text **without** counting skips; Hermes adds the counter (§5.3).

### 5.2 Chain (Hermes)
On an event with `replaces: K`, Hermes reads the latest row with `dedupe_key = K`:
- none, or its chain is `resolved`, or it is older than `hermes.repeat.reset_after_days` → new chain:
  `repeat = {count: 1, skipped: 0, since: now}`.
- otherwise → `repeat = {count: prev.count + 1, skipped: prev.skipped + 1, since: prev.since}`; if the previous
  row is still open (not answered/expired) it is moved to **`superseded`** (`superseded_by` = new id, compare-and-set
  so a concurrent answer wins) and every client gets `update {state: "superseded", superseded_by}`.
- The new occurrence is published as a normal notification (presence hold, audience, actions, retry: unchanged)
  with `payload.repeat`. No new table: the chain lives in the rows' payload.
- Answer with a `resolves` action / resolving `closes` → `payload.repeat.resolved = true` on that row.

### 5.3 What clients get
`notification` body gains `repeat: {count, skipped, since, text}` (only when `count > 1`); `text` is ready Italian,
short and readable aloud: «Saltato 1 volta» / «Saltato 3 volte · dal 12 ott». Clients show it as a small line/chip;
an audio client just reads it after the message. The inbox `view` exposes the same `repeat` and **hides
`superseded` rows** (only the live one is listed; history stays in Archive).

### 5.4 Clients
- **Telegram**: `update` with `state: superseded` → delete the old message (fallback over 48 h: buttons replaced by
  «↻ Sostituito»); new message rendered with the repeat line in italics under the text.
- **WebUI**: backend unchanged (it forwards to SignalR); frontend removes a superseded item from the list (an
  old toast simply expires), shows the repeat chip on cards and toasts, counts don't double.

### 5.5 Settings (Themis, `hermes_settings.py`)
| Key | Type / default | Effect |
|---|---|---|
| `hermes.repeat.reset_after_days` | int 30 (1–365) | A chain idle longer than this starts again from zero |

### 5.6 Module boundaries
Hermes: chain, counter, replace on every client. Module: decides when to nudge and what «done» means (`resolves`,
`closes`). Clients: rendering only. Archive: storage (existing table and states).

## 6. Phases
1. Hermes: `replaces` in `process_event`, chain/counter in `NotificationCenter.publish`, `superseded` broadcast,
   `resolves` in `answer`/`close`, inbox hides superseded, setting; unit tests (written, not run by Claude).
2. Telegram: superseded → delete/fallback; repeat line.
3. WebUI frontend: superseded removal, repeat chip (cards + toasts).
4. Docs: `hestia-hermes.md`, `hestia-telegram.md`, `hestia-webui.md`, swagger (`ClientNotifyRequest`, event keys),
   `docs/ARCHITECTURE.md` rule «recurring nudges use `replaces`»; tell the Self care / Guardaroba / Coach threads.
