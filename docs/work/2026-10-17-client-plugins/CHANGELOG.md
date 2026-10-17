# CHANGELOG — client plugins (spec changes)

- v1.0 — 2026-10-17 — first draft: plugin contract v1, new module Agora, Scout as first plugin — from Marko's request — user via project thread
- v1.1 — 2026-10-17 — Agora port 19020 (19017-19019 taken by wardrobe/self care/coach), sub-pages (`parent`), image upload as base64 in JSON, live UI client-side in native components, module context out of contract — requests from the wardrobe and coach threads — Hestia AI (peer threads)
- v2.0 — 2026-10-17 — redesign: plugins are module-shipped Web Component bundles loaded by the client from a link (SDK + host API), catalog = Hub discovery like MCP, no Agora module, each client owns its configuration as its own Themis settings, Oracle proposes dashboards via Themis — Marko's feedback on v1 — user via project thread
- v2.1 — 2026-10-17 — one Hub catalog organized by client and type (tool, command, page, widget; card and quick_action reserved), existing discovery kept; visibility stays per client (no central module) — Marko's feedback — user via project thread
- v2.2 — 2026-10-17 — offline: WebUI PWA with service worker caching shell + plugin bundles by version, host.online/events, host.store (IndexedDB per module); sync stays the module's job — request from the Hercules (coach) thread for gym use — Hestia AI (peer thread)
