# SPEC — Prompt uguali in ogni situazione

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Migliorare i prompt per ogni situazione», Marko 2026-11-09 and 2026-11-12) |
| **Status** | Implemented and merged (PR #99); real run by Marko pending. Point 6 (classifier) waits for his answer |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
Follows `docs/work/2026-11-06-hestia-viva` and `docs/work/2026-11-12-identita-e-proattivita` (who the assistant
is: name, she/he, owner, style). This dossier is about how the prompt is put together, not about her character.

## 1. Today (verified on main 8ec10ee)

- The persona carried the Telegram HTML rules for every client; the WebUI draws Markdown, a spoken turn wants neither.
- The style contract was inside the persona and added again by the small talk shortcut and by the agent loop.
- Mode `quick` (Rapida) was a separate path: one call, no tools, no memories, a reduced prompt.
- The small talk shortcut of `auto` got no preferences or memories: she did not know who she was talking to.
- Hidden text was half Italian, half English (`ACTION INTENT`, `CONVERSATION HISTORY`, «Now provide your final answer»).
- `ACTION INTENT` said «no tool → explain it cannot be performed»; persona rule 8 said «never say I cannot, propose
  developing it». Three labels for the same client instructions.
- Modules that write to the owner (Hermes, Argus, Athena recap, Chronos plan, Plutus, setup hello) each wrote their
  own «Sei Hestia…» and called `/api/llm/generate`, which has no persona: tone, name and she/he did not apply.

## 2. Marko's decisions (2026-11-12)

1. Oracle does not know the client: the answer format is an instruction each client sends.
2. Modes: Rapida = everything, no thinking · Pensata = model thinking on · CoT = chain run by an orchestrator that
   accepts steering messages. Rapida is never a poorer prompt.
3. Every hidden text in English; the model always answers in the language of his last message.
4. No few-shot examples in the classifier («come fanno i big?»). Proposed to him: no LLM classifier at all, tools
   narrowed without a model call plus a «search tools» tool. **Not decided, not in this version.**
5. Module texts all pass through Oracle, so the voice is applied in Oracle.

## 3. Scope and design

### A — One composer (Oracle)
- `prompt_config.system_identity()` = persona + style contract + language rule. It is the system prompt of every
  chain that speaks to the owner (`agent_factory`), of the external agent, of the assistant inside another AI
  (`assistant_profile`) and of module texts (`voice`, see D). No path adds these blocks again.
- Persona = only who she is. The operating rules became `tool_rules` and are included by the two agent-loop
  preambles (and the external agent), so they are paid only when the turn has tools.
- `language_rule`: instructions are English, the answer follows the owner's latest message.
- One label per thing: `OWNER PREFERENCES`, `CONVERSATION HISTORY`, `CLIENT INSTRUCTIONS`, `USER:`.
- `ACTION INTENT` now points to tool rule 3 (propose developing it) instead of contradicting it.
- Removed: `formatter_html_rule`, the `__experimental` formatter variants (never refined, Telegram-only).

### B — Format from the client
- Oracle: no format anywhere (persona, formatter). `/api/format` uses the caller's `client_instructions`.
- Telegram: `telegram.chat.client_instructions` default = Telegram HTML rules (it already sent them).
- WebUI: `WebUI:OracleClientInstructions` = Markdown (the chat renders it with `marked`).
- MCP command page: plain text. Spoken turn: `voice_turn_contract`, added when the client says `spoken`.

### C — Modes
- `quick` no longer short-circuits: same init, classify, tools and prompt as `auto`; `_think_level` is off.
  `auto`/`thinking` → on, `cot` → deep + CoT instruction (unchanged). The small talk shortcut stays for `quick` and
  `auto` and now receives the owner's preferences (same source as the agent loop, 10 at most).
- CoT with an orchestrator that takes steering messages: with the thread «Rendere ogni modulo un agente di Oracle»
  (its SPEC already has the orchestrator); not in this version.

### D — Module texts in the assistant's voice
- `POST /api/llm/generate` takes `voice: bool` (default false). True = the text is for the owner: system prompt
  `system_identity()`, the prompt is prefixed with `module_voice_instruction`. False = a plain tool (extraction,
  scoring, review) without persona, as before.
- Callers with `voice: true`: Hermes (`narrate`: entity notification, batch, «frase»), Argus alerts and recovery,
  Athena recap, Chronos weekly plan, Plutus monthly summary, Hephaestus setup hello. Their prompts now hold only
  what to say, the data and the format they deliver; no «Sei Hestia…».
- Language of these texts: still Italian, written in each request (there is no owner message to follow and no
  personal language setting). Flagged to Marko.

### E — Tests
- `Hestia-Oracle/tests/test_prompt_composer.py`: each block once and no client format; every hidden text English
  and without a fixed name; language rule; agent loop (tool rules once, no style, no opposite orders); small talk
  knows the owner; the four modes get the same prompt and differ only in thinking; external agent and other AI;
  formatter without format; `voice` reaches the chain.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job: the assistant behaves the same whatever mode, client or module is involved.
2. Owner module: Oracle (prompts); clients own their format; modules own their data.
3. Configuration: no new setting.
4. Push/poll: n/a. 5. Confirms: n/a. 6. UI: none. 7. Undo: n/a.
8. Docs: hestia-oracle.md, hestia-hermes.md, hestia-telegram.md, hestia-webui.md, swagger.yml, ARCHITECTURE
   (rule 13), REGOLE-DI-MARKO (R6), CLAUDE.md, root CHANGELOG.

## 5. Acceptance criteria
- `system_identity()` holds persona, style and language once, and no word about Telegram, HTML or Markdown.
- A turn in Rapida calls the same loop as auto with thinking off; Pensata on; CoT deep.
- Small talk prompt carries `OWNER PREFERENCES`.
- No prompt in `_DEFAULT_PROMPTS` has Italian instructions or the fixed name.
- `/api/llm/generate {voice: true}` runs with the persona as system prompt.

## 6. Open (asked to Marko in chat)
- Classifier: remove it (his point 6).
- Tool descriptions of the modules (about 250) are still Italian: they are hidden text too.
- Language of notifications and recaps: a personal setting, or follow the last chat language.
- Internal prompts of Athena, Chronos agenda parser, Scout, Metis, Forge (not spoken to the owner) are still Italian.
