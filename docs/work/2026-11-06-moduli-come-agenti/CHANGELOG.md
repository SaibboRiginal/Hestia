# CHANGELOG — Ogni modulo un agente di Oracle

- v1.0 — 2026-11-06 — first draft — Marko's idea in project chat — user via project chat
- v2.0 — 2026-11-06 — operating modes classica/agenti/agenti_in_serie (classica default, classifier kept for it); chats per client explained — Marko wants to go back and a serial mode for local — user via project thread
- v2.1 — 2026-11-06 — table: how the operating modes fit chat modes, brain mode, chains, guards, goals, voice and settings — Marko asked if all work together — user via project thread
- v3.0 — 2026-11-16 — `agenti_in_serie` merged into `agenti`: the LLM bus (PR #111) decides serial vs parallel; `oracle.agenti.max_paralleli` dropped; «bacheca del turno» added — Marko asked for a bus because his PC runs one model at a time — user via project thread (bus thread)
- v3.1 — 2026-11-17 — English names (oracle.operating_mode classic/agents, oracle.agents.*, agent.<module>, bus oracle.bus.local_workers) — PR #113 rule and bus rename — bus thread
- v3.2 — 2026-11-17 — approved; operating mode is global (not per client); agents without ask_user; frame label = module title — implementation details — user via project thread
