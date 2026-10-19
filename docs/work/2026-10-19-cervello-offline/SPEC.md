# Brain offline — Hestia keeps working when Oracle is down

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (Marko, brainstorm 2026-10-19 §0 item 2: «Cervello offline — Argus → Hermes diretto con testo fisso; banner WebUI e avviso Telegram; i messaggi della chat vanno in coda e hanno risposta quando torna») |
| **Status** | Draft — waiting Marko's approval before code |

## Goal
Oracle is the only brain. When it is down (crash, restart that does not come back, container stopped) the rest of
Hestia must keep working and say so clearly: the user is told once, every client shows it, nothing written in the
chat is lost, and every queued message gets its answer when the brain returns.

## Facts checked in the code (2026-10-19)
- Argus already sends its alerts **through Hermes** (`alert_worker` → `POST /route/hermes/api/events/ingest`); Oracle
  is only used to *narrate* the text and there is a plain-text fallback. But each narration waits up to 60 s on a
  dead Oracle before falling back, and Oracle being down produces only a generic `service.health` alert.
- Docs contradict each other and the code: `Hestia-Argus/hestia-argus.md` *Alert Flow* says "Oracle dispatches via
  Hermes" and "if Oracle is unreachable, a TODO stub logs the failure"; `docs/ARCHITECTURE.md` (known gaps) says
  "alerts still go via Hermes with plain text" (true); `readme.md` roadmap says "alert directly on Telegram"
  (against the rule *Hermes is the only outbound messenger*).
- Telegram chat: Oracle failure → the status message becomes "⚠️ Connessione all'Oracle fallita" + raw error; the
  message is lost. WebUI chat: the stream fails and the message is lost.
- Hermes narrates events without `_message` through Oracle (with a fallback): on a dead Oracle each one waits.
- Oracle `/health` is a plain `ok`; it does not say whether a model answers (that is the "Oracle a blocchi" thread).

## Scope

### 1. Brain state — Argus (diagnosis)
- Argus owns one state: `brain = online | offline`, with `since` and `reason` (`unreachable`, `unhealthy`,
  `unregistered`). Fed by the monitor cycle it already runs (Oracle's health check), no new loop or agenda job.
- **Client report (push):** a client whose chat call to Oracle fails calls `POST /api/argus/brain/report`
  (via Hub). Argus does not trust it blindly: it checks Oracle's `/health` at once and flips the state only if that
  check fails. The same report after the brain is back speeds up recovery detection. Otherwise recovery is seen at
  the next monitor cycle (≤ `argus.poll.interval`, 60 s).
- `GET /api/argus/brain` → `{state, since, reason, queued}` (`queued` = messages waiting, read from Archive).
- **Grace:** the user is told only if the brain stays offline for `argus.brain.grace` seconds (new Themis setting,
  default 60), so a normal Oracle restart (Forge deploy) never notifies. The chat queue (§3) works from the first
  failed message, independently of the grace.
- While the brain is offline Argus does not ask Oracle to narrate anything: fixed texts at once (no 60 s waits).
  Oracle's own generic `service.health` alert is replaced by the brain notice (no double message). Repair requests
  to Hephaestus and agenda rechecks for Oracle stay as today.
- Future hook (not built here): if Oracle's `/health` one day reports `brain: "no_model"` (whole model chain
  exhausted, owned by the "Oracle a blocchi" thread), Argus treats it as `offline` with `reason: no_model`.
  **No Oracle code changes in this work.**

### 2. Notice — Hermes (only outbound messenger)
- Argus publishes event `system.brain` (domain `system`) to Hermes with a fixed `_message`, `_title`,
  `_level: warning`, `replaces: "system.brain"` (one live notice, Hermes' repeat chain) and a new generic key
  `_system: {brain: "offline", since, reason}`.
  Text: «🧠 <b>Cervello offline</b> da 1 min: Oracle non risponde. Comandi, notifiche e agenda funzionano; i messaggi
  in chat restano in coda e avranno risposta appena torna.»
- Back online: event with `_system: {brain: "online"}`, `closes: "system.brain"` (`decision: resolved`) and a short
  notice «🧠 Di nuovo online dopo 14 min · rispondo ai 3 messaggi in coda» (the count only when > 0).
- Hermes stays generic:
  - `_system` is passed through to every client as `system` in the client notify request (a "state hint");
    Hermes does not interpret its content, except:
  - while the last relayed `_system.brain` is `offline`, Hermes skips its own Oracle narration and uses its plain
    fallback (no waits on a dead brain).
  - `system.brain` is added to the system subscriptions bootstrapped at startup (`owner`, every client), like
    `service.action_required`.

### 3. Chat queue — Archive (storage) + each client (its own conversation)
- Archive gets a table `chat_queue` + `/api/chat-queue` (only DB owner): `id, client, session_id, target,
  client_ref` (e.g. Telegram message id to reply to), `text, created_at, state` (`queued → answering → answered |
  failed`), `attempts, answered_at`. Claim = compare-and-set `queued → answering` (no double answers if two
  drains race).
- **When a message is queued:** the client's call to Oracle fails before any answer arrives (connection refused,
  Hub 502/503/504, Oracle not registered, timeout before the first frame). An error *inside* an answer (Oracle up,
  model error) is shown as today. Text messages only in v1; a file/photo while offline gets «Il cervello è offline:
  rimandamelo appena torna» (files are large and Oracle reads them in the same turn).
