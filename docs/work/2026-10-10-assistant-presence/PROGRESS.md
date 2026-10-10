# PROGRESS — assistant presence

Spec: `SPEC.md` v2.2 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current state studied (Oracle `/api/activity`, Athena idle gate)
- [x] Decision: deep sleep from agenda window **and** inactivity
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] SPEC v2.0: signals → combinable states → effects, extensible states
- [x] SPEC v2.1: core/optional tiers, default values
- [x] SPEC v2.2: aligned with Themis + Hermes global notifications
- [ ] User approves SPEC
- [x] Wait for central settings foundation (P1–P5 on main, 2026-10-10)
- [ ] Archive `presence_signals` / `presence_snapshot` / history tables and API
- [ ] Chronos presence engine (signals, rule evaluation, effects), built-in states, `assistant.sleep` window, Hermes event; swagger
- [ ] `hestia_common.presence_client` with fallback
- [ ] Pings: Oracle chat, Telegram, WebUI (debounced)
- [ ] Activity reporting + consumers via effects: Athena, Oracle (context line, style, notice, tool), Forge, Metis, Hermes
- [ ] Clients: Telegram `/stato` `/nondisturbare`, WebUI badge + state editor
- [ ] Settings registration (§4.5) — done together with the Chronos step
- [ ] Docs: hestia-chronos.md ("Who plans what"), hestia-oracle/athena/hephaestus/metis.md, swagger, .env.example
