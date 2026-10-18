# PROGRESS — core modules as plugins · one MCP · external AIs

Spec: `SPEC.md` v2.1 · resume from the first unchecked box.

- [x] Current state studied (plugin contract v2.7, core module endpoints, Hestia-MCP gateway, Forge router/tools, tunnel script, sidebar layout, the three tool paths: Oracle via Hub `/discovery/module-tools`, Telegram via MCP `/tools/all`, MCP `/tools/call`)
- [x] Dossier created (SPEC v1.0), revised to v2.0 after Marko's feedback
- [x] Marko confirms SPEC v2.0 (2026-10-18, card «Approva»: order P1→P6, write tools limited)
- [x] P1 sidebar one scroll area (fixed top/bottom) + sections Fissati/Generale/Dashboard/Moduli/Sistema, collapsible, pin on hover + drag in Fissati, no duplicates (computed list); settings `webui.sidebar.pinned`/`.collapsed` (.NET WebUISettings); `pin` icon; `PluginClient(kind=)`, `page(badge=)` validated under api_prefix, Hub catalog `modules[].kind`; badges polled with the catalog; docs (DESIGN-SYSTEM §9, webui md, shared md, swagger, ARCHITECTURE, client-plugins SPEC v2.8); test `test_core_kind_and_badge_reach_the_catalog` + validation cases (written, not run). Verified: `ng build` dev clean, Playwright on mocks at 1280×520 (whole list scrolls, top/bottom fixed, pinned entries not duplicated, badge, offline module dimmed) and 1280×900. .NET not compiled here
- [ ] P2 one MCP: Hestia-MCP `/mcp`; Oracle, Telegram, WebUI moved; old endpoints removed; docs
- [ ] P3 accesses (tokens, scopes, limit, audit), WebUI `/mcp` door, Forge note/submit branch, README guide
- [ ] P4 inside views (Hub, Argus, Oracle, Athena, Hermes, Chronos, Themis, Hephaestus, Metis), Sistema dashboard
- [ ] P5 OAuth server + consent page, Accessi page, Hecate outbound credentials, named tunnel guide
- [ ] P6 built-in pages → plugins (Sviluppo + Copia per AI, Notifiche, Agenda, Comandi & MCP, Documenti)
- [ ] Marko: `up-all.bat --build`, try criteria §4, root CHANGELOG
