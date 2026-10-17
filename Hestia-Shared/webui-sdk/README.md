# Hestia WebUI SDK (`@hestia/webui-sdk`)

Build a module's own UI for the WebUI. Contract: `docs/work/2026-10-17-client-plugins/SPEC.md` §4.

## How it fits

```
Hestia-<Name>/ui/src/index.ts  --(node build.mjs plugin, in the module's Docker build)-->  ui/dist/webui/<name>.js
module: PluginClient(...).webui(entry="<name>.js", pages=…, widgets=…, quick_actions=…)  → GET /api/ui/manifest
Hub:    capabilities.ui_manifest → GET /api/discovery/catalog?client=webui                 (one catalog: client × type)
WebUI:  loads /plugins/<module>/<name>.js, creates <name-…> elements, sets el.host + el.ctx
```

The WebUI serves this SDK **once** (`/plugins/_sdk/sdk.js`, with Lit inside) and maps `@hestia/webui-sdk`, `lit`
and `lit/*` to it with an import map: plugin bundles contain only their own code and every plugin shares the same
kit and styles.

## A page in 20 lines

```ts
import { HestiaElement, definePlugin, html, css } from '@hestia/webui-sdk';

class ScoutListings extends HestiaElement {
  static properties = { items: { state: true } };
  declare items: any[] | null;
  static styles = [...HestiaElement.styles, css`.grid { --min: 260px; }`];
  constructor() { super(); this.items = null; }
  async connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() {
    const r = await this.host.api('GET', '/api/ui/listings', { query: { limit: 30 } });
    this.items = r.ok ? r.data.items : [];
  }
  render() {
    if (this.items === null) return html`<hxk-state kind="loading"></hxk-state>`;
    return html`<div class="page"><h1>Case</h1><div class="grid">
      ${this.items.map(i => html`<hxk-card clickable heading=${i.title} @click=${() => this.host.navigate('case/' + i.id)}>${i.price}</hxk-card>`)}
    </div></div>`;
  }
}
definePlugin({ 'scout-listings': ScoutListings });
```

Rules: element names start with `<module>-`; call only your own module (`host.api`, paths under `api_prefix`);
use the kit (`hxk-*`) and the tokens (`var(--accent)` …) so the plugin follows every theme; work at 360 px.
Any tech that outputs custom elements is allowed, always with these shared styles/libraries.

## Host API (`el.host`)

`api` · `image` · `upload` (resized on device, base64) · `navigate` / `link` · `toast` (with Annulla) · `confirm` ·
`assistant` ("Crea con Hestia") · `notify` (browser notification) · `config` (per-client prefs) · `store(name)`
(IndexedDB per module, offline) · `online` · `on('refresh'|'theme'|'visible'|'hidden'|'online'|'offline')`.
Types: `src/types.ts`. Context (`el.ctx`): module, surface, id, route/widget params, query, size, theme, phone.

## Kit (`hxk-*`, prefix chosen so it never clashes with the WebUI's Angular `hx-*`)

`hxk-icon` · `hxk-button` (variant default|primary|ghost|danger, icon, loading) · `hxk-badge` (tone) · `hxk-card`
(heading, subtitle, clickable, slot actions) · `hxk-stat` (.items KPI) · `hxk-state` (loading|empty|error|offline,
event retry) · `hxk-list` (.items, event item-click) · `hxk-chart` (line|bar|donut) · `hxk-field` (Themis types,
event change) · `hxk-image-picker` (.host, photos) · `hxk-quicklog` (one-tap chips, Annulla, ⋯ other day, progress
hint). Utility classes in every `HestiaElement`: `.page .card .grid .row .col .grow .muted .small .truncate`.

## Module folder and Docker build

```
Hestia-<Name>/ui/src/index.ts      # defines all the module's elements
Hestia-<Name>/ui/tsconfig.json     # paths: "@hestia/webui-sdk" → ../../Hestia-Shared/webui-sdk/src/index.ts
```

```dockerfile
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/ ./
COPY Hestia-<Name>/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/<name>.js

FROM python:3.12-slim
…
COPY --from=ui-build /ui/dist /code/ui/dist          # PluginClient(..., dist="/code/ui/dist")
```

A UI change needs `up-all.bat --build <svc>` (the bundle is baked in the image). `ui/dist/` is git-ignored.

Local check: `npm ci && npm run typecheck && node build.mjs runtime` (here) — the WebUI build runs the runtime build too.
