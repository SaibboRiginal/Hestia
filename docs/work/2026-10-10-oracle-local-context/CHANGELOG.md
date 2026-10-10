# CHANGELOG (spec) — Oracle local context

- v1.0 — 2026-10-10 — spec created after brainstorming (found: `num_ctx`/`keep_alive` never sent to Ollama;
  phases A real context + warm model, B cache telemetry, C cache-friendly prompts + tool-result stubs,
  D optional OpenAI-compatible provider for llama-server/vLLM shared with the Haiku thread) — source: user
  via external chat (Claude Code cloud session).
- v1.1 — 2026-10-10 — phases A and D aligned with central-settings §3.9 (num_ctx/keep_alive are `ollama` provider config fields; llama-server/vLLM = `openai` provider instances; env read only by `load_llm_config()`; provider layer owned by the Haiku thread) — refinement — source: channel session relay of the settings thread's schema.
