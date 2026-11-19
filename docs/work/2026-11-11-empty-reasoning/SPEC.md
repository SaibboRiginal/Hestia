# SPEC — «Ragionamento» shown with nothing inside

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat |
| **Status** | Done |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code)

The owner: in the chat, mode Auto, the «thinking» is always shown even when empty; he cannot tell whether the
model is really thinking or the block is shown by default.

- Oracle sends a `thinking` frame for three things (`core/agent_loop.py`): the model's reasoning text
  (`action=reasoning`, only when not empty), each tool about to run (`tool_call`) and each tool result
  (`tool_result`).
- The WebUI (`chat-thinking`) drew ONE block for all of them, always titled «Ragionamento · N passi», where N
  counted every frame. Telegram (`reply_renderer`) did the same, counting only reasoning: «Ragionamento · 0 passi ·
  1 strumenti».
- In Auto almost every turn uses a tool (memory, agenda…) and a model that does not think (or a turn where it
  did not) returns no reasoning: the block was there on every answer, called «Ragionamento», with tool lines only.
  So it was shown by default; it did not mean the model had reasoned.
- Some local models return the empty wrapper (`<think>\n\n</think>`) as reasoning: after `strip()` it was not
  empty and became a reasoning step with nothing to read.

## 2. Goal

«Ragionamento» appears only when the model really reasoned. What is not reasoning is named for what it is.

## 3. Scope and design

- **Oracle** — `stream_emitter.clean_reasoning()` removes thinking wrappers; the agent loop emits a `reasoning`
  frame only when text is left. The frame protocol does not change.
- **WebUI** — `chat-thinking` (chat page and «Crea con Hestia» drawer, one component): with at least one
  reasoning step the title is «Ragionamento · N passi · M strumenti» (N = reasoning steps only) and «Sto
  ragionando…» while working; with tools only it is «Strumenti usati · M» (zap icon) and «Uso gli strumenti…».
  `chat.service` drops a frame with nothing to show.
- **Telegram** — same rule in `reply_renderer._reasoning_block`; whitespace-only reasoning is not a step.
- The display setting (Nascosto / Compatto / Dettagliato / In diretta) is unchanged and still hides both.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: know at a glance whether the answer was reasoned.
2. Owner module (R1): Oracle owns the frames; each client owns its drawing.
3. Configuration: none new.
4. Push or poll; automatic and manual: n/a.
5. Who confirms; what the assistant may do alone: n/a.
6. WebUI (icons, no emoji) and Telegram (tool + display): both, icons `brain` / `zap`.
7. Stop, correct, undo: n/a.
8. Docs that change: `hestia-webui.md`, `hestia-telegram.md`, `hestia-oracle.md`.

## 5. Acceptance criteria

- An answer with tools and no reasoning never shows the word «Ragionamento» (WebUI, drawer, Telegram).
- An answer with neither shows no block.
- An answer with reasoning shows «Ragionamento» with the count of reasoning steps.
- An empty thinking wrapper from a model produces no reasoning step.
