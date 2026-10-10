# CHANGELOG (spec) — central settings

- v1.0 — 2026-10-10 — spec created after brainstorming (registry declared by modules, Archive store,
  scopes system/profile/client/session, state + revision for all clients, WebUI panel with search and module
  status, Oracle tools with user confirmation, Athena proposals; secrets/infrastructure stay in .env;
  export/import and test buttons dropped) — source: user via external chat (Claude Code cloud session).
- v1.1 — 2026-10-10 — new core module Themis owns the settings logic, Archive only stores (user wants the DB
  pure); Oracle/Athena may propose any key except safety ones (always with user confirmation); §3.9 LLM
  providers: provider types in code, provider instances as a list setting, use-case mapping, presets; new
  setting types object / list<object> / ref / secret_ref — source: user via external chat + coordinator
  request to align with the Haiku and Oracle-context threads.
- v1.2 — 2026-10-10 — no legacy env bridge (moved settings leave env; code defaults); only implemented
  provider types can be added, default instances pre-created; generic per-module/section presets (§3.10)
  with Personalizzato; roles of modules/Themis/Argus/Athena/Oracle (§3.11); Oracle Anthropic key env =
  ORACLE_ANTHROPIC_API_KEY — source: user via external chat + coordinator note.
- v1.3 — 2026-10-10 — chat proposal flow written out (search → get → propose → existing approval → apply);
  WebUI approval card added to P5 (missing today); providers UI: use-case comboboxes are the main control,
  instances under advanced "Connessioni" — source: user via external chat.
- v2.0 — 2026-10-10 — design change: Oracle is only the brain → settings tools belong to Themis (exposed via
  Hestia-MCP), confirmation delivered by Hermes (message + Approva/Rifiuta actions), no approval logic in
  Oracle; provider endpoints/keys are infrastructure (env), no "Aggiungi"/instance list — UI is only the
  use-case table with provider/model comboboxes — source: user via external chat.
- v2.1 — 2026-10-10 — rule: Hermes is the only outbound messenger to clients (checked all modules); Hermes
  WebUI channel recorded as an external dependency — source: user via external chat.
- v2.2 — 2026-10-10 — refinements during implementation: (1) Oracle models are flat keys
  `oracle.models.<use case>.{provider,model,fallback_provider,fallback_model,thinking}` instead of one
  `oracle.usecases.<uc>` object, so every client gets plain comboboxes and the WebUI a use-case table
  (`row`/`column` hints); (2) personal chat settings: tone and instructions are Oracle's (`oracle.chat.*`,
  scope user) and Oracle applies them itself from the `client` + session of each request; presentation
  options stay client-local; (3) a new session is not copied from the profile: session → client → profile is
  resolved at every message, so a session only stores explicit overrides (same result, no stale copies);
  (4) Forge permission modes are `oracle: read` — reason: simpler clients, one place that applies answer
  settings, module boundaries — source: implementation (central settings thread).

