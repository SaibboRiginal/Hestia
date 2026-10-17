# SPEC — Client plugins: modules ship their own UI, clients discover and load it · Scout as first plugin

| | |
|---|---|
| **Version** | 2.3 |
| **Source** | User request · channel: project thread (Claude Code cloud session) · 2026-10-17 |
| **Status** | Draft — waiting for Marko's confirmation (no code before it) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): give custom modules a way to **"install" themselves**
into the clients that have a plugin interface (WebUI first): widgets, pages, etc. Widgets placed and configured
by hand or shown automatically in a dashboard; Oracle can also create dashboards. Pages always visible. Settings
to hide/show per client. Then do it for **Scout**. New modules (wardrobe, self care, coach — separate threads)
build on this as full standalone-quality apps.

v2.0 (Marko, after reading v1): a plugin is **a small standalone app (TS/HTML, even Angular) that the WebUI loads
from a link** and that adds routes and widgets dynamically, calling its own endpoints. The plugin system is a
**catalog like the MCP one** (modules only say they are available) — **no new module**. **Each client keeps its
own configuration** (what is shown, dashboards): the client is what gets configured.

---

## 1. Goal

A module that has a UI ships it **inside the module** as a browser bundle (Web Components). It advertises it in its
Hub registration, exactly like it advertises its MCP tools. Each client with a plugin interface (today the WebUI)
reads the catalog from Hub, loads the bundles it supports, mounts their pages and widgets, and lets the user
configure what is visible and the dashboards — stored as **that client's own settings** in Themis.

## 2. Scope

### In
- Contract v2 (§4): manifest in Hub registration, bundle format (custom elements), host API given to plugins.
- Hub: `GET /api/discovery/catalog` — one catalog organized by client and type (tools, commands, pages, widgets), existing discovery endpoints unchanged.
- `hestia_common.plugin_client` (Python): declare manifest, put it in `capabilities`, serve the bundle files.
- **Hestia WebUI SDK** `Hestia-Shared/webui-sdk/` (TypeScript): types, `definePlugin`, host API, design tokens +
  CSS kit, small Lit-based kit components (button, card, stat, list, table, chart, empty/error states, form
  fields, image picker), build script (esbuild) → one ES module per module.
- WebUI: plugin loader (dynamic routes `/p/<module>/...`, sidebar entries, widget host), proxy for plugin calls,
  dashboards page with edit mode, Impostazioni → *Plugin* (show/hide), WebUI's own settings for its configuration,
  small MCP endpoint so Oracle can see widgets and propose dashboards.
- Scout plugin: pages Case (+ detail) and Statistiche, widgets, actions.
- Docs: `docs/ARCHITECTURE.md` (global rule), Hub/Scout/WebUI docs, swagger, AI-GUIDE, DESIGN-SYSTEM § Plugins.

### Out (for now)
- Telegram plugins (contract allows other clients: `clients.telegram` later, e.g. text widgets).
- Wardrobe / self care / coach modules → their own threads, on top of this contract.
- Device-level configuration (phone vs desk) → later, as a layer of the client's settings.

## 3. Who does what (module boundaries)

| Module | Job in this feature |
|---|---|
| **Each module** (Scout, …) | owns its UI bundle and its own REST endpoints; advertises the manifest in its Hub registration |
| **Hub** | registry + discovery (already does it for MCP tools/commands): one organized `/api/discovery/catalog`; routing unchanged |
| **WebUI** (client) | loads bundles, gives them the host API, owns **its own configuration** (visibility, dashboards, layout) as its Themis settings, proxies plugin calls only to the plugin's own module |
| **Themis** | stores every client's configuration like any setting (owner = the client, e.g. `webui.*`); history/undo free |
| **Oracle** | sees widgets and dashboards through the WebUI's MCP tools; **proposes** a dashboard through Themis, Marko confirms via Hermes (same rule as every setting) |
| **Hermes** | unchanged; a notification may carry `_link: {module, page, id}` → the WebUI opens that plugin page |

