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
