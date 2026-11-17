# PROGRESS — Ogni modulo un agente di Oracle

- [x] Read Oracle code (classifier, agent loop, chains, module registry) and the Verity thread
- [x] SPEC v1.0 draft
- [x] SPEC v2.0 operating modes
- [x] SPEC v3.0 bus LLM (one agent mode, bacheca del turno)
- [x] Marko approves the SPEC (2026-11-17 11:00 «puoi iniziare a lavorarci»)
- [x] A1 agent registry from Hub (when_to_use/manual/tools) + use cases `agente.<modulo>`
- [x] A2 `when_to_use`/`manual` for core services missing them
- [x] A3 agent tool + agent loop (prompt, history, guards on owner's words, depth 1)
- [x] A0 setting oracle.funzionamento, classica = today
- [x] A4 main loop without classifier (agents mode), direct answer, turn board, contextvars copy
- [x] A5 `agent` frame live (worker thread + queue), swagger + docs
- [x] A6 WebUI reasoning block + Telegram status line (ng build ok; .NET not built in cloud)
- [ ] A7 tests, precheck, PR, CI green, merge

## Checkpoint 2026-11-17 (WIP started too early, stopped at Marko's request; resumed after his go)
Done in code on this branch (not merged, no PR):
- `oracle_settings.py`: `oracle.operating_mode` (classic|agents, default classic), `oracle.agents.max_per_turn|history|steps`, `operating_mode()`. Italian labels not yet in `locales/it/messages.json`.
- `agent_loop.py`: `ToolDefinition.service` and `.direct`; direct answer when the turn's only call is a `direct` tool returning `{answer}`.
- `oracle_engine._build_domain_tools`: tools carry `service` (hub commands, `<domain>.search` first owner).
Not started: agent registry/use cases, agent loop + board, engine «agents» branch, live `agent` frame, clients, docs, tests.
Nothing changes behaviour while `oracle.operating_mode = classic`.
