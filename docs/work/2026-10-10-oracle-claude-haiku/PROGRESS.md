# PROGRESS — Claude Haiku in Oracle

Spec: `SPEC.md` v1.3 · resume from the first unchecked box.

- [x] Options, costs and terms researched; user chose both API key and subscription (thread 2026-10-10)
- [x] Dossier created (code reading done)
- [x] Hold lifted (settings P1-P5 on main); plan rebased (v1.3)
- [ ] User confirms the v1.3 plan
- [ ] Provider layer: base + ollama + gemini moved, `load_llm_config()`, `UniversalAgent` dispatch
- [ ] `anthropic` provider (tools, thinking per mode, caching, attachments, stream)
- [ ] `openai` basic provider type
- [ ] `claude_cli` provider (subscription)
- [ ] Thinking level from chat mode (`oracle_engine`)
- [ ] Forge: strip Anthropic API keys from the `claude` env
- [ ] requirements, `.env.example`, compose comments, `hestia-oracle.md`, root CHANGELOG
- [ ] Unit tests for providers (mocked) — written, not run
