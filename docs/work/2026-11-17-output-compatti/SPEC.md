# SPEC — Shaped outputs for small context windows

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Valutare trucchi per risparmiare token»; evaluation `valutazioni/trucchi-risparmio-token.md`, ideas 1, 2, 4 approved 2026-11-17) |
| **Status** | Implemented (owner's real run pending) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, before this work)

- The local model window is 16k–32k (owner, 2026-11-17), at most 256k later with dedicated hardware.
- Agent loop: a tool result became `str(result)` (a Python repr when the module answered a dict: quotes, `None`,
  `True`) and was cut at the first 2000 chars (`oracle.agent.tool_result_max_chars`) whatever the window: a list of
  40 events showed the first 6 with broken JSON and no count. Older results became a stub saying «call the tool
  again» (a second call to the module).
- Forge local engine: test output = last 4000 chars (a failure in the middle of a long run was lost); search = 80 lines.
- JSON put in prompts with `indent=2` (module entities in `ContextBuilder`, notification payloads): spaces paid each turn.

## 2. Goal

The same facts reach the model in fewer tokens, and nothing shortened is ever mistaken for the whole; the limits
follow the window of the model that answers, so 16k works today and 256k tomorrow without touching anything.

## 3. Scope and design

### 3.1 One shaping function (`hestia_common.compact_output`)
- `shape(value, max_chars) → Shaped(text, cut, full, total_items)`: dict, list, JSON text or plain text. No model, no
  dependency (owner's rule: ideas from external repos are rebuilt in Hestia, nothing is installed).
- JSON: empty values (None, "", [], {}) removed at every depth (False and 0 stay); a list of ≥ 3 objects sharing
  their keys becomes `{"columns": [...], "rows": [[...]]}`; compact separators. Over the budget the longest lists keep
  the most items that fit (binary search): items with an error (`ok: false`, `error`, `errors`, `failed`,
  `exception`) first, then the first ones in order, and `"more": "showing N of M"` (top-level list: a line after it).
  Only when no list is left, a plain cut with a note.
- Text and logs (`shape_text`): consecutive repeated lines → one line `[×N]`; over the budget 30 % head + 50 % tail
  + the middle's error lines (error, fail, traceback, exception, assert, warning, denied, refused, timeout) and
  `[…N lines omitted…]`.
- `full` is the whole output, shaped without loss, for «the rest on request».

### 3.2 Oracle agent loop
- `tool_result_budget(window, chars_per_token)`: setting `oracle.agent.tool_result_max_chars` default **0 =
  automatic** = 4 % of the answering model's window (the same window as budget and compaction), floor 800, ceiling
  24,000 chars. 16k → ~2,000 (today's value), 32k → ~3,900, 256k → 24,000. A number in the setting forces it.
- Every tool result goes through `shape()`; when cut, the note says «not the whole result, never present it as
  complete» and how to get the rest.
- `result_more(ref, part)`: turn tool always present when the turn has tools (stable, so the cached prefix does not
  change). Results longer than 200 chars are kept whole for the turn under `r1`, `r2`…; parts of one budget each.
  Old results stubbed under pressure point to `result_more(ref=…)` instead of «call the tool again». Read-only, no
  call to the module, no side effect.
- Decision: no new setting, no switch; the existing setting changes default (0 = automatic, like the local window).

### 3.3 Forge (Hephaestus)
- `AgentTools.t_run_tests` and `t_search` return `shape_text(...)` (4000 / 6000 chars): a failure in the middle of a
  long run now reaches the model. `run_test_command` keeps its long output for the Sviluppo page (not a model).
- Claude Code as engine: the commands it runs by itself stay its own; Hestia shapes what passes through its tools.

### 3.4 JSON in prompts without indent
- `ContextBuilder.compact_entities_for_prompt` and `OracleEngine.format_payload` dump compact JSON.

### 3.5 Module agents (idea 4)
- Not on main yet (thread «Rendere ogni modulo un agente di Oracle»): the answer contract for an agent («first line
  = result or blocker, then only the data the task needs, compact, no preamble, no recap, no advice not asked») and
  the rule «agent results go through `shape()` with the same budget» were handed to that thread.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: answers with a small local window stay complete and correct (counts, errors) instead of
   reading half a list.
2. Owner module (R1): Oracle (agent loop), Hephaestus (its tools), shared function in Hestia-Shared.
3. Configuration: existing Themis setting, new default 0 = automatic; no switch, no env.
4. Push or poll: none (runs inside the turn).
5. Who confirms: nothing changes for the owner; `result_more` only reads a copy kept for the turn.
6. WebUI and Telegram: unchanged (the thinking stream shows the shaped result).
7. Stop, correct, undo: a number in the setting forces the old fixed cap.
8. Docs: `hestia-shared.md`, `hestia-oracle.md`, `hestia-hephaestus.md`, root CHANGELOG.
9. Texts: hidden notes for the model in English; setting help in English with its Italian catalog entry.

## 5. Acceptance criteria
- A module answering 40 events at 16k: the model reads a table with «showing N of 40», error items kept, and can
  read the rest with `result_more`.
- A dict result is compact JSON, never a Python repr.
- Setting 0 → budget follows the window; a number forces it.
- A Forge test run with a failure in the middle: the failure line and the final summary both reach the model.
