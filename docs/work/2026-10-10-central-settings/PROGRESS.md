# PROGRESS — central settings

Spec: `SPEC.md` v2.1 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current state studied
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] Store decided: new module Themis + Archive storage (v1.1)
- [x] User approves SPEC v2.1 (2026-10-10, "ora sai su cosa lavorare"); Hermes multi-client delivery moved to thread "Notifiche nella WebUI"
- [x] P1 `hestia_common.settings_client` (setting/preset/SettingsClient, declare_log_level, router effective|reload)
- [x] P1 Hestia-Themis service (port 19016, compose global+rpi, Hub registration, MCP tools, proposals → Hermes) + Archive `/api/settings-store/*` (3 tables); swagger, docs, CI matrix; logic verified with a mocked-Hub smoke script (pytest not run, user rule)
- [ ] P2 Oracle models + preset; Forge engine (migrate `settings.json`); `LOG_LEVEL`
- [ ] P3 WebUI Impostazioni: personal/system, search, module status cards, `hx-setting`
- [ ] P4 Unified chat settings (Telegram + WebUI), profile → session copy, chat quick menu
- [ ] P5 Themis MCP tools (Hestia-MCP) + proposals confirmed via Hermes; Athena `setting` proposals
- [ ] P6 Migrate remaining modules' tunable env vars (one module per step)
- [ ] Docs: hestia-<name>.md, swagger, .env.example notes, docs/ARCHITECTURE.md rule
