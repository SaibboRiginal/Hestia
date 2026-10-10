# PROGRESS — Oracle local context

Spec: `SPEC.md` v1.3 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current Oracle context handling studied
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [ ] User approves SPEC (open points §7)
- [x] Haiku thread's provider layer on main (0922927): `agents/providers/` (LLMProvider, PROVIDER_TYPES, get_provider), `agents/llm_config.py` load_llm_config(). Ollama/Gemini NOT moved yet, `openai` type not built → both are ours. Thinking is a level (False/True/"deep"). New tunables via `settings_client.setting(...)`, never env.
- [ ] A move Ollama calls into an `ollama` provider class (register in PROVIDER_TYPES, endpoint in load_llm_config()); `ollama` provider `CONFIG_FIELDS` num_ctx/keep_alive sent on every Ollama call (generate, chat, tools, stream, vision); as `oracle.provider.ollama.*` Themis settings (no new env var); startup log; host Ollama env notes in docs
- [ ] B `ollama_call_stats` parsing + log per agent; aggregates in `/api/chat/context`; swagger
- [ ] C prompt audit (static prefix byte-stable, sorted tools); append-only history between compactions; tool-result stubs in agent loop; classifier/extractor model option documented
- [ ] D `openai` provider (endpoint `ORACLE_OPENAI_BASE_URL`) for llama-server/vLLM (type class from the Haiku thread's layer), usage→stats mapping; docs for llama-server / vLLM
- [ ] Settings declared in the central registry (when it exists)
- [ ] Tests (unit/format, mocked HTTP) + docs `Hestia-Oracle/hestia-oracle.md`
