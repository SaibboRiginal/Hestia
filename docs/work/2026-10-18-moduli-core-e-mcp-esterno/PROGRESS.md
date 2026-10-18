# PROGRESS — core modules as plugins · one MCP · external AIs

Spec: `SPEC.md` v2.2 · resume from the first unchecked box.

- [x] Current state studied (plugin contract v2.7, core module endpoints, Hestia-MCP gateway, Forge router/tools, tunnel script, sidebar layout, the three tool paths: Oracle via Hub `/discovery/module-tools`, Telegram via MCP `/tools/all`, MCP `/tools/call`)
- [x] Dossier created (SPEC v1.0), revised to v2.0 after Marko's feedback
- [x] Marko confirms SPEC v2.0 (2026-10-18, card «Approva»: order P1→P6, write tools limited)
- [x] P1 sidebar one scroll area (fixed top/bottom) + sections Fissati/Generale/Dashboard/Moduli/Sistema, collapsible, pin on hover + drag in Fissati, no duplicates (computed list); settings `webui.sidebar.pinned`/`.collapsed` (.NET WebUISettings); `pin` icon; `PluginClient(kind=)`, `page(badge=)` validated under api_prefix, Hub catalog `modules[].kind`; badges polled with the catalog; docs (DESIGN-SYSTEM §9, webui md, shared md, swagger, ARCHITECTURE, client-plugins SPEC v2.8); test `test_core_kind_and_badge_reach_the_catalog` + validation cases (written, not run). Verified: `ng build` dev clean, Playwright on mocks at 1280×520 (whole list scrolls, top/bottom fixed, pinned entries not duplicated, badge, offline module dimmed) and 1280×900. .NET not compiled here
- [x] P2 one MCP: Hestia-MCP `/mcp` (Streamable HTTP JSON, initialize/tools.list/tools.call/ping, batches, `_meta.hestia`, client visibility) over Hub discovery (`app/core/catalog.py`, `mcp_server.py`); `hestia_common.tool_call` (one resolver) + `hestia_common.mcp_client`; Oracle agent loop + approval path call `tools/call` (own resolver and HubClient.get_commands removed), Telegram registry/router on MCP (Hub fallback removed, `resolve_template` = shared rules), WebUI `HubClient.McpListToolsAsync/McpCallToolAsync` + CommandsController (args from JSON schema); `/tools`, `/tools/all`, `/tools/call` and `tool_registry.py` removed; docs (mcp, shared, oracle, telegram, webui md, swagger `/mcp`, ARCHITECTURE, readme). Tests: new `Hestia-MCP/tests/test_mcp_server.py` (7), Telegram `TestRouteCommandThroughMCP`, Oracle tests on a `HubBackedMCP` double — run here: MCP 7 passed, Oracle 390 passed, Telegram 141 passed. .NET not compiled here
- [ ] P3 accesses (tokens, scopes, limit, audit), WebUI `/mcp` door, Forge note/submit branch, README guide
- [ ] P4 inside views (Hub, Argus, Oracle, Athena, Hermes, Chronos, Themis, Hephaestus, Metis), Sistema dashboard
- [ ] P5 OAuth server + consent page, Accessi page, Hecate outbound credentials, named tunnel guide
- [ ] P6 built-in pages → plugins (Sviluppo + Copia per AI, Notifiche, Agenda, Comandi & MCP, Documenti)
- [ ] Marko: `up-all.bat --build`, try criteria §4, root CHANGELOG
