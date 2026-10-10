# CHANGELOG — Claude Haiku in Oracle

- v1.0 — 2026-10-10 — initial spec: anthropic (API key) + claude_cli (subscription) providers on the §3.9 provider layer — user asked for both — user via project thread
- v1.1 — 2026-10-10 — configuration via Themis settings only, no legacy env compat, no new tunable env vars — central-settings SPEC v1.2 decision — user via settings thread
- v1.2 — 2026-10-10 — no provider instances: providers = implemented types with endpoint/key from env; load_llm_config builds per-type config + use-case mapping — central-settings SPEC v2.0 — user via settings thread
- v1.3 — 2026-10-10 — rebased on settings P1-P5: PROVIDERS enum values + list_models, oracle.models.<uc>.* keys, load_llm_config for infra env only — settings foundation landed on main — coordinator relay
- v1.4 — 2026-10-10 — implemented; ollama/gemini move and openai type left to the local-context thread; Forge strips only ORACLE_ANTHROPIC_API_KEY; no preset — user chose "Sì, senza preset"; keep the diff focused — user via project thread
