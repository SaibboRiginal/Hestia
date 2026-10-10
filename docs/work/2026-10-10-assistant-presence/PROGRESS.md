# PROGRESS — assistant presence

Spec: `SPEC.md` v2.2 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current state studied (Oracle `/api/activity`, Athena idle gate)
- [x] Decision: deep sleep from agenda window **and** inactivity
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] SPEC v2.0: signals → combinable states → effects, extensible states
- [x] SPEC v2.1: core/optional tiers, default values
- [x] SPEC v2.2: aligned with Themis + Hermes global notifications
- [x] User approves SPEC (2026-10-10, "ora puoi implementare")
- [x] Wait for central settings foundation (P1–P5 on main, 2026-10-10)
- [x] Archive `presence_signals` / `presence_snapshot` / `presence_changes` tables and `/api/presence-store` API
- [x] Chronos presence engine (`services/presence.py`, settings `core/presence_settings.py`), `assistant.sleep` window, agenda tick hook, Hermes event, MCP tools `stato`/`nondisturbare`/`disturbami`, tests `tests/test_presence.py` (smoke-checked, pytest not run)
- [x] Swagger for Chronos `/api/presence*`, Archive `/api/presence-store*`, Hermes `release-held`, WebUI `/api/webui/presence*`
- [x] `hestia_common.presence_client` with fallback
- [x] Pings: Oracle chat, Telegram, WebUI (debounced)
- [x] Activity reporting + consumers via effects: Athena, Oracle (context line, style, notice), Forge, Metis, Argus (degraded count), Hermes (hold + digest)
- [x] Clients: Telegram `/stato` `/nondisturbare` `/disturbami` (MCP), WebUI badge + popover. State editor = advanced JSON object setting in Impostazioni (a friendlier editor is a possible follow-up)
- [x] Settings registration (§4.7) — `SettingsClient("chronos")`
- [x] Docs: hestia-chronos/archive/shared/oracle/telegram/webui/athena/hephaestus/metis/argus/hermes.md, docs/ARCHITECTURE.md, swagger (no env change: everything is a Themis setting)
- [ ] User test: .NET WebUI build + real run (`up-all.bat --build`); pytest suites not run here (smoke-checked only)
