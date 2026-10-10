# PROGRESS — Oracle local context

Spec: `SPEC.md` v1.2 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current Oracle context handling studied
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [ ] User approves SPEC (open points §7)
- [ ] Wait for the Haiku thread's provider-layer refactor + `load_llm_config()` 
- [ ] A `ollama` provider `CONFIG_FIELDS` num_ctx/keep_alive sent on every Ollama call (generate, chat, tools, stream, vision); declared as Themis settings (no new env var); startup log; host Ollama env notes in docs
- [ ] B `ollama_call_stats` parsing + log per agent; aggregates in `/api/chat/context`; swagger
- [ ] C prompt audit (static prefix byte-stable, sorted tools); append-only history between compactions; tool-result stubs in agent loop; classifier/extractor model option documented
- [ ] D `openai` provider type instance for llama-server/vLLM (type class from the Haiku thread's layer), usage→stats mapping; docs for llama-server / vLLM
- [ ] Settings declared in the central registry (when it exists)
- [ ] Tests (unit/format, mocked HTTP) + docs `Hestia-Oracle/hestia-oracle.md`