No new module: the catalog is discovery (Hub), the configuration belongs to the client.

## 4. The contract v2 (read this if you build a plugin)

### 4.1 Module side (Python)

```python
from hestia_common.plugin_client import PluginClient, page, widget

ui = PluginClient("scout", title="Scout", icon="home", color="amber",
                  dist="/code/app/ui/dist")          # built bundle (see §4.4)
ui.webui(
  entry="scout.js",                                   # ES module that defines the custom elements
  pages=[
    page("case", "Case", element="scout-listings", icon="home", order=10),
    page("case/:id", "Annuncio", element="scout-listing", detail=True),
    page("statistiche", "Statistiche", element="scout-stats", icon="chart", parent="case"),
  ],
  widgets=[
    widget("kpi", "Case in numeri", element="scout-kpi-widget", sizes=["s", "m"], auto=True),
    widget("nuove", "Nuove case", element="scout-new-widget", sizes=["m", "l"], auto=True,
           params={"city": {"type": "string", "label": "Città"}, "limit": {"type": "int", "default": 5}}),
  ],
  api_prefix="/api/ui/",                              # paths the bundle may call on its own module
)
app.include_router(ui.router())    # GET /api/ui/manifest, GET /ui/webui/{file} (bundle + assets, ETag)
capabilities["ui_manifest"] = ui.manifest_path      # in the Hub registration payload, next to mcp_endpoint
```

Pages are **always visible** by default; `detail=True` pages have no sidebar entry; `parent` makes sub-pages
(sidebar entry expands: Guardaroba → Capi · Outfit · Accessori). Widget `params` = what the user (or Oracle) can
configure per dashboard instance; `sizes` from `s` (1×1), `m` (2×1), `l` (2×2), `xl` (4×2); `auto` = proposed on
the automatic Home dashboard.

### 4.2 One catalog, organized by client and by type (Hub)

Hub already has the pieces: the registry with each service's `capabilities`, MCP tool discovery
(`mcp_endpoint`), inline `commands`, `module_tool_domains`. Today each is read by its own endpoint. v2.1 puts them
in **one organized catalog** without breaking the existing endpoints (they stay, the catalog is a view over them
plus the new UI contributions):

`GET /api/discovery/catalog?client=webui&type=page,widget` →

```json
{ "revision": 42,
  "modules": [ {"module": "scout", "title": "Scout", "icon": "home", "color": "amber", "online": true, "version": "1.4.0+3f7f11f"} ],
  "contributions": {
    "webui":    { "page": [ … ], "widget": [ … ], "card": [ … ], "quick_action": [ … ], "bundle": [ {"module": "scout", "entry": "/ui/webui/scout.js", "api_prefix": "/api/ui/"} ] },
    "telegram": { "command": [ … ], "widget": [ … ] },
    "*":        { "tool": [ … ] } } }
```

- **Client** = who can show it (`webui`, `telegram`, future ones; `*` = every client, e.g. MCP tools).
- **Type** (closed list, the client ignores types it does not know):

| Type | Client | What it is | v1 |
|---|---|---|---|
| `tool` | `*` | MCP tool (Oracle, MCP gateway) — existing | ✓ existing |
| `command` | telegram, webui | command from a tool (Telegram menu, Comandi page) — existing | ✓ existing |
| `page` | webui | full page, always visible by default, sub-pages via `parent` | ✓ |
| `widget` | webui (telegram later: text) | block for dashboards, with `params`, `sizes`, `auto` | ✓ |
| `card` | webui | how the module's items look **inside the chat** (e.g. a Scout listing card when Oracle answers with houses) | later |
| `quick_action` | webui (telegram later: buttons) | **one-tap action** on the Home and in the Ctrl+K palette ("Routine viso fatta", "Outfit indossato", "Inizia allenamento") — §4.2b | ✓ |

