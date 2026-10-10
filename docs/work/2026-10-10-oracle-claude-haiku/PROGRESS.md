# PROGRESS — Claude Haiku in Oracle

Spec: `SPEC.md` v1.0 · resume from the first unchecked box.

- [x] Options, costs and terms researched; user chose both API key and subscription (thread 2026-10-10)
- [x] Dossier created (code reading done)
- [ ] **On hold** until the user finishes the central-settings work (user, 2026-10-10 09:49); no code written yet
- [ ] Provider layer: base + ollama + gemini moved, `load_llm_config()`, `UniversalAgent` dispatch
- [ ] `anthropic` provider (tools, thinking per mode, caching, attachments, stream)
- [ ] `openai` basic provider type
- [ ] `claude_cli` provider (subscription)
- [ ] Thinking level from chat mode (`oracle_engine`)
- [ ] Forge: strip Anthropic API keys from the `claude` env
- [ ] requirements, `.env.example`, compose comments, `hestia-oracle.md`, root CHANGELOG
- [ ] Unit tests for providers (mocked) — written, not run
