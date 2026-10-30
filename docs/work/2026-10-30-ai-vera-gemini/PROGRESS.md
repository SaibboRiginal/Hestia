# Progress — Test with the real AI (Gemini)

- [x] Find the real-model suite (`Hestia-Oracle/tests/test_live_*.py`, `llm_live`): still there, Ollama only
- [x] `tests/live_llm.py`: Ollama or Gemini, model list, pacing, quota rotation; conftest drops ORACLE_KEY_* without --run-live
- [x] Bench: Gemini on every chain but embedding, wait for oracle.chains, accept ORACLE_KEY_GEMINI
- [x] Chat probes on the bench (personality, quick/auto/thinking/cot, agenda, memory, weather, fitness, finance, people, deadlines, wardrobe, routines, settings, voice)
- [x] Fixes 1–10 of SPEC §3 with regression tests
- [x] Docs: hestia-oracle, hestia-themis, hestia-chronos, hestia-echo, swagger, TESTING (root + Oracle), root CHANGELOG
- [ ] Full llm_live run on Gemini: results in this file
- [ ] precheck 0 failed, PR green and merged