- Each item carries `id` (`<module>.<id>`), `module`, `label`, `icon`, `order` and its type's fields.
- Modules declare everything in one place: `capabilities.ui_manifest` (UI) next to `mcp_endpoint` (tools);
  `plugin_client` builds the manifest, Hub fetches and caches it like MCP tools (TTL, refreshed on re-register).
- Offline modules stay in the catalog with `online: false`, so the client can say "Scout non raggiungibile".
- The WebUI Comandi & MCP page becomes the browser of this catalog (filters client · type · module).

### 4.2b Quick actions (one tap from the Home) — v1

Marko: everything must be **super fast from the WebUI Home** (routine done today, outfit worn, favourites).
Quick actions are drawn **by the WebUI itself** (no bundle load → instant), as a strip of chips at the top of Home
and in a Ctrl+K palette:

```json
{ "id": "routine_done", "label": "Routine fatta", "icon": "check", "group": "Self care",
  "source": "/api/ui/quick/routines",
  "method": "POST", "path": "/api/ui/routines/{id}/done", "confirm": null, "undo": {"method": "DELETE", "path": "/api/ui/routines/{id}/done/today"} }
```

- Static (one chip) or **dynamic** with `source` → the module returns the chips of the moment:
  `[{id, label, icon?, state?: "todo" | "done" | "late", hint?: "2/2 oggi", favorite?: bool}]` (e.g. one chip per
  routine due today, one per favourite outfit). Paths are under the module's `api_prefix`; `{id}` = chip id.
- Tap → call → toast with **Annulla** (`undo`) → chip changes state (✓). No dialogs unless `confirm` is set.
- Optional `params` → a tiny inline sheet (e.g. "peso", "note") instead of a page.
- The user pins/unpins chips (★) and orders them: WebUI setting `webui.home.quick` (client-owned, §4.6). By default
  Home shows the module's `favorite` / due-today chips.
- Widgets can also act in one tap (they are full components), quick actions are the zero-load path.

Module manifest (`GET /api/ui/manifest`, built by `plugin_client`):

```json
{ "module": "scout", "version": "1.4.0+3f7f11f", "title": "Scout", "icon": "home", "color": "amber",
  "clients": {
    "webui": { "entry": "/ui/webui/scout.js", "api_prefix": "/api/ui/", "sdk": "1",
               "page":   [ {"id": "case", "label": "Case", "element": "scout-listings", "icon": "home", "order": 10} ],
               "widget": [ {"id": "nuove", "label": "Nuove case", "element": "scout-new-widget",
                            "sizes": ["m", "l"], "auto": true, "params": {"city": {"type": "string"}}} ] } } }
```

### 4.3 Bundle = Web Components

- One ES module (`entry`) that registers custom elements with names prefixed by the module (`scout-…`).
- Any tech that outputs custom elements: **Lit + TS (recommended, small, the SDK kit is Lit)**, vanilla TS/HTML,
  or Angular Elements (allowed; heavier, ~150 KB per plugin).
- The WebUI creates the element and sets two properties: `host` (§4.5) and `ctx`
  (`{route params, query, widget params, size, theme, client}`); it listens for nothing else.
- Styling: the design tokens are CSS variables (`--surface-1`, `--accent`, …) which reach inside shadow DOM; the
  SDK ships the kit CSS and components so plugins look native in every theme. Phone: plugins must work at 360 px.
- Live UI (workout timer, rest countdown, browser notifications) is plain client-side code in the bundle;
  `host.notify()` asks the permission and shows a browser notification.

### 4.4 Build and deploy

- Source in `Hestia-<Name>/ui/` (`package.json`, `src/`), built with `Hestia-Shared/webui-sdk/build.mjs`
  (esbuild) into `Hestia-<Name>/ui/dist/` — **not committed** (`.gitignore`).
- The module Dockerfile gets a Node build stage (multi-stage, output copied into the Python image). A UI change
  needs `up-all.bat --build <svc>` (Forge tells the user, like WebUI changes).
