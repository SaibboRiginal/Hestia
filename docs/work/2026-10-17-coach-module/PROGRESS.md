# PROGRESS — Hercules (gym coach) module

Spec: `SPEC.md` v2.5 · resume from the first unchecked box.

- [x] Request received (project chat 2026-10-17), existing modules studied (Scout, Archive stores, Themis, Chronos, Hermes)
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] Align shared parts (§9) with threads Guardaroba, Self care, Plugin dei moduli nei client
- [x] Marko answered §13 (Hercules, gym only + offline, conversational adaptation) → SPEC v2.0
- [x] Start when the plugin contract is on main (phase 1 on main 2026-10-18, started on the recommended option)
- [x] P1 Hestia-Hercules service + Archive hercules-store + catalog seed (115) + CRUD + swagger + hestia-hercules.md + compose + CI + unit tests
- [x] P2 records / stats / progression / stall / import-export (Strong, Hevy)
- [x] P3 20 MCP tools, `fitness` tool domain (module_tool_domains, no Oracle change), adaptation engine, feedback, module context, optional reminder (agenda 18:30 + Hermes replaces), Themis settings
- [ ] Marko: `up-all.bat --build hercules archive` and a real session (Archive creates the table at start)
- [x] Fix 2026-10-18: Hub rejected registration (service_type domain, tag domain) → SERVICE_TYPE=module, tags module,fitness,context; Hub regression test covers Hercules defaults
- [x] P4 UI bundle Hestia-Hercules/ui/ (offline first + /sync): 9 pages, 8 widgets, live workout with rest timer, warm-ups, plates; typecheck + esbuild build OK, flows driven in Chromium incl. offline → online sync (2026-10-18)
- [ ] P5 Telegram polish (natural logging `hercules_log_sets` already in P3); wait for Marko's feedback from real use
- [x] Root CHANGELOG line
