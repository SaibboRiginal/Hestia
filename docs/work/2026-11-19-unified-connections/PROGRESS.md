# PROGRESS — Unified connections

- [x] SPEC v1.0
- [x] hestia_common/connections.py (contract, router, reload-keys, AddressConnector) + tests (Hub `test_connections_contract.py`)
- [x] plugin_client `connection` type + Hub catalog (bundle entry for modules with only connections) + WebUI catalog types
- [x] Hephaestus connection-secret endpoint + live reload + tests
- [x] Apollo ComfyUI connector (Test: version, GPU/VRAM, models) + env removed
- [x] Lares Home Assistant connector + env removed
- [x] Hecate: connectors on the shared contract, Google client in .env (`HECATE_KEY_GOOGLE_*`), Gmail instant notices card, Outlook card, phone key
- [x] Hermes VAPID generated and saved (`HERMES_KEY_VAPID_*`)
- [x] SDK `<hxk-connections>`; Hecate bundle removed
- [x] WebUI page /connections, setup step, Ctrl+K, setting editor link, sidebar
- [x] Hecate tool connections_status (Telegram) + `GET /api/gateway/connections-overview`
- [x] Docs, swagger, .env.example, compose, locales it, Argus ignore pattern
- [ ] precheck, PR, CI, merge

Left out on purpose (to decide with Marko): outbound MCP servers (`HECATE_MCP_<NAME>_URL/KEY`) still in .env;
`HECATE_ENABLE_PROVIDER_*` toggles; optional `GARMIN_EMAIL/PASSWORD` env.
