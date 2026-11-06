# SPEC — Hestia viva: persona, voce breve, consapevolezza, reazioni, eventi

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via external chat (thread «Rendere Hestia viva come Verity», 2026-11-06) |
| **Status** | Approved plan («puoi iniziare con lo sviluppo», 2026-11-06) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, main 4f45189)

Study of the Minecraft mod Verity JE (decompiled 6.1, `/mnt/project-files/valutazioni/verity-vs-hestia.md`):
one langchain4j call with ~35 small game tools, an XML persona filled from state (karma, day), 1–2 sentence
answers, events of the game sent as `<SYSTEM>` turns, idle talk. Hestia:

- Persona `prompt_config.analyst_persona_default`: «voce femminile, professionale, lucida…» + rules 1–13 +
  Telegram format; style contract «Corto > lungo». `oracle_prompts.json` is empty.
- `oracle.chat.tone` / `oracle.chat.instructions` (Themis) and presence lines (`oracle_presence.py`).
- A spoken turn is not known to Oracle: WebUI «Parla» (`live-voice.service.ts`) and Telegram voice notes
  (`run_chat_turn(spoken=True)`) send a normal chat turn.
- Turn in `auto`: classify (LLM) → quick answer or agent loop. The classifier also narrows the tools (≈250 tools /
  30k tokens do not fit a local model), so it stays.
- After every turn, in background: mood capture (gated), memory extraction (gated), **controls extraction
  (`user_control_service.extract_and_save_controls`): one LLM call every turn, no gate**.
- The chat prompt does not see the owner's mood of today (Psyche `GET /api/mood/today`), the last notifications
  Hestia sent (Hermes `GET /api/notifications`), nor what the owner opened/started (Metis taps, no list endpoint).
- No reactions anywhere (WebUI, Telegram, Oracle stream).
- Events reach the owner only as Hermes notifications.
- Agents: one agent loop with up to 8 tools in parallel per round; no parallel sub-agents.

## 2. Goal

Hestia feels like a person: her own character, short answers unless more is needed, aware of what the owner says
and does and of what she did, reacts with emoji like any chat, and gets faster. Nothing paid is required (Marko:
«non voglio cose a consumo»): everything works on the chains already configured.

## 3. Scope and design

### F1 — Persona and spoken turns (Oracle, WebUI, Telegram)
- New identity block at the top of `analyst_persona_default` (rules 1–13 and Telegram format unchanged): a person
  who lives with the owner, warm, sharp, frank, ironic when it fits; uses his name now and then; uses memory
  without announcing it; tone follows the context; **1–2 sentences unless he asks for details or the task needs
  more**; never invents. Caveman style (short lines).
- `ChatRequest.spoken: bool` (Oracle `/api/chat`): the turn is heard and answered aloud. Oracle adds the prompt
  `voice_turn_contract` (1–2 spoken sentences, no lists/markdown/links/emoji, numbers in words when short).
- WebUI: «Parla» sends `spoken: true` (SignalR `chat` message → `ChatHubMessage.Spoken` → Oracle body).
  Telegram: a voice note with spoken replies on (`voice_service.is_live`) sends `spoken: true`.

### F2 — Speed (Oracle)
- Controls extraction gets a deterministic gate (`user_control_service.looks_like_control`): only messages that
  talk about notifications, reminders, quiet hours, «non chiedermi», «smetti», «basta»… reach the LLM.
- The classifier stays (it narrows the tools for local models); measured times keep using the existing logs
  (`chat_phase_timing_ms`, `background_phase_timing_ms`) and the Cervello page.

### F3 — Awareness (Oracle, Metis)
- `core/services/awareness.py`: for owner turns Oracle adds up to 3 short background lines, cached 60 s:
  - mood of today (Psyche `/api/mood/today` → `summary.mood_word`, energy, stress);
  - the last 3 notifications Hestia sent today (Hermes `/api/notifications?limit=5` → title, time);
  - the last things the owner opened or started (Metis new `GET /api/metis/usage/recent?limit=` → ref, client,
    time).
  Each source fails silently (`[🔄]` log, line left out); timeout 2 s each, read in parallel.
- Tunable `oracle.chat.consapevolezza_righe` (int, 3, 0–6; 0 = none), group Contesto.

### F4 — Emoji reactions (Oracle, WebUI, Telegram)
- Hestia → owner: the model may open the answer with `[[r:<emoji>]]` (prompt line in the style contract). Oracle
  strips it from the stream and emits `{"type":"reaction","emoji":"👍","target":"user"}` before the tokens; an
  answer made only of the marker = reaction alone (no text bubble). Clients: WebUI shows the emoji on the owner's
  message; Telegram calls `setMessageReaction` on the owner's message (emoji outside Telegram's list → no
  reaction, logged).
- Owner → Hestia: WebUI reaction picker on her messages; Telegram `message_reaction` updates. Both call Oracle
  `POST /api/chat/reaction {session_id, emoji, text}` which saves one history line
  «[reazione dell'utente: 👍 a «…»]» so the next turn sees it. No LLM call.
- Chat reactions are real emoji (Marko 2026-11-06: the no‑emoji rule is for UI chrome, not chat content).

### F5 — Notifications as a sentence of Hestia (Hermes) — an option (Marko 2026-11-06)
- Hermes setting `hermes.notifiche.stile`: `scheda` (default, as today) · `frase`. With `frase`, Hermes (still the
  only sender) asks Oracle (`narrate` → `/api/llm/generate`) to say an informative notification as one short
  sentence in the persona, then delivers it as usual. Warnings, errors, health/action-required alerts and events
  with buttons, questions or secrets stay cards. Oracle down → the card text unchanged.

Agents (modules as Oracle agents, parallel work) are out of scope: their own thread «Rendere ogni modulo un agente di Oracle» (Marko 2026-11-06).

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job: an assistant that feels present, short, aware and fast.
2. Owner module: Oracle (persona, prompt, stream), Metis (tap list), Hermes (delivery), clients (display).
3. Configuration: `oracle.chat.consapevolezza_righe`, `hermes.notifiche.stile` (a style, not an on/off switch).
4. Push: reactions ride the existing chat stream; awareness is read at turn time.
5. Confirms: nothing new writes data; reactions are history lines.
6. WebUI: emoji only inside chat bubbles (reactions); Telegram: native reactions.
7. Undo: a reaction can be removed (same endpoint with `emoji: ""`).
8. Docs: hestia-oracle.md, hestia-metis.md, hestia-webui.md, hestia-telegram.md, hestia-hermes.md, swagger.yml,
   ARCHITECTURE (stream contract), root CHANGELOG.

## 5. Acceptance criteria
- A spoken turn answers in ≤ 2 sentences without lists; a written one stays short unless detail is asked.
- A message that is not about notifications/reminders no longer triggers the controls LLM call.
- Owner turns carry the awareness lines when the sources answer; any source down → the turn is unchanged.
- `reaction` frame streamed and stripped from text; WebUI and Telegram show it; owner reactions reach history.
- Unit tests for: persona/contract assembly, spoken flag, control gate, awareness lines (fake Hub), reaction marker
  parser (stream), reaction endpoint, Metis recent taps.

## 6. Open questions
- None (F5 settled as the option `hermes.notifiche.stile`).
