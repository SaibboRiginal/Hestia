# PROGRESS — Oracle local context

Spec: `SPEC.md` v1.0 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current Oracle context handling studied
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [ ] User approves SPEC (open points §7)
- [ ] A `num_ctx` + `keep_alive` on every Ollama call (generate, chat, tools, stream, vision); startup log; `.env.example` + host Ollama env notes
- [ ] B `ollama_call_stats` parsing + log per agent; aggregates in `/api/chat/context`; swagger
- [ ] C prompt audit (static prefix byte-stable, sorted tools); append-only history between compactions; tool-result stubs in agent loop; classifier/extractor model option documented
- [ ] D `openai` provider in `UniversalAgent` (chat, tools, stream) — agree ownership with the Haiku thread; docs for llama-server / vLLM
- [ ] Settings declared in the central registry (when it exists)
- [ ] Tests (unit/format, mocked HTTP) + docs `Hestia-Oracle/hestia-oracle.md`
