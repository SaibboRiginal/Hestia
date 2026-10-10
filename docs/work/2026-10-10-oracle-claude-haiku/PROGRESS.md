# PROGRESS — Claude Haiku in Oracle

Spec: `SPEC.md` v1.4 · resume from the first unchecked box.

- [x] Options, costs and terms researched; user chose both API key and subscription (thread 2026-10-10)
- [x] Dossier created (code reading done)
- [x] Hold lifted (settings P1-P5 on main); plan rebased (v1.3)
- [x] User confirmed the plan, no preset (2026-10-10 15:10)
- [x] `agents/providers/` base + registry, `agents/llm_config.py` `load_llm_config()`, `UniversalAgent` dispatch
- [x] `anthropic` provider (tools, thinking per mode, caching, attachments, stream)
- [x] `claude_cli` provider (subscription, text tool calls)
- [x] Thinking level from chat mode (`oracle_engine`); factory: Claude thinking on unless setting "Mai"
- [x] Provider enum (`oracle_settings.PROVIDERS`) + `/api/llm/models` for both types
- [x] Forge: `ORACLE_ANTHROPIC_API_KEY` stripped from the `claude` env
- [x] requirements, `.env.example`, `hestia-oracle.md`, swagger enum, root CHANGELOG
- [x] Unit tests `tests/test_claude_providers.py` — written, not run (user rule); smoke-checked with fake CLI/client
- [ ] User test: rebuild Oracle, set key/token, pick the provider in Impostazioni → Modelli, chat in each mode
- [ ] (other thread) move ollama/gemini into `agents/providers`, add `openai` type
