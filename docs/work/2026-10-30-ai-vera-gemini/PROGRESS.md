# Progress — Test with the real AI (Gemini)

- [x] Find the real-model suite (`Hestia-Oracle/tests/test_live_*.py`, `llm_live`): still there, Ollama only
- [x] `tests/live_llm.py`: Ollama or Gemini, model list, pacing, quota rotation; conftest drops ORACLE_KEY_* without --run-live
- [x] Bench: Gemini on every chain but embedding, wait for oracle.chains, accept ORACLE_KEY_GEMINI
- [x] Chat probes on the bench (personality, quick/auto/thinking/cot, agenda, memory, weather, fitness, finance, people, deadlines, wardrobe, routines, settings, voice)
- [x] Fixes 1–10 of SPEC §3 with regression tests
- [x] Docs: hestia-oracle, hestia-themis, hestia-chronos, hestia-echo, swagger, TESTING (root + Oracle), root CHANGELOG
- [x] Full llm_live run on Gemini (2026-10-30, models gemini-flash-lite-latest → 3.1-flash-lite → gemma-4 → 2.5-flash):
      54 passed, 1 skipped (Ollama model list), 3 failed = stale tests, not the model (ChatClassifier takes one agent
      now, its `ask(…, thinking=False)` broke the mocks' side effect, tool_log has no `duration_ms`); fixed, rerun green
- [x] precheck 0 failed, PR #53 green and merged

## Round 2 (SPEC v1.1)
- [x] Bench chain = 6 Gemini models (3.6-flash, 3.5-flash, 3-flash-preview, 3.5-flash-lite, flash-lite-latest, 3.1-flash-lite)
- [x] Memory scenarios (greeting, passing state, durable fact twice, advice, job, reminder, birthday, recall, forget)
- [x] Module scenarios (finance, wardrobe, fitness, deadlines, home, calendar, poem, maths, identity, thinking mode)
- [x] MCP doors: external (token, 18 tools, all reads ok) and internal (252 tools, all reads ok but Garmin not linked)
- [x] Fixes 11–21 with regression tests; docs (oracle, shared, demeter, hercules)
- [x] Recheck on the bench after the fixes, precheck, PR #54 green and merged
- [ ] Voice: needs huggingface.co allowed in the cloud environment (asked Marko)

## Round 3 (SPEC v1.2) — small models
- [x] Chain Gemma 4 → Flash-Lite on the bench; fallback on quota verified
- [x] Fix 22 (tools of the turn's domains) + fix 23 (no memory copy of a module write), tests
- [x] 12 cases of Marko's own use with Gemma
- [x] Marko chose fix 22 for every model; PR #55 merged

## Safeguards (SPEC v1.3)
- [x] turn_guards.py + tests (552 green)
- [x] Verification round 4 with the small model (10 cases), fixes 29–31 (555 green), pizza cases re-run ok
- [x] PR #62 merged (e7522b4)
