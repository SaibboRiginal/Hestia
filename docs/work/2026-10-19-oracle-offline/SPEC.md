# Oracle offline — Hestia keeps working when Oracle is down

| | |
|---|---|
| **Version** | 3.0 |
| **Source** | user via external chat (Marko, brainstorm 2026-10-19 §0 item 2: «Cervello offline — Argus → Hermes diretto con testo fisso; banner WebUI e avviso Telegram; i messaggi della chat vanno in coda e hanno risposta quando torna»; v2.2: «togli proprio cervello come nome e icona»; v2.3: «metti qualcosa di generico, chi lo legge non deve sapere chi o che cosa»; v3.0: «rendiamolo un po' più sofisticato» + answers of 2026-10-22 (sistema immunitario 1–3 tentativi, stato a sé quando finiscono i modelli, coda smart che decide, «mentre non c'ero», registro eventi notevoli non ridondante con Hermes, fumetto dopo reload, domande dell'assistente come Claude: selezione multipla, campo libero, conferma «per tutto»); v2.0: «deve andare in congiunzione con lo stato che avevamo già adesso, non andiamo a complicarci troppo») |
| **Status** | v2.3 merged (PRs #6 #10 #11). **v3.0 approved by Marko 2026-10-22** (section «v3»), in progress |

## Goal
Oracle is the only LLM core. When it is down the rest of Hestia keeps working and says so: the user is told once,
the clients show it, nothing written in the chat is lost, and every queued message is answered when Oracle
returns. User-facing texts are generic and never name a module (v2.3): state «⏳ Non disponibile», replies «Non posso rispondere adesso: messaggio in coda, ti rispondo appena possibile», back «✅ Di nuovo disponibile dopo N min». Internal names stay `oracle.*` (v2.2). Built **on the assistant presence that already exists** (Chronos: signals → states → effects), not as a
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
- Monitor cycle (already running, no new loop): Oracle's health check failing for at least `argus.oracle.grace`
  seconds (new Themis setting, default 60, so a normal restart/deploy says nothing) → presence signal
  `oracle.offline = true` (meta `since`, refreshed every cycle with a TTL, so a dead Argus does not leave it stuck);
  Oracle healthy again → signal cleared.
- Same moment: one Hermes event (`service.action_required`: the system subscription every client always has;
  `service.health` alerts are opt-in) with fixed `_message` and
  `replaces: "system.oracle"` (one live notice):
  «⚠️ <b>Oracle offline</b>: non risponde. Comandi, notifiche e agenda funzionano; i messaggi in chat restano
  in coda e avranno risposta appena torna.» Back: `closes: "system.oracle"` + «✅ Oracle di nuovo online dopo 14 min.»
  Oracle's generic `service.health` alert is not sent on top of it.
- While the signal is set Argus does not ask Oracle to narrate anything (fixed texts at once, no 60 s waits).

### 2. Chronos — a presence overlay (the existing state)
- New built-in overlay `oracle_offline`: «Oracle offline» ⚠️, priority above the others,
  `when oracle.offline == true`, help «Oracle non risponde: i messaggi restano in coda e avranno risposta appena torna;
  i lavori che usano Oracle aspettano.», effects `work.light: defer`, `work.heavy: defer` (proactive work waits,
  through the effects consumers already read) and new ranked effect **`chat.reply`** (`live < queued`) = `queued`,
  `notice` «Oracle è offline, ti rispondo appena torna». Editable like the other states (`chronos.presence.states`).
- When `chat.reply` relaxes back to `live` (same place as the `notify.level` release), Chronos asks every Hub service
  that declares capability `chat_queue_drain` to answer its queue: `POST /route/<svc>/<drain path>`. No client
  hardcoded (discovered from the Hub registry like Hermes discovers clients).

### 3. Chat queue — Archive stores, each client answers its own
- Archive: table `chat_queue` + `/api/chat-queue` (create, list by client/state, claim with compare-and-set
  `queued → answering`, done/failed). Fields: `client, session_id, target, client_ref, text, created_at, state,
  attempts, answered_at`.
- A client queues a text message when its call to Oracle fails before any answer arrives (connection refused, Hub
  502/503/504, Oracle not registered, timeout before the first frame), and replies at once «⚠️ Oracle è offline:
  messaggio in coda, ti rispondo appena torna.» An error inside an answer (Oracle up, model error) is shown as today.
  Text only; a file while offline gets «rimandamelo appena torno». Archive also down → today's error.
- Drain (on the Chronos call above and at the client's own startup): oldest first, one at a time, replayed to Oracle
  `/api/chat` with the original session and a note in `client_instructions` («scritto alle 10:42 mentre eri offline»).
  No expiry. Telegram answers as a reply to the original message; WebUI backend replays without a browser open,
  Oracle saves the history, an open chat sees it live.

### 4. What the user sees
- **WebUI:** the presence badge shows «⚠️ Oracle offline» (existing popover explains it). The chat page shows a strip
  from the effect `chat.notice` while `chat.reply = queued`, and a queued message has a clock «In coda» until answered.
  No separate banner component.
- **Telegram:** the Hermes notice (closed/replaced when back), the fixed reply per message, `/stato` shows the overlay.

### 5. Docs
`hestia-argus.md` (Alert Flow rewritten to the real flow, Oracle signal, setting), `hestia-chronos.md` (overlay, effect,
drain call), `hestia-archive.md` (queue), `hestia-telegram.md`, `hestia-webui.md`, `hestia-shared.md` if
`presence_client` changes, swagger (Archive, Telegram/WebUI drain), `docs/ARCHITECTURE.md` (known gap removed),
`readme.md` roadmap line, root CHANGELOG.

## Out of scope
- Oracle code (no change). A future Oracle `/health` saying "no model answers" (thread "Oracle a blocchi") can set the
  same signal later.
- A new Argus/Hermes API or a parallel "Oracle state" outside presence.

## Acceptance criteria
1. Oracle stopped > 60 s → presence overlay «Oracle offline», one notice on every client; restarted within 60 s →
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
- Oracle back is pushed (presence relax → drain), mirroring the existing «release held notifications».

## v3 — More sophisticated (draft 3.0, 2026-10-22)
Source: Marko in the Project thread, 2026-10-19 → 2026-10-22. Same principles: one presence state, each module its own
job, generic user texts (no module named), icons + tone in clients, Telegram keeps emoji, tunables in Themis.

### Facts checked in the code (2026-10-22)
- Argus already: detects a module down → `request_hephaestus_remediation(requested_action="auto_health_recovery")` →
  plans rechecks in the agenda with growing waits (`argus.repair.recheck` 10 min … `recheck_max` 360 min), keeps an
  incident list (`health_history`, **memory only**, lost on restart).
- But the repair does nothing real: issue `service_down` selects the read-only triage runbook; Hephaestus executes by
  calling the **sick service's own** maintenance path through Hub (a dead service cannot answer); `argus.remediate.dry_run`
  defaults to true; no container is ever restarted. Hephaestus already restarts containers for Forge deploys
  (`forge/deployer.restart_containers`, Docker socket).
- Oracle already knows when its model chain is exhausted (`llm_chains.ChainExhausted`, `mark_exhausted`), but nobody
  outside sees it.
- Question cards already exist end to end: Oracle `ask_question` → NDJSON `question` frame (kinds `free_text`,
  `single_choice`, `multi_choice`, `confirm`) → WebUI card / Telegram buttons → answer routes an action. **Only modules**
  use it (Themis confirmations); the model itself cannot ask.
- WebUI: the «in coda» hourglass lives only in the page state; a reload loses it.

### A. Questions from the assistant (like Claude) — foundation, needed by C
- Oracle gives the model one tool **`ask_user`**: `{prompt, kind: free_text|single_choice|multi_choice|confirm,
  options?[{value,label,help?}], allow_other?, required?}`. The model calls it when the request is ambiguous, when an
  action is risky or not easily undone, or when it has to choose between real alternatives (with or without thinking).
  Oracle's prompt says when (caveman style): ask only if the answer changes what is done; never for trivia.
- The turn **pauses**: Oracle emits the existing `question` frame and keeps the pending turn (tool call + messages so
  far); the answer resumes the same turn with the answer as the tool result. Timeout (Themis `oracle.ask.timeout`,
  default 24 h) → the turn resumes with «nessuna risposta» and the model goes on with its safest default.
- Pending questions survive a restart: stored in Archive (`/api/pending-questions`), not only in Oracle's memory.
- Clients: WebUI card gains multi-choice (checkboxes + «Invia») and «Altro…» free field; Telegram: inline buttons,
  multi-choice as toggle buttons + «Fatto», free text = the next message. A question asked outside an open chat (queue
  drain, proactive work) is delivered by **Hermes** as a confirmation with the same options (Hermes is the only
  messenger), and the answer comes back to Oracle.

### B. Immune system — real self-repair, 1 to 3 tries
- Argus (diagnosis) stays the one who notices and decides; Hephaestus (hands) does the repair.
- New Hephaestus runbook action `restart_container` for `service_down` / `service_degraded` when the health check fails
  or the container is exited/unhealthy: snapshot (status + last logs) → restart `hestia_<svc>` (existing deployer) →
  health check → result. Only `hestia_*` containers; never Hephaestus itself, never during a Forge deploy of the same
  service (Forge's own rollback owns that window).
- Tries: at most `argus.repair.max_attempts` (Themis, default 3, 1–5) per incident, on the existing agenda rechecks
  (growing waits). Restarts are real by default (`dry_run` default → false for this action only; the read-only runbooks
  stay as they are).
- Gave up after the last try → one Hermes notice (`service.action_required`, `replaces: system.repair.<svc>`) with a
  generic text: «🩺 Un servizio non riparte da solo: ho provato 3 volte. Dettagli nel registro.» + action «Riprova».
  Back → `closes` + «✅ Tornato a posto». Each try is a line in the incident (feeds E).
- If the sick service is Oracle, the existing «Non disponibile» flow runs as today; the restarts happen underneath.

### C. Smart queue — the assistant decides
- Drain no longer replays one message at a time. The client sends Oracle the whole queue for that chat in one call
  (`/api/chat` with `queued: [{text, written_at}]`, use case `chat.queue`). Oracle's model decides, case by case:
  answer each separately, one merged answer, or — when some messages are old or superseded — ask with `ask_user`
  (A): multi-choice «Questi messaggi sono di ieri, li tengo?» and then answers only the kept ones.
- Every queued message ends answered, merged or discarded by the user's choice; none silently dropped.
- No `/coda` command (Marko: automatic).

### D. «Mentre non c'ero» — one catch-up message
- Case: unavailable 7:50–9:30; at 8:00 the morning recap, at 9:00 a gym reminder, a mail arrives meanwhile.
- While the overlay holds, Chronos already defers work (`work.light/heavy: defer`). Chronos records what was deferred
  or failed in the window (agenda runs, Iris events that needed the assistant) in the incident window.
- On relax, Chronos (owner of the agenda) re-runs the jobs still meaningful (a reminder whose time is long past is not
  re-sent alone) and asks Oracle for **one** text «Mentre non c'ero: …» covering everything, delivered by Hermes.
  No list → nothing sent.

### E. Status «Limitato» — every model is exhausted
- Oracle reports in its `/health` `{models: "ok" | "limited" | "none"}` from its chain state (no notification logic in
  Oracle). Argus reads it in the monitor cycle and sets presence signal `oracle.limited` (grace = `argus.oracle.grace`).
- Chronos overlay `oracle_limited`: «Limitato», icon `battery-low`, tone warning, help «rispondo, ma in modo ridotto:
  i modelli principali non sono disponibili», effects `work.heavy: defer`, `chat.style: brief`. `none` = all chains
  exhausted → same as «Non disponibile» (`chat.reply: queued`).
- One Hermes notice like the existing one (`replaces/closes system.oracle`, generic text).

### F. Notable events journal
- Not the request log (that is the «Registro persistente dell'Hub» work) and not notifications (Hermes): a short,
  curated history of things worth remembering — outages and their length, «Non disponibile»/«Limitato», repairs and
  their tries, gave-ups, Forge rollbacks, backups failed.
- Argus owns it (it already keeps incidents) and stores it in **Archive** (`/api/system-events`), so it survives
  restarts. Argus WebUI page «Registro»: a timeline, one line per event with icon + tone, duration, what was tried.
- No double alerting: an event in the journal sends nothing by itself; Hermes notices link to it («Dettagli nel
  registro»).

### G. WebUI: the hourglass survives a reload
- On page load the chat asks its backend for this session's queued items (Archive `/api/chat-queue?client=webui`) and
  draws them with the hourglass until answered.

### Order
A → C (needs A) · B → F (F shows B's tries) · E · D · G. Each phase: code, tests, module `.md`, swagger, root CHANGELOG.

### Acceptance criteria (v3)
1. The model asks via a card (WebUI) / buttons (Telegram) in each of the 4 kinds; the answer resumes the same turn;
   a pending question survives an Oracle restart.
2. A stopped module is restarted by itself within the first recheck; after 3 failed tries one notice, no more tries.
3. Five queued messages, two of them from yesterday → the assistant answers sensibly (merged or asks about the old ones).
4. Outage across a recap + reminder → one «Mentre non c'ero» message after return, no duplicates.
5. All chains exhausted → «Limitato», notice; models back → closed.
6. Journal page lists the outage, the tries and the return after an Argus restart.
7. Reload of the WebUI chat while a message is queued → hourglass still there.
