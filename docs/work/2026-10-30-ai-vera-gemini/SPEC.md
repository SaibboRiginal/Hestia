# SPEC — Test with the real AI (Gemini) on the cloud bench

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via external chat (Marko, 2026-10-30: «messo chiave e abilitato l'host… i test non deterministici dell'AI ci sono ancora?») |
| **Status** | Implemented (round 2: behaviour) |

## 1. Today (verified in code)
- The non-deterministic real-model suite still exists: `Hestia-Oracle/tests/test_live_*.py` (4 files, ~58 tests,
  marker `llm_live`, skipped unless `--run-live`). It only knew local Ollama, so it never ran on the cloud bench.
- `tools/cloud_test.py` switched only 3 Oracle use cases to Gemini, and its Themis write raced Oracle's settings
  registration (404): on the bench the brain stayed the fake LLM.
- The Gemini key is in the session as `ORACLE_KEY_GEMINI` (Oracle's own name).

## 2. Goal
Run Hestia with a real model end to end (personality, chat modes, MCP tools, settings, routines, memory) and fix
what breaks; make the live suite runnable on Gemini.

## 3. Scope and design
- Live suite: `tests/live_llm.py` = one helper (provider Ollama or Gemini, model list, pacing, per-day quota → next
  model). Without `--run-live` the conftest drops `ORACLE_KEY_*` so deterministic tests never see a real key.
- Bench: every chain except `embedding` becomes a 4-model Gemini chain (four free-tier quotas); waits for
  `oracle.chains` in Themis; accepts `ORACLE_KEY_GEMINI` or `GEMINI_API_KEY`.
- Fixes found with the real model (each with a regression test):
  1. Gemini tool calling: schemas go as `parameters_json_schema` (one schema the OpenAPI subset refused —
     `contentMediaType`, array without `items` — failed every tool call); Oracle keeps each tool's own JSON Schema.
  2. Default Gemini models by alias (`gemini-flash-latest`, `gemini-flash-lite-latest`): 2.0-flash and
     2.5-flash-lite are no longer served to new keys.
  3. Chronos `POST /api/calendar/events` takes the flat tool shape (every assistant call was a 422).
  4. A write that failed is never told as done (note in the next prompt).
  5. A whole answer written as `memory.search(query="…")` is run as a tool call, not shown.
  6. The same write with the same title runs once per turn (three identical routines).
  7. A 200 answer `{"error": …}` is not «Fatto» and not in «Ho fatto».
  8. Themis and Echo own their tool domains (`settings`, `voice`): the chat never had those tools.
  9. Themis: unknown key in a proposal → hint with `settings_search` and close keys; the card shows option
     labels («Caldo → Diretto»); a pending proposal is «Serve la tua conferma», not «Fatto».
  10. Persona: no opening greeting when the user does not greet.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: the assistant does what is asked and says the truth about it.
2. Owner module (R1): Oracle (loop, provider), Chronos (events), Themis (proposals), Echo (caps only).
3. Configuration: no new setting; chains stay in Themis (`oracle.chains`), defaults updated.
4. Push or poll: unchanged.
5. Who confirms: unchanged (settings proposals confirmed by the user).
6. WebUI / Telegram: same packets; a proposal now shows «Serve la tua conferma».
7. Stop, correct, undo: unchanged.
8. Docs: hestia-oracle.md, hestia-themis.md, hestia-chronos.md, hestia-echo.md, swagger, TESTING.md (root and
   Oracle), root CHANGELOG.

## 5. Acceptance criteria
- `pytest Hestia-Oracle/tests -m llm_live --run-live` runs on Gemini with only `ORACLE_KEY_GEMINI` set.
- On the bench with Gemini: chat answers in every mode, calls tools (agenda, memory, weather, fitness, finance,
  people, deadlines, wardrobe, routines, settings, voice), proposes a setting with a confirm card, never claims a
  failed action, never repeats a write.
- Unit/api/format tests green; precheck 0 failed.

## 6. Round 2 — behaviour of the whole assistant (v1.1)
Marko (2026-10-30): test that the AI answers sensibly with every module, does not make a mess, understands when to
save memories and does not save rubbish, and that the system/orchestrator prompts work. Done on the bench with real
conversations (memory, 11 modules, modes, MCP doors). Found and fixed, each with a regression test:
11. A fact said twice or in other words became 2–3 memories (chat tool + background extractor): `same_fact` dedupe in
    both paths; the extractor stays off when the chat used its memory tools and sees the turn's actions (a routine,
    a birthday are not saved again as memories); «ricordami di…» = reminder, a passing state is not a memory.
12. «Dimentica dove lavoro» claimed «rimosso» with nothing removed: new tool `memory.forget`; `memory.search`
    matches word forms (lavoro/lavora).
13. Quick chat (no tools) answered «Ho registrato la stanchezza, riduco gli impegni»: rule + one retry when the
    answer claims an action (`_CLAIMED_ACTION`).
14. Advice asked («mi consigli una pizza?») registered a dinner: analyst rule 10 (write tools only when asked).
15. «Riproverò a breve» / promises nobody scheduled: rule 11.
16. `memory:save`, `memory_save` → «Unknown tool»: near-miss names resolve to the one manifest tool.
17. The same failing call ran 4 times: an identical failed call is not repeated.
18. An answer `<call:cibo_oggi></call:cibo_oggi>` reached the user: parsed as a tool call.
19. Reads shown as «Fatto» (`cibo_dieta` without arguments, `wardrobe_suggest`): `unchanged` result flag, `suggest`
    is a read word.
20. MCP: a POST tool called with no arguments sent no body → 422 (Case disponibili); `scout_stats` always failed
    (limit 100 > 50).
21. «Come sto andando con l'allenamento?» ignored the run logged a minute before: the fitness summary lists the
    week's activities.
Not testable in this cloud session: voice (huggingface.co blocked by the environment network), weather
(open-meteo blocked), Google Calendar and Telegram (need Marko's accounts).

## 7. Round 3 — small models (v1.2)
Marko (2026-10-30): he may run a local 9B model; test again with weaker models, models moving on when one is out of
quota, with cases like his own use. Chain on the bench: Gemma 4 26B-A4B → Gemma 4 31B → three Flash-Lite.
- Fallback between models verified: per-minute and per-day 429 move to the next step; all out → «no model» (503).
22. Every turn sent every tool of every module (~250 tools, ~30k tokens): Gemma's per-minute token quota refused it
    and a local model with `num_ctx` 8192 would lose the start of the prompt (rules, tools). A turn the classifier is
    sure about now gets only its domains' tools + `_ALWAYS_TOOLS` (53 tools, ~9.5k tokens for the agenda).
    Marko asked to choose (decision card): recommended = for every model.
23. «Mia mamma si chiama Laura» → person card and also a memory: when a module write stored it, no memory unless the
    user says «ricorda».
12 cases of his own use with Gemma (agenda, gym sets, expenses, houses, low mood, reminder in 2 hours, mother,
recall, shorter answers, new command, «spegni tutto», thanks): right tool and honest answers in all of them.
Open: the agenda prompt is still ~9.5k tokens, over the 8192 default context of Ollama (raise `num_ctx` to 16384 on
the PC, or slim the agenda tools).

