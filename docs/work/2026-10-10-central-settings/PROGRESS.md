# PROGRESS — central settings

Spec: `SPEC.md` v2.1 · resume from the first unchecked box.

- [x] Brainstorming with the user (thread 2026-10-10), current state studied
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] Store decided: new module Themis + Archive storage (v1.1)
- [x] User approves SPEC v2.1 (2026-10-10, "ora sai su cosa lavorare"); Hermes multi-client delivery moved to thread "Notifiche nella WebUI"
- [x] P1 `hestia_common.settings_client` (setting/preset/SettingsClient, declare_log_level, router effective|reload)
- [x] P1 Hestia-Themis service (port 19016, compose global+rpi, Hub registration, MCP tools, proposals → Hermes) + Archive `/api/settings-store/*` (3 tables); swagger, docs, CI matrix; logic verified with a mocked-Hub smoke script (pytest not run, user rule)
- [x] P2 Oracle models (`oracle_settings.py`: 4 use cases × provider/model/fallback/thinking, presets
  Economico/Bilanciato/Qualità, live via `AgentFactory.reconfigure`, `GET /api/llm/models`); MODEL_USECASE_* env
  removed; Forge engine + permission modes (`forge_settings.py`, live; `settings.json` keeps only the Claude
  schedule; MCP tools `forge_set_engine`/`forge_set_mode` removed: the assistant proposes via Themis);
  `<owner>.log.level` in Oracle + Hephaestus. Import-smoked (pytest not run). Note: old engine/mode choices in
  `settings.json` are not migrated (no legacy, user rule) → defaults local / auto / ask.
- [x] P3 WebUI Impostazioni → Sistema (`features/settings/`: api, store, `hx-setting`, `hx-setting-control`,
  system panel with cards, search, presets, row/column tables, history/undo, proposals banner) + .NET
  `CentralSettingsController` (proxy to Themis via Hub) + Themis `GET /api/settings/key/{key}/options` and
  proposal labels + `row`/`column` hints in the shared client. `ng build` clean; checked with Playwright on a
  mocked API (desktop light, phone dark). .NET not built here (no SDK): Marko builds it.
- [x] P4 Personal chat settings: Oracle declares `oracle.chat.tone` / `oracle.chat.instructions` (scope user) and
  applies them itself (`client` field in chat/format requests, `SettingsClient.user_values`); WebUI Personali =
  profile, chat ⚙ quick menu = session; Telegram /settings tone + instructions = client layer `telegram`
  (`personal_settings.py`). Presentation options stay in each client. No copy on new session: resolution is
  dynamic (see CHANGELOG v2.2). Regression test added in Oracle (pytest not run). ng build clean, quick menu
  checked with Playwright on a mocked API.
- [x] P5 Themis MCP tools + proposals via Hermes (P1) — delivery works with the Hermes global notifications now on
  main (event `service.action_required` with `kind: settings.proposal`, `closes` on decision); Athena candidate kind
  `setting` (`CHIAVE`/`VALORE`, observer lists proposable settings) → Themis proposal, capped by the new setting
  `athena.settings.proposals_per_day`. Parser regression test added (pytest not run).
- [ ] P6 Migrate remaining modules' tunable env vars (one module per step); includes Forge fallback/max_turns/
  auto_rollback, `declare_log_level` in every module, Metis baseline label still reading env MODEL_USECASE_GENERIC_MODEL
- [ ] Docs: hestia-<name>.md, swagger, .env.example notes, docs/ARCHITECTURE.md rule
- [x] Out of scope fix: Archive `avvisi_recenti` response prompt no longer Scout-specific (generic, caveman style)
