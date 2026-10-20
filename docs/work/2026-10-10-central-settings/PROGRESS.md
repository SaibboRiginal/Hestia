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
- [x] P6 Migrate remaining modules' tunable env vars (one module per step):
  - [x] Hecate (calendar backfill, Archive/calendar timeouts, auth re-check, notify cooldown)
  - [x] Scout (cycle interval, mail senders/filters, batching, LLM timeout, reconcile, enrichment)
  - [x] Hermes (delivery retries, recurring dedupe, batch window, Telegram retract delay) and MCP (tool cache, timeouts)
  - [x] Argus (poll, auth check, log source/limits, alerts, remediation, Forge proposals); defaults keep the values
    the global compose ran with (backfill 0, batch 20 s, Outlook ignore pattern)
  - [x] Athena (loop, gate, retrospective, hints, observer, strategist, Forge, memory, skills, audit); agenda window
    hours are code defaults of the Chronos windows (user edits there win), not settings
  - [x] Hephaestus (Forge fallback/turns/timeouts/merge/rollback/push/verify/scheduler, remediation) and Metis
    (dataset limits/labels; base model read from Oracle `oracle.models.generic.model`, training window = agenda)
  - [x] Oracle (2026-10-18, v2.4): agent loop, context, timeouts/retries, Ollama behaviour, memory, Athena hints,
    approval gate (assistant read-only), caches, documents, prompt A/B → `oracle.*`; `ORACLE_CLAUDE_MODEL` →
    `oracle.models.claude_code.model`; dead Gemini model vars removed; `ORACLE_TIMEZONE` → container `TZ`
  - [x] Scout / Athena model choices → Oracle use cases `scout_extraction`, `athena_strategist`, `athena_auditor`
    (`/api/llm/generate` takes `use_case`); `SCOUT_LLM_*`, `ATHENA_*_MODEL/PROVIDER` removed
  - [x] Chronos: agenda tick/attempts, sync window/calendar/notify-new, reminder poll/look-ahead → `chronos.*`;
    `CHRONOS_SYNC_ENABLED` / `_POLL_SECONDS` dropped (the agenda job `chronos.calendar_sync` is the switch and the
    interval); `CHRONOS_DISPLAY_TZ` → `TZ`
  - [x] Telegram: alert grouping, feedback rate/snooze, hidden commands, locale, client instructions, stream timeout,
    signal style (+ per family, action = compact as the compose ran) → `telegram.*`; control server answers
    `/api/settings/effective|reload`
  - Left in env on purpose: secrets, URLs/ports, binaries/paths, `ORACLE_EMBED_DIM` (DB column), Oracle LLM gateway
    profiles (endpoint + key bundles), `ORACLE_NOTIFY_DEFAULT_TARGET`, Hecate `GOOGLE_OAUTH_FLOW_MODE`, Forge
    test/deploy commands.
  - Follow-up (optional): Argus monitor loop, Forge scheduler, Hermes retry loop, Hecate auth re-check are still
    sleep loops (could become agenda jobs).
- [x] Docs: hestia-<name>.md, swagger (`/api/settings/effective|reload` with `shared`, `/api/llm/generate` `use_case`),
  .env.example and compose comments, docs/ARCHITECTURE.md rule
- [x] Out of scope fix: Archive `avvisi_recenti` response prompt no longer Scout-specific (generic, caveman style)
- [x] v2.3 Impostazioni VS Code-like (2026-10-11): one search over everything (local, instant), sidebar
  Personali + Sistema with match counts, resizable; Personali rows = `<hx-setting-shell>`; user-scope settings
  only in Personali. "Themis non risponde" was the Hub registration 422 fixed in 9c8ebc8 (rebuild hub + themis).
- [x] Real run on the cloud bench (2026-10-19): value changed from the WebUI is used at once by the module (PAO 18 → expiry 547 days), history, Annulla, out-of-range 422, 15 modules in the panel → `docs/work/2026-10-19-prove-reali-banco/`
