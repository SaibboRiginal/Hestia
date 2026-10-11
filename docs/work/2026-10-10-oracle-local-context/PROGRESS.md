# PROGRESS — Oracle local context

Spec: `SPEC.md` v1.4 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current Oracle context handling studied
- [x] Dossier created (SPEC v1.0 → v1.3 aligned with central settings v2.0)
- [x] Haiku thread's provider layer on main (0922927): `agents/providers/`, `agents/llm_config.py`
- [x] User: "finish everything, then we test" (2026-10-11) → defaults chosen (SPEC §8)
- [x] A `num_ctx` + `keep_alive` on every Ollama call from settings (`oracle_settings.ollama_request_options`); `TokenCounter` window/threshold from settings; startup `ollama_context_config` + `/api/ps` check
- [x] B `core/services/llm_stats.py` (Ollama / OpenAI-compatible stats, per use-case label) + `runtime` in `/api/chat/context`; swagger
- [x] C sorted tools, ACTION INTENT moved to dynamic part, stable history window (`ContextBuilder.stable_window`), tool-result stubs (`_stub_old_tool_results`)
- [x] D `agents/providers/openai_compat.py` (chat, tools, stream, vision, embeddings, list_models), registered; `ORACLE_OPENAI_BASE_URL`/`ORACLE_OPENAI_API_KEY` in `load_llm_config()`
- [x] Settings declared in Themis (group Contesto)
- [x] Tests written: `Hestia-Oracle/tests/test_local_context.py`, TokenCounter tests moved to the setting (not run here, user rule; code smoke-checked with mocks)
- [x] Docs: `Hestia-Oracle/hestia-oracle.md` (section "Local models"), compose comments, swagger
- [ ] User test on the real stack: check `event=ollama_context_config`, `event=llm_call_stats` cache_hit_pct over a multi-turn chat, `/api/chat/context` → `runtime`; optionally llama-server via `ORACLE_OPENAI_BASE_URL`
- [ ] Later (optional): move Ollama/Gemini into provider classes; Anthropic usage into `llm_stats`
