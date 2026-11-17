# SPEC — Chat: modalità, ragionamento visibile, contesto e consumi

| Version | Source | Status |
|---|---|---|
| 1.0 | user via Claude project chat (Marko, 2026-10-11) | in progress |

## Goal
In the WebUI chat Marko could not find (1) the conversation mode (rapida, pensata, CoT),
(2) how the reasoning is shown (nascosto, compatto, dettagliato, dal vivo), (3) context-window
usage and usage/consumption depending on the provider in use.

## Findings (before)
- The chat header had a small `Auto/Veloce/Ragionamento` select, never remembered, not in Themis,
  not available on Telegram. Oracle `thinking` still took the quick-chat shortcut (docstring said
  otherwise). No CoT mode.
- Reasoning display existed only in Impostazioni → Personali (hidden/compact/detailed), the WebUI
  backend default was `hidden` → nothing shown out of the box; no `live`; the "Crea con Hestia"
  drawer ignored the setting.
- Oracle `/api/chat/context` existed (estimate + `runtime`), the WebUI never showed it. Window =
  Ollama `num_ctx` whatever the provider; Gemini / Anthropic / Claude CLI usage not recorded.

## Scope / design
1. **Mode = Themis setting** `oracle.chat.mode` (scope user: profile → client → session), options
   `auto` (Auto), `quick` (Rapida), `thinking` (Pensata), `cot` (CoT). Owner Oracle.
   - `/api/chat` `mode` empty → Oracle resolves the setting for client+session; explicit value wins.
   - quick: one call, no tools. auto: classifier decides (unchanged). thinking: always agent loop,
     model reasoning on (normal). cot: always agent loop, reasoning deep, ≥50 turns, plus one prompt
     line asking a step-by-step plan and a short recap of the steps in the answer.
   - WebUI: selector in the composer; a change writes scope `session` (this conversation), the
     message also carries the mode explicitly. Personali shows the default (generic Themis row).
   - Telegram: `/settings` gets "Modalità" (client layer `telegram`), like tone.
2. **Reasoning display** (presentation, client-local): `hidden | compact | detailed | live`,
   default `compact`. compact = closed box, one line per step; detailed = open box with full
   reasoning text and tool results; live = open while working, closes when the answer arrives.
   Editable from the chat ⚙ popover and from Personali; the drawer follows it.
3. **Context & consumption** in the chat header: gauge (% of the window of the provider in use) +
   popover: provider/model, billing kind (locale gratis · API a consumo · abbonamento), context
   breakdown, this conversation's tokens (input / cached / output, calls), API-equivalent cost when
   the provider reports it (Claude CLI), "Compatta" button.
   - Oracle: `llm_stats` also records Gemini, Anthropic API, Claude CLI; per-conversation totals
     (session id bound to the chat stream via a contextvar); `/api/chat/context` adds `active`
     (use case generic: provider, label, model, billing, context_window) and `session_usage`.
     Used % = last real prompt size of this conversation when known, else the estimate.
   - Context window per provider type: Ollama/OpenAI-compatible = `oracle.provider.ollama.num_ctx`,
     Gemini 1,048,576, Anthropic / Claude CLI 200,000 (class constants).
   - WebUI backend: `GET /api/webui/chat/context`, `POST /api/webui/chat/compact` (Hub → Oracle).

## Acceptance
- Composer shows Auto/Rapida/Pensata/CoT, remembered per conversation, default from Personali.
- Reasoning visible by default (compatto), switchable from the chat.
- Header gauge shows % and tokens of the current conversation for the active provider.

## Out of scope
- Real subscription quota of Claude (not exposed by the CLI); provider pricing tables.
