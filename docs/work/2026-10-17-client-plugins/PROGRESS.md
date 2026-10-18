# PROGRESS — client plugins

Spec: `SPEC.md` v2.6 · resume from the first unchecked box.

- [x] Current state studied (WebUI APP_MODULES registry, Hub discovery/registry, Themis user scope, Scout tools)
- [x] Dossier created (SPEC v1.0 → v2.0 after Marko: bundles loaded from a link, Hub catalog, client-owned config)
- [x] Marko confirms SPEC v2.5 (2026-10-17, decisions §8)
- [x] P1 `hestia_common.plugin_client` (manifest, validation, bundle files with ETag, capabilities) + Hub `/api/discovery/catalog` (client × type, manifest cache, offline keeps last manifest) + WebUI SDK `Hestia-Shared/webui-sdk` (types, HestiaElement, kit `hxk-*` incl. quicklog/chart/forms, build.mjs runtime|plugin, README); swagger, ARCHITECTURE rule, hub/shared docs; tests `Hestia-Hub/tests/test_plugins_catalog.py` written (not run, user rule); logic checked with a smoke script, SDK `tsc` + runtime build clean (sdk.js 45 KB, 15 KB gz)
- [x] P2 WebUI: .NET `PluginCatalog` + `PluginsController` (catalog, bundle, call under api_prefix, image) + own settings `webui.plugins.*`/`webui.home.quick`/`webui.dashboards`; Angular `features/plugins/` (loader via blob import + import map, Home with quick strip + auto widgets, dashboards `/d/:id` with edit mode, module pages `/p/<module>/<page>`, sidebar sections, Ctrl/⌘+K palette, Impostazioni → Moduli e Home); PWA (manifest, `sw.js`, offline badge, offline start); Dockerfile builds the SDK runtime; docs (webui md, DESIGN-SYSTEM §9, swagger). Verified: `ng build` dev + prod clean, Playwright run against a mocked API with a demo Lit plugin (Home, edit, page, palette, phone, offline reload). .NET not compiled here (SDK download blocked) → Marko's build
- [ ] P3 Scout plugin (endpoints, user flag, Lit bundle, Dockerfile build stage, `_link`)
- [ ] P4 WebUI MCP endpoint (`webui_widgets`, `webui_dashboards`) + Oracle dashboard proposal end-to-end (question card in chat), docs final pass, root CHANGELOG
