# PROGRESS — client plugins

Spec: `SPEC.md` v2.6 · resume from the first unchecked box.

- [x] Current state studied (WebUI APP_MODULES registry, Hub discovery/registry, Themis user scope, Scout tools)
- [x] Dossier created (SPEC v1.0 → v2.0 after Marko: bundles loaded from a link, Hub catalog, client-owned config)
- [x] Marko confirms SPEC v2.5 (2026-10-17, decisions §8)
- [x] P1 `hestia_common.plugin_client` (manifest, validation, bundle files with ETag, capabilities) + Hub `/api/discovery/catalog` (client × type, manifest cache, offline keeps last manifest) + WebUI SDK `Hestia-Shared/webui-sdk` (types, HestiaElement, kit `hxk-*` incl. quicklog/chart/forms, build.mjs runtime|plugin, README); swagger, ARCHITECTURE rule, hub/shared docs; tests `Hestia-Hub/tests/test_plugins_catalog.py` written (not run, user rule); logic checked with a smoke script, SDK `tsc` + runtime build clean (sdk.js 45 KB, 15 KB gz)
- [ ] P2 WebUI .NET `PluginsController` + own settings `webui.plugins.*`/`webui.dashboards` + Angular loader, dashboards, Impostazioni → Plugin, MCP endpoint
- [ ] P3 Scout plugin (endpoints, user flag, Lit bundle, Dockerfile build stage, `_link`)
- [ ] P4 Oracle dashboard proposal end-to-end, docs final pass, root CHANGELOG
