# PROGRESS — assistant presence

Spec: `SPEC.md` v1.0 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current state studied (Oracle `/api/activity`, Athena idle gate)
- [x] Decision: deep sleep from agenda window **and** inactivity
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [ ] User approves SPEC (open points §6)
- [ ] **Blocked**: wait until central settings (`2026-10-10-central-settings`) is finished — user's rule
- [ ] Archive `assistant_state` + history tables and API
- [ ] Chronos presence state machine (worker tick + ping), `assistant.sleep` window, Hermes event; swagger
- [ ] `hestia_common.presence_client` with fallback
- [ ] Pings: Oracle chat, Telegram, WebUI (debounced)
- [ ] Consumers: Athena, Oracle context line + `assistant_state` tool, Forge, Metis
- [ ] Clients: Telegram `/stato` `/nondisturbare`, WebUI badge
- [ ] Settings registration (§4.5) — done together with the Chronos step
- [ ] Docs: hestia-chronos.md ("Who plans what"), hestia-oracle/athena/hephaestus/metis.md, swagger, .env.example