- The client answers at once with a fixed text: «🧠 Il cervello è offline: messaggio in coda (n° 2), ti rispondo
  appena torna.» and sends the brain report to Argus (§1).
- **Drain (push, not poll):** the client drains *its own* queue when Hermes delivers `system.brain online`, and at
  its own startup. Oldest first, one at a time per session, each replayed to Oracle `/api/chat` with its original
  session and a note in `client_instructions` ("messaggio scritto alle 10:42 mentre eri offline") so the answer
  accounts for the delay. No expiry: every queued message is answered (no task is abandoned).
- **Telegram:** answer sent as a reply to the original message; if the queue had more than one message, a single
  header «Rispondo ai 3 messaggi arrivati mentre ero offline» first. Confirm buttons and commands are unchanged
  (commands do not use Oracle).
- **WebUI:** the backend (not the browser) drains, so it works with no tab open. Oracle saves the history as for any
  chat; an open chat sees the answer appear live (SignalR). In the chat the queued message shows a clock «In coda»
  that becomes the normal answer.
- If Archive is also down, the client falls back to today's error message (nothing to queue into).

### 4. Clients show the state
- **WebUI banner** (top of every page, design system warning style): «🧠 Cervello offline da 12 min · i messaggi
  restano in coda (3) e avranno risposta appena torna». Source: `GET /api/system/brain` (WebUI backend → Hub →
  Argus) at load, then the `system` hint pushed by Hermes (SignalR to open tabs). Gone when `online` arrives.
  The chat composer stays enabled.
- **Telegram:** the Hermes notice (§2) + the per-message fixed reply (§3). The notice is replaced/closed when the
  brain is back (repeat chain: delete/«↻ Sostituito»).

### 5. Docs
`hestia-argus.md` (Alert Flow rewritten to the real flow + brain state, endpoints, setting), `hestia-hermes.md`
(`_system`, bootstrap, narration skip), `hestia-archive.md` (chat queue), `hestia-telegram.md`, WebUI md, swagger
(Argus, Archive, Hermes `ClientNotifyRequest.system`, WebUI), `docs/ARCHITECTURE.md` (known gap removed, brain-offline
rule), `readme.md` roadmap line, AI-GUIDE if it mentions it, root CHANGELOG.

## Out of scope
- Model chain / quota fallback and Oracle `/health` reporting `no_model` ("Oracle a blocchi").
- Presence state for the brain (could later become a presence signal; not needed now).
- Proactive callers (Athena, Chronos jobs, modules) that call Oracle keep their own existing fallbacks/retries.

## Acceptance criteria
1. Oracle stopped for > 60 s → exactly one Telegram notice and one WebUI notification; WebUI banner on every page.
2. Oracle restarted within the grace → no notice at all.
3. Messages written in Telegram and WebUI while offline → fixed "in coda" reply, then, once Oracle is back, an
   answer to each, in order, in the right chat; nothing answered twice.
4. Brain back → notice closed/replaced, «di nuovo online» notice, banner gone.
5. While offline, Argus/Hermes notifications go out at once with fixed/plain text (no 60 s waits on Oracle).
6. Docs consistent: no "TODO stub" nor "direct Telegram" left.
7. Unit/api tests: Argus state machine (grace, report, recovery), Archive queue CAS, Hermes `_system` pass-through +
   narration skip + bootstrap, Telegram enqueue/drain. Cloud bench (`python tools/cloud_test.py all`): stop Oracle,
   write in WebUI, screenshot banner + queued bubble, start Oracle, screenshot the answers.

## Design decisions
- **Who does what:** Argus = diagnosis (state), Hermes = telling the user, Archive = storing the queue, each client =
  its own conversation (queue in, replay out). Oracle unchanged. No module takes another's job; no direct Telegram.
- **Clients drain, not Oracle:** the answer goes back where the question was asked, the same way as a live chat; Oracle
  would otherwise need to deliver messages (Hermes' job) and know every client.
- **Push:** the client that fails reports it at once; recovery is pushed by Hermes to the clients. The only
  periodic check is Argus' existing monitor cycle.