- Version in the manifest (`version + build hash`) → the WebUI caches bundles and reloads when it changes.

### 4.5 Host API (what a plugin can do — `@hestia/webui-sdk`)

| | |
|---|---|
| `host.api(method, path, {query, body})` | calls **its own module** through WebUI → Hub; only paths under `api_prefix`; returns `{status, data}` |
| `host.image(path)` | URL for an image served by its module (module returns `{mime, data_b64}`; WebUI serves bytes) |
| `host.upload(file, {maxSide: 2048})` | resizes on the device, returns `{name, mime, data_b64}` (≤ 8 MB) to put in a body |
| `host.navigate(page, params)` / `host.link(...)` | routes inside the plugin (`/p/scout/case/123`) or other plugins |
| `host.toast(text, tone)` · `host.confirm(title, text, danger)` | WebUI toasts and dialogs |
| `host.assistant({label, hints, prompt})` | opens "Crea con Hestia" with the page context |
| `host.notify(title, body)` | browser notification (asks permission once) |
| `host.config` | read/write of the plugin's **per-client** preferences (stored in WebUI settings, §4.6) |
| `host.online` · `host.on('online' \| 'offline', cb)` | connection state (WebUI backend reachable) |
| `host.store(name)` | IndexedDB database namespaced by module (`hestia.<module>.<name>`) for offline data and queues |
| `host.on('refresh' \| 'theme' \| 'visible', cb)` | lifecycle |

Rule: a plugin talks only to its own module. Data from other modules goes through its module (or Oracle via MCP).

### 4.5b Offline (WebUI as an installable PWA)

