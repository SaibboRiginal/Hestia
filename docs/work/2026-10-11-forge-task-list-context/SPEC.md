# SPEC — Full Forge task list in chat · local Forge engine within the model window

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User via external chat (Claude Code cloud session, project thread "Lista task di sviluppo incompleta") · 2026-10-11 |
| **Status** | Implemented on main — waiting for the user's real run |

User's words (Italian original): in "Crea con Hestia" he asked "mi dai una lista di tutti i task di sviluppo e il
motivo?" and got 2 tasks of 8, a truncated reason, and an answer opening with "Sveglia.". He also pasted Forge
task `910395` (local engine): "test falliti · agent stopped without finish (turn limit or no tool use)".

## Causes found
1. `forge_tasks` returned the full public record of every task (summary, diff_stat, deploy plan, 500-char test
   tail…); Oracle's agent loop cuts every tool result at 2000 chars, so the model saw only the first 2 tasks.
2. "Sveglia." = the presence line "Stato assistente: Sveglio" in the client instructions, echoed by the model.
3. Task 910395: Forge's `local` profile went to Ollama's OpenAI endpoint `/v1`, which ignores `num_ctx`: Ollama
   reloaded the model with its small default window while Forge budgeted ~90k chars (~25k tokens). After reading a
   few large files the prompt overflowed, the model's answer stopped mid-sentence twice (no tool call) and the loop
   ended. The half-done edits then broke Athena's tests.

## Scope / design
- Hephaestus `GET /api/hephaestus/forge/tasks/brief`: one line per task `id6 · state · services · request`, the
  request clipped evenly so the whole list stays < 1600 chars; too many tasks → oldest closed ones omitted and
  counted (`by_state`, `omitted`). MCP tool `forge_tasks` uses it. `GET /forge/tasks` (WebUI) unchanged.
- Oracle agent loop: truncation marker says the rest is missing (never present it as complete).
- Oracle presence line marked as internal context; style contract: no opening interjections / assistant state.
- Oracle LLM gateway: built-in `local` profile served through Ollama native `/api/chat` with the same
  `num_ctx` + `keep_alive` as every Oracle call (no reload), translated to/from the OpenAI shape;
  `finish_reason=length` when the window fills; `/api/llm/profiles` reports `context_window`.
- Forge built-in engine: prompt budget from the reported window (≈3 chars/token, 70%), trims old tool outputs
  then clips the latest; precise stop reason (context full / turn limit / stopped calling tools).

## Acceptance
- With 8 tasks the chat tool result holds all 8 lines with their request (< 2000 chars).
- A local Forge run never sends more than the window; a cut answer is reported as "model context full".
- Tests: `Hestia-Hephaestus/tests/test_forge_context_fit.py`, `Hestia-Oracle/tests/test_local_context.py`
  (`TestGatewayOllamaNative`).

## Not in scope
- Raising the default `oracle.provider.ollama.num_ctx` (8192): coding on a local model needs ≥32k tokens, the
  user chooses it in Impostazioni → Sistema → Oracle → Contesto (VRAM-dependent).
- Task 910395 itself: its change is not usable (proposal from Athena, tests broken) — to be rejected by the user.
