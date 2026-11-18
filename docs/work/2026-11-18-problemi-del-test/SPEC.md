# SPEC — Problems found in the owner's real test

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via project chat (Marko, 2026-11-17 real test: 17 points + 2 screenshots; design agreed 2026-11-18, go «inizia» 2026-11-18) |
| **Status** | In progress |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, main f828465)

- **Stuck replies.** `llm_bus` (dossier 2026-11-16-bus-llm): 1 local worker, no timeout in the queue. A waiting call
  blocks a server thread (sync endpoints share the threadpool), so many waiting module calls starve every Oracle
  endpoint (chat, `/api/ui/*` → page «Requests and models» says «not reachable»). A module call whose caller already
  timed out still waits and then runs. A running background call is never interrupted by the owner's turn. The WebUI
  drops `status` frames, so the owner sees nothing while waiting.
- **Stop / new chat blocked.** WebUI ChatHub answers «cancel» with a `status` frame the client ignores: `isStreaming`
  stays true; «New conversation» does not reset it.
- **`alt::` keys and English labels.** Plugin `host.api` uses `fetch` (no i18n interceptor) → data labels such as
  notification titles and MCP areas show the raw source with its tag. `localize` (TS and Python) skips the whole
  sub-tree under a KEEP_KEYS key (`page`, `action`, `source`…) → plugin page labels stay English (breadcrumb).
- **WebUI.** Native `title` tooltips everywhere; pinned entries scroll with the rest; collapsed-sidebar button almost
  transparent; breadcrumb pieces not links; composer hint line; «Talk» in the header; stat tiles not clickable.
- **Chains.** Three editors (setup, Assistant › Models, Voice); memory (embedding) only one model in the setup; model
  lists not filtered per use (Gemini shows TTS/image models for chat); Gemini quota only reacted to, kept in memory.
- **Pages.** Deliveries: module names, raw HTML, technical English errors, unclear states. Development: title cut,
  the source (Argus log sample in `context`) never shown; Argus proposes only on ERROR/CRITICAL, not on recurring
  `[🔄]` fallbacks.
- **Chat.** No queue/steering while answering; no «/» commands.
- **Mascot.** Aphrodite «Pet» (page Look, section «Animaletto»): shows only with an image (ComfyUI or upload).

## 2. Goal

Every point fixed everywhere it appears, one reusable component per pattern, plain labels.

## 3. Scope and design (packages, one PR each, merged when CI is green)

- **A — stuck replies.** Bus waits do not hold a server thread for the pages (pages/status served on their own path);
  each queued call carries the caller's deadline and is dropped (`[🔄]` log, error to the caller) when it expired
  before running; the owner's turn interrupts a running *background* local call (closed connection, the call is put
  back in line and runs again after); `status` frames shown in the WebUI thinking line; a waiting turn emits a status
  «finishing a background job, then it's you». WebUI stop closes the answer client-side at once; new conversation
  resets the stream state; the WebUI error text names no module.
- **C — language.** `host.api` answers go through `localize`; KEEP_KEYS apply only to string values; the tag is always
  stripped as safety net; regression tests (TS + Python).
- **D — WebUI one pattern.** One tooltip (`hx-tooltip`, shared with the SDK) that upgrades every `title` and the
  `aria-label` of icon-only buttons; pinned block outside the scroll area; solid collapsed-sidebar button; breadcrumb
  pieces are links; composer: no hint line, «Talk» next to the mic, dictation inserts at the cursor; `hxk-stat` tiles
  with `items`/`open` open a panel with the list (applied where a tile counts things).
- **E — chains.** One chain editor component used by setup, models, memory and voice; embedding becomes a real chain
  (each vector records its model; search uses vectors of the same model); model pickers filtered by capability
  (Gemini methods + names, Ollama `/api/show` capabilities, OpenAI-compatible by name + «Try»); Gemini limits learned
  from the 429 details (limit value, per minute/day, retry delay), used to skip a model just before the limit;
  missing details → today's reactive skip (`[🔄]`); «exhausted until» persisted and shown («available again at …»).
  Context settings: one plain choice with the technical ones under «Advanced».
- **F — pages.** Deliveries rebuilt (area icons instead of module names, one sentence per state, plain error text with
  the action, HTML stripped, grouped by day, details on demand). Development: full title wraps, section «Where it comes
  from» with the redacted log sample, when and how often; Argus writes a readable translated title. Argus treats a
  recurring `[🔄]` line like a recurring error.
- **B — chat.** While an answer runs: Enter queues the message (sent after, merged by `queued_chat`), «Add now» steers
  (the agent loop reads it at its next step). WebUI and Telegram. «/» opens the command catalog with completion; a «/»
  command runs the tool directly.
- **G — mascot.** Named «Mascotte», findable from personal settings and Ctrl+K, a built-in animated mascot that works
  without ComfyUI (states: idle, thinking, speaking, listening, sleeping), draggable and docked to the edges, generated
  or uploaded pictures still possible.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: the assistant answers and says what it is doing; the site is consistent and readable.
2. Owner module (R1): Oracle (bus, chat), WebUI + SDK (UI), Hermes/Hephaestus/Argus plugins (pages), Aphrodite (mascot).
3. Configuration: no new switches; existing Themis settings only.
4. Push or poll: unchanged.
5. Who confirms: Forge tasks from Argus still need the owner's approval.
6. WebUI stroke icons, no emoji; Telegram keeps its emoji.
7. Stop, correct, undo: stop works; queued messages can be removed before they leave.
8. Docs: module docs, `docs/ARCHITECTURE.md`, `docs/AI-GUIDE.md`, `DESIGN-SYSTEM.md`, swagger for endpoint changes.
9. Texts: English source + Italian catalog.

## 5. Acceptance criteria
Per package in `PROGRESS.md`; every bug gets a regression test.
