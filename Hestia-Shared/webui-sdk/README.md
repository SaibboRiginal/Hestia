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
      ${this.items.map(i => html`<hxk-card clickable heading=${i.title} @click=${() => this.host.navigate('houses/' + i.id)}>${i.price}</hxk-card>`)}
    </div></div>`;
  }
}
definePlugin({ 'scout-listings': ScoutListings });
```

Rules: element names start with `<module>-`; call only your own module (`host.api`, paths under `api_prefix`);
use the kit (`hxk-*`) and the tokens (`var(--accent)` …) so the plugin follows every theme; work at 360 px.
Any tech that outputs custom elements is allowed, always with these shared styles/libraries.

## Host API (`el.host`)

`api` · `image` · `upload` (resized on device, base64) · `navigate` / `link` · `openSetting(key?)` (Impostazioni on one
setting, or on the module's own; the shell already draws a gear to the module's settings on every page) · `toast` (with Annulla) · `confirm` ·
`assistant` ("Crea con Hestia") · `notify` (browser notification) · `config` (per-client prefs) · `store(name)`
(IndexedDB per module, offline) · `online` · `on('refresh'|'theme'|'visible'|'hidden'|'online'|'offline')` ·
`event?.(kind, data)` (tell the assistant what the owner just did: `mood_logged {score}`, `workout_done {records}`,
`deadline_done`, `budget_over {category?}`; the WebUI's fixed rules pick the mascot's reaction, unknown kinds are ignored;
call it after the action succeeded, with `?.` so older hosts still work).
Types: `src/types.ts`. Context (`el.ctx`): module, surface, id, route/widget params, query, size, theme, phone.

## Kit (`hxk-*`, prefix chosen so it never clashes with the WebUI's Angular `hx-*`)

`hxk-icon` · `hxk-button` (variant default|primary|ghost|danger, icon, loading) · `hxk-badge` (tone) · `hxk-card`
(heading, subtitle, clickable, slot actions) · `hxk-stat` (.items KPI; a tile that counts things gets `list` — shown in a panel — or `open`) · `hxk-state` (loading|empty|error|offline,
event retry) · `hxk-list` (.items, event item-click) · `hxk-chart` (line|bar|donut) · `hxk-field` (Themis types plus `password` and `email`,
event change) · `hxk-chain` (the one editor of an ordered «provider + model» list: .steps, .providers, .choices
{provider: options that fit}, .states, field model|voice; events steps-change, need-choices, retry) · `hxk-image-picker` (.host, photos) · `hxk-quicklog` (one-tap chips, Annulla, ⋯ other day, progress
hint) · `hxk-page-head` (the one page header: heading, sub = one line of context, default slot = the page's ONE primary
action, ask = label of the «Ask» button, .suggestions) · `hxk-empty` (the one empty state: icon, heading, text, slot
action = start button, example = a sentence the owner can tap to say it in chat). Both send `hxk-ask` (`askEvent()`):
`HestiaElement` catches it and opens the assistant with the page as context. Utility classes in every `HestiaElement`: `.page .card .grid .row .col .grow .muted .small .truncate`.

Texts in the owner's language: write the English text and wrap it, `tr('Save')`, `tr('{0} items', n)` (`tr`,
`language()` and `locale()` from `@hestia/webui-sdk`). The WebUI loads the catalog (`globalThis.__hestiaI18n`) before any
plugin, so a module-level constant can be wrapped too; add the Italian text to
`Hestia-Shared/hestia_common/locales/it/messages.json` (the test `test_every_webui_and_plugin_text_has_an_italian_translation`
checks it). Dates and numbers: `toLocaleDateString(locale(), …)`, never a literal `'it-IT'`. Never wrap SVG paths or CSS.

Helpers: `plural(n, one, many)` for counts («1 capo», «2 capi»); `this.markEmpty(bool)` in a widget with nothing to
show (the dashboard shrinks the cell). Touch targets follow `--tap`, scrollbars are thin and themed, and every
colour, radius and duration is a token, so plugins follow the user's theme **and style** (Classico, Vetro, Netto:
`Hestia-WebUI/frontend/DESIGN-SYSTEM.md` § Styles). Don't hardcode radii or durations, and don't give a page root an
opaque `var(--bg)`: with transparency on, the page backdrop must show through.

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
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-<Name>/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/<name>.js

FROM python:3.12-slim
…
COPY --from=ui-build /ui/dist /code/ui/dist          # PluginClient(..., dist="/code/ui/dist")
```

A UI change needs `up-all.bat --build <svc>` (the bundle is baked in the image). `ui/dist/` is git-ignored.

Local check: `npm ci && npm run typecheck && node build.mjs runtime` (here) — the WebUI build runs the runtime build too.
