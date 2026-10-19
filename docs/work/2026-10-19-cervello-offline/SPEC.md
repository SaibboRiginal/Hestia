# Brain offline — Hestia keeps working when Oracle is down

| | |
|---|---|
| **Version** | 2.0 |
| **Source** | user via external chat (Marko, brainstorm 2026-10-19 §0 item 2: «Cervello offline — Argus → Hermes diretto con testo fisso; banner WebUI e avviso Telegram; i messaggi della chat vanno in coda e hanno risposta quando torna»; v2.0: «deve andare in congiunzione con lo stato che avevamo già adesso, non andiamo a complicarci troppo») |
| **Status** | Approved 2026-10-19 (v2.0 = Marko's simplification on top of the approved v1.0) — implementing |

## Goal
Oracle is the only brain. When it is down the rest of Hestia keeps working and says so: the user is told once,
the clients show it, nothing written in the chat is lost, and every queued message is answered when the brain
returns. Built **on the assistant presence that already exists** (Chronos: signals → states → effects), not as a
parallel state.

## Facts checked in the code (2026-10-19)
- Argus already sends its alerts **through Hermes** (`alert_worker` → `/route/hermes/api/events/ingest`); Oracle only
  *narrates* the text and there is a plain-text fallback. Each narration waits up to 60 s on a dead Oracle.
- Docs contradict the code: `hestia-argus.md` *Alert Flow* says "Oracle dispatches via Hermes" and "TODO stub";
  `docs/ARCHITECTURE.md` known gaps says "alerts still go via Hermes with plain text" (true); `readme.md` roadmap says
  "alert directly on Telegram" (against *Hermes is the only outbound messenger*).
- Argus already feeds presence (`health.degraded_services` → overlay «Stanco»). Chronos already reacts to a relaxing
  effect (`notify.level` → asks Hermes to release held notifications). The WebUI badge and Telegram `/stato` already
  show every overlay with label, emoji, help and «Cosa cambia».
- Telegram and WebUI chat: Oracle failure → error text, the message is lost.

## Scope

### 1. Argus — the signal and the notice (diagnosis)
- Monitor cycle (already running, no new loop): Oracle's health check failing for at least `argus.brain.grace`
  seconds (new Themis setting, default 60, so a normal restart/deploy says nothing) → presence signal
  `brain.offline = true` (meta `since`, refreshed every cycle with a TTL, so a dead Argus does not leave it stuck);
  Oracle healthy again → signal cleared.
- Same moment: one Hermes event (`service.health`, existing subscription path) with fixed `_message` and
  `replaces: "system.brain"` (one live notice):
  «🧠 <b>Cervello offline</b>: Oracle non risponde. Comandi, notifiche e agenda funzionano; i messaggi in chat restano
  in coda e avranno risposta appena torna.» Back: `closes: "system.brain"` + «🧠 Di nuovo online dopo 14 min.»
  Oracle's generic `service.health` alert is not sent on top of it.
- While the signal is set Argus does not ask Oracle to narrate anything (fixed texts at once, no 60 s waits).

### 2. Chronos — a presence overlay (the existing state)
- New built-in overlay `brain_offline`: «Cervello offline» 🧠, priority above the others,
  `when brain.offline == true`, help «Oracle non risponde: i messaggi restano in coda e avranno risposta appena torna;
  i lavori che usano il cervello aspettano.», effects `work.light: defer`, `work.heavy: defer` (proactive work waits,
  through the effects consumers already read) and new ranked effect **`chat.reply`** (`live < queued`) = `queued`,
  `notice` «il cervello è offline, ti rispondo appena torna». Editable like the other states (`chronos.presence.states`).
- When `chat.reply` relaxes back to `live` (same place as the `notify.level` release), Chronos asks every Hub service
  that declares capability `chat_queue_drain` to answer its queue: `POST /route/<svc>/<drain path>`. No client
  hardcoded (discovered from the Hub registry like Hermes discovers clients).

### 3. Chat queue — Archive stores, each client answers its own
- Archive: table `chat_queue` + `/api/chat-queue` (create, list by client/state, claim with compare-and-set
  `queued → answering`, done/failed). Fields: `client, session_id, target, client_ref, text, created_at, state,
  attempts, answered_at`.
- A client queues a text message when its call to Oracle fails before any answer arrives (connection refused, Hub
  502/503/504, Oracle not registered, timeout before the first frame), and replies at once «🧠 Il cervello è offline:
  messaggio in coda, ti rispondo appena torna.» An error inside an answer (Oracle up, model error) is shown as today.
  Text only; a file while offline gets «rimandamelo appena torno». Archive also down → today's error.
- Drain (on the Chronos call above and at the client's own startup): oldest first, one at a time, replayed to Oracle
  `/api/chat` with the original session and a note in `client_instructions` («scritto alle 10:42 mentre eri offline»).
  No expiry. Telegram answers as a reply to the original message; WebUI backend replays without a browser open,
  Oracle saves the history, an open chat sees it live.

### 4. What the user sees
- **WebUI:** the presence badge shows «🧠 Cervello offline» (existing popover explains it). The chat page shows a strip
  from the effect `chat.notice` while `chat.reply = queued`, and a queued message has a clock «In coda» until answered.
  No separate banner component.
- **Telegram:** the Hermes notice (closed/replaced when back), the fixed reply per message, `/stato` shows the overlay.

### 5. Docs
`hestia-argus.md` (Alert Flow rewritten to the real flow, brain signal, setting), `hestia-chronos.md` (overlay, effect,
drain call), `hestia-archive.md` (queue), `hestia-telegram.md`, `hestia-webui.md`, `hestia-shared.md` if
`presence_client` changes, swagger (Archive, Telegram/WebUI drain), `docs/ARCHITECTURE.md` (known gap removed),
`readme.md` roadmap line, root CHANGELOG.

## Out of scope
- Oracle code (no change). A future Oracle `/health` saying "no model answers" (thread "Oracle a blocchi") can set the
  same signal later.
- A new Argus/Hermes API or a parallel "brain state" outside presence.

## Acceptance criteria
1. Oracle stopped > 60 s → presence overlay «Cervello offline», one notice on every client; restarted within 60 s →
   nothing.
2. Messages written in Telegram/WebUI while offline → fixed "in coda" reply; once Oracle is back each one is answered,
   in order, in the right chat, never twice.
3. Back → overlay gone, notice closed, «di nuovo online».
4. While offline Argus notifications go out at once with fixed text.
5. Docs consistent (no "TODO stub", no "direct Telegram").
6. Tests: Argus signal/grace/notice, Chronos overlay + drain call on relax, Archive queue CAS, Telegram enqueue/drain.
   Cloud bench: stop Oracle, chat in WebUI, screenshots (badge, strip, queued bubble), start Oracle, screenshot answers.

## Design decisions
- One state: presence. Argus = diagnosis (signal), Chronos = state and its effects, Hermes = telling the user,
  Archive = storing, each client = its own conversation. Oracle untouched.
- Brain back is pushed (presence relax → drain), mirroring the existing «release held notifications».