The WebUI becomes a PWA (web manifest + service worker; today it has none). The service worker caches the app
shell, the catalog last seen and **every plugin bundle with its assets, by version**, so plugin pages open without
network (e.g. Hercules in the gym). Offline: `host.api` rejects with `offline` (no silent queue); each plugin keeps
its own offline data and sync queue in `host.store()` and syncs with its module when `online` fires (sync protocol =
the module's job, e.g. `POST /api/hercules/sync`). The WebUI shows an offline badge; dashboards show last data
where the plugin cached it. Login token stays valid offline (already stored in the browser).

### 4.6 Client configuration (each client owns its own)

The WebUI declares **its own** Themis settings (like it does already for `webui.auth.local_without_token`):

| Key | Type | |
|---|---|---|
| `webui.plugins.hidden` | list | hidden pages/widgets (`scout.case`, `scout.*`); empty = everything visible |
| `webui.plugins.order` | list | sidebar order of plugin pages |
| `webui.dashboards` | object | `[{id, title, icon, auto, created_by, items:[{widget, x, y, w, h, params, title}]}]` |
| `webui.home.quick` | list | pinned quick actions on Home, in order (`self_care.routine_done:viso-sera`) |
| `webui.plugins.prefs` | object | per-plugin preferences written by `host.config` |

- **No central module for this**: visibility is only Marko's customization of a client, so each client owns it.
  It is still "central" for free because every client's settings live in Themis: one Impostazioni panel can show
  them per client, history/undo works, Oracle can read them.
- `scope="user"`, so Themis already layers them (profile → client); another client (Telegram) declares its own.
- Impostazioni → *Plugin*: modules with their pages/widgets and switches; dashboards edited on the dashboard page.
- **Home dashboard**: built from visible `auto` widgets until the user edits it (then it is saved; new auto widgets
  are appended, never moved).
- Oracle: the WebUI registers in Hub with a small MCP endpoint: `webui_widgets(q?)` (compact catalog) and
  `webui_dashboards()`. To create or change a dashboard Oracle uses the existing `settings_propose` on
  `webui.dashboards` → Hermes → Marko confirms (same rule as every setting; nothing is written behind his back).

### 4.7 Endpoints

| Who | Method | Path | |
|---|---|---|---|
| Module | GET | `/api/ui/manifest` | manifest (also advertised as `capabilities.ui_manifest`) |
| Module | GET | `/ui/<client>/{file}` | bundle and static assets (ETag) |
| Hub | GET | `/api/discovery/catalog?client=&type=&module=` | organized catalog (§4.2) + online state + revision |
| WebUI | GET | `/api/webui/plugins` | catalog for the frontend (with visibility applied) |
| WebUI | GET | `/plugins/{module}/{file}` | bundle proxy (cached by version) |
| WebUI | ANY | `/api/webui/plugins/{module}/call/{path}` | plugin → its own module (checks `api_prefix`) → 403 otherwise |

## 5. Scout plugin (first implementation)

- Module endpoints `/api/ui/…`: `listings` (q, city, status, price, rooms, m², sort, paging), `listings/{id}`,
  `stats` (KPI, nuove per settimana, per stato, prezzi per città, città per i filtri), `PATCH listings/{id}`
  (`listing_status`, user flag `favorite|discarded`), `POST cycle` (existing email cycle).
- Pages: **Case** (KPI row, filters, cards with price, m², rooms, city, status, score, "Apri annuncio", Preferita /
  Scarta), **Annuncio** (detail, features, summary, map link), **Statistiche** (charts).
- Widgets: *Case in numeri* (auto), *Nuove case* (auto, param city), *Preferite*, *Prezzi per città*.
- Scout's `entity.upserted` notifications gain `_link` to the listing.

## 6. Acceptance criteria

1. A module with a `ui/` bundle and `capabilities.ui_manifest` appears in the WebUI (sidebar + widget catalog)
   **without changing or rebuilding the WebUI**, within a minute of registering.
2. Module stopped → its pages say "non raggiungibile", widgets show a muted offline state, nothing else breaks.
3. Impostazioni → Plugin: hiding Scout's page removes it from the WebUI sidebar; reset/undo works (Themis history).
4. Home dashboard shows Scout's auto widgets; add/move/resize/remove, configure params, create a second dashboard.
5. Chat "creami una dashboard con le case a Milano" → Oracle proposes it; after Approva it appears in the WebUI.
6. Scout pages: filter, detail, status change, favourite/discard, "Controlla email" with toast and refresh.
7. A plugin calling another module's path or outside `api_prefix` gets 403.
8. Home quick actions: a due routine chip → one tap → ✓ with Annulla, no page load; pin/unpin with ★.
9. Usable on the phone (360 px), light and dark themes.

## 7. Phases

- **P1 Contract**: `plugin_client` (manifest, router, bundle files), Hub `/api/discovery/catalog` (+ cache,
  revision, existing endpoints untouched), WebUI SDK (types, host API, kit, build script), swagger, ARCHITECTURE rule.
- **P2 WebUI runtime**: .NET `PluginsController` (catalog, bundle proxy, call proxy, image), WebUI settings
  (`webui.plugins.*`, `webui.dashboards`), Angular loader (dynamic routes, sidebar, widget host, Home quick-action strip + Ctrl+K palette), PWA service worker (offline bundles), dashboard page +
  edit mode, Impostazioni → Plugin, MCP endpoint, DESIGN-SYSTEM § Plugins. `ng build` + Playwright on mocks.
- **P3 Scout plugin**: endpoints, user flag, `ui/` bundle (Lit), Dockerfile build stage, `_link`, docs.
- **P4 Oracle**: domain routing for `webui_widgets` / dashboards proposal, end-to-end check of criterion 5.

Tests: written (plugin_client, Hub discovery, call-proxy guard), not run here (user rule).

## 8. Decisions to confirm (Marko)

1. Plugins as **Web Components with Lit + TS** (recommended; Angular Elements allowed when a plugin wants it).
2. Bundles **built in the module's Docker image** (recommended), not committed to git.
3. Oracle **proposes** dashboards via Themis and you approve (recommended, same rule as settings) — or it writes
   them directly because they are only layout.
