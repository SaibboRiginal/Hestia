# SPEC — Client plugins: modules install pages, widgets and dashboards into clients (WebUI first) · Scout as first plugin

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User request · channel: project thread (Claude Code cloud session) · 2026-10-17 |
| **Status** | Draft — waiting for Marko's confirmation (no code before it) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): give custom modules a way to **"install" themselves**
into the clients that have a plugin interface (WebUI first), so a module like Scout is not only notifications
but can be **seen**: widgets, pages, etc. Widgets are placed and configured by hand **or shown automatically in
a dashboard**; **Oracle can also create dashboards** for me. Pages are **always visible**. Settings to **hide or
show** each thing **per client**. Then implement it for **Scout** so Scout gets visual feedback. Next, new modules
(wardrobe, self care, coach — separate threads) will build on this contract as full standalone-quality apps
with pages and assistant context.

---

## 1. Goal

One **plugin contract** that any module (core or domain) uses to declare *what it can show* — pages, widgets,
data sources and actions — once, generically, without knowing which client will render it. Clients that have a
plugin interface (today: WebUI) discover the declarations and render them in the Hestia design system. The user
decides per client what is visible. Dashboards compose widgets from any module; the user or Oracle builds them.
Scout is the reference implementation.

## 2. Scope

### In
- Contract v1 (§4): manifest, surfaces (page, widget), data sources, actions, block kinds and their data shapes.
- `hestia_common.plugin_client` (shared lib, same pattern as `settings_client`): declare + register + re-assert
  + mount the data/action endpoints.
- **New core module `Hestia-Agora`** (§3): plugin catalog + dashboards (storage in Archive) + MCP tools so
  Oracle can list widgets and create/edit dashboards.
- Visibility per client = Themis `scope="user"` settings auto-declared for every surface (profile → client layer).
- WebUI: plugin runtime (sidebar entries for plugin pages, generic page renderer, block components, dashboard
  page with edit mode, "Plugin" section in Impostazioni to show/hide per client), .NET proxy controller.
- Scout plugin: "Case" page (filters, list/cards, detail), "Statistiche" section, widgets, actions.
- Docs: `docs/ARCHITECTURE.md` (global rule), Agora + Scout + WebUI module docs, swagger, AI-GUIDE, DESIGN-SYSTEM.

### Out (for now)
- Telegram rendering of plugins (contract allows it: `clients`; a later `/dashboard` text snapshot is possible).
- Wardrobe / self care / coach modules → their own threads, on top of this contract.
- Module-shipped JS bundles (web components) → contract reserves `renderer: "element:…"` for later (§4.7).
- Photo outfit composition (wardrobe thread, later).

## 3. Who does what (module boundaries)

| Module | Job in this feature |
|---|---|
| **Each module** (Scout, …) | declares its manifest; serves its own data sources and actions (its own data only) |
| **Agora** (new, core, port **19017**, Raspberry Pi like Themis) | **catalog** of every module's manifest (register, re-assert, online state via Hub); **dashboards** (CRUD, auto "Home" dashboard); MCP tools for dashboards. Owns no domain data, renders nothing |
| **Archive** | stores dashboards (one generic table `ui_dashboards`), like the settings store |
| **Themis** | visibility settings per surface (user scope → client layer); the user changes them like any setting |
| **Hub** | routing only (client → module data/action, module → Agora). Unchanged |
| **WebUI** | renders surfaces and dashboards; proxies data/actions only to paths declared in the catalog |
| **Oracle** | only through Agora's MCP tools (`ui_widgets`, `dashboard_*`) when the user asks in chat |
| **Hermes** | unchanged: modules keep notifying through it; a notification may link to a plugin page (`_link`) |

Why a new module and not Hub/Themis: Hub is registry + router (no business logic), Themis is settings; a
dashboard is user content composed across modules, so it needs one owner. Agora = "the square where modules show
themselves".

## 4. The contract v1 (read this if you build a plugin)

### 4.1 Declaring (Python module)

```python
from hestia_common.plugin_client import PluginClient, page, widget, section, block, source, action, field

ui = PluginClient("scout", title="Scout", icon="home", color="amber",
                  description="Case trovate dalle email degli annunci")
ui.declare(
  sources=[
    source("listings", "/api/ui/listings", params=["q", "city", "status", "price_max", "rooms_min", "sort", "limit", "offset"]),
    source("listing", "/api/ui/listings/{id}"),
    source("stats", "/api/ui/stats"),
  ],
  actions=[
    action("fetch_now", "Controlla email", "POST", "/api/scout/cycle", icon="refresh", tone="primary"),
    action("set_status", "Cambia stato", "PATCH", "/api/ui/listings/{id}",
           fields=[field("listing_status", "Stato", "enum", options=["available", "in_negotiation", "sold"])]),
  ],
  pages=[
    page("listings", "Case", icon="home", order=10,
         filters=[field("q", "Cerca", "string"), field("city", "Città", "enum", options_source="stats#cities"),
                  field("price_max", "Prezzo max", "int", unit="€")],
         sections=[
           section("Panoramica", [block("stat", source="stats#kpi")]),
           section("Annunci", [block("cards", source="listings", item_page="listing",
                                     item_actions=["set_status"])]),
         ],
         actions=["fetch_now"]),
    page("listing", "Annuncio", detail=True, sections=[section(None, [block("detail", source="listing")])]),
  ],
  widgets=[
    widget("new_listings", "Nuove case", block("list", source="listings", params={"sort": "-created", "limit": 5}),
           size="m", auto=True),
    widget("kpi", "Case in numeri", block("stat", source="stats#kpi"), size="s", auto=True),
  ],
)
app.include_router(ui.router())   # GET /api/ui/manifest (Agora re-reads it); data/actions are the module's own routes
ui.start()                        # background register to Agora via Hub + hourly re-assert (like settings_client)
```

Ids: surface id = `<module>.<id>` (`scout.listings`, `scout.new_listings`). Paths are the module's own routes,
reached only through Hub (`/route/<module>/<path>`); `{id}`-style placeholders are filled by the client.

### 4.2 Manifest (JSON, what Agora stores and clients read)

```json
{ "module": "scout", "version": 3, "title": "Scout", "icon": "home", "color": "amber", "description": "…",
  "sources":  { "listings": {"path": "/api/ui/listings", "params": ["q", "…"]}, "…": {} },
  "actions":  { "fetch_now": {"label": "Controlla email", "method": "POST", "path": "/api/scout/cycle",
                              "icon": "refresh", "tone": "primary", "confirm": null, "fields": []} },
  "pages":    [ {"id": "listings", "label": "Case", "icon": "home", "order": 10, "detail": false,
                 "clients": ["*"], "filters": [], "actions": ["fetch_now"],
                 "sections": [ {"title": "Panoramica", "blocks": [ {"kind": "stat", "source": "stats#kpi"} ]} ] } ],
  "widgets":  [ {"id": "new_listings", "label": "Nuove case", "size": "m", "auto": true, "clients": ["*"],
                 "block": {"kind": "list", "source": "listings", "params": {"limit": 5}},
                 "configurable": ["city", "price_max"] } ] }
```

- `version` = hash/counter; clients refetch when the catalog revision changes.
- `source#path` selects a sub-object of the source's answer (`stats#kpi` → `answer.kpi`).
- `clients`: `["*"]` or a list (`webui`, `telegram`, …). A client shows only what it supports (§4.6).
- `configurable`: widget params the user/Oracle may set per dashboard instance (e.g. city filter).

### 4.3 Surfaces

- **Page** — a full screen. Non-detail pages get a sidebar entry under the module's group, **always visible by
  default**. `detail: true` pages have no entry; they open from an item (`item_page`), route
  `/p/<module>/<page>/<id>`. A page = header (label, page actions, "Chiedi a Hestia") + optional filter bar +
  optional `tabs` + sections; each section = title + grid of blocks (`span` 1–4 columns).
- **Widget** — one block in a card, for dashboards. `size`: `s` (1×1), `m` (2×1), `l` (2×2), `xl` (4×2).
  `auto: true` → appears on the automatic **Home** dashboard. Clicking a widget title opens `open_page` if set.

### 4.4 Block kinds (closed vocabulary; data shapes are what the source returns)

| kind | data shape (source answer, or `#sub` of it) | use |
|---|---|---|
| `stat` | `{items:[{label, value, unit?, delta?, tone?, icon?, hint?}]}` | KPI tiles |
| `list` | `{items:[{id, title, subtitle?, meta?, badge?:{text,tone}, icon?, image?, url?}], total?}` | compact lists |
| `cards` | same as `list` + `fields?:[{label,value}]`, `tags?:[]` | rich items with photo |
| `table` | `{columns:[{key,label,type?:text\|number\|money\|date\|badge\|link, sort?}], rows:[{id, …}], total?}` | sortable tables |
| `detail` | `{title, subtitle?, image?, images?, badge?, fields:[{label,value,type?}], text?, links?:[{label,url}]}` | one record |
| `chart` | `{type: line\|bar\|donut, x?:[…], series:[{name, values:[…], tone?}], unit?}` | trends, splits |
| `timeline` | `{items:[{at, title, text?, tone?, icon?}]}` | history, logs |
| `steps` | `{items:[{id, title, text?, done?, meta?}]}` (+ `toggle_action`) | routines, checklists |
| `progress` | `{items:[{label, value, max, unit?, tone?}]}` | goals, gauges |
| `markdown` | `{text}` | free text |
| `form` | none (built from `action.fields`, types = Themis setting types) | create/edit records |
| `actions` | none (list of action ids) | buttons |

Common: `empty` text, `params` (fixed source params), `item_page`, `item_actions`, `refresh` seconds (≥ 30).
Paging: client sends `limit`/`offset`, source returns `total`. Tones: `neutral, info, success, warning, danger, accent`.
Every block shows loading / empty / error states (module offline → "Scout non raggiungibile", no crash).

### 4.5 Actions

`{label, method, path, icon?, tone?, confirm?: "text", fields?: [field…]}`. With `fields` the client opens a form
(same controls as Themis settings: enum, bool, int, float, string, text, time, list, date, image-url). Answer of
an action: `{ok, message?, refresh?: ["listings"], open?: {page, id}}`. Clients show `message` as a toast and
refresh the named sources. Destructive actions must set `confirm`.

### 4.6 Visibility per client (Themis)

`plugin_client` auto-declares for every non-detail surface a Themis setting
`<module>.ui.<surface>.visible` (`bool`, `scope="user"`, group "Interfaccia", default `true`, `oracle="propose"`).
Profile = default for every client, client layer = override (hide Scout's page on the phone WebUI but not on desk
is a later "device" layer, out of v1). Clients read them with the catalog. Impostazioni → *Plugin* lists modules
and their pages/widgets with the switches.

Client capability: each client sends `client=<name>&kinds=stat,list,…` when reading the catalog; Agora drops
surfaces whose `clients` exclude it or whose blocks use kinds the client cannot draw.

### 4.7 Renderer (rich apps)

A page or widget may set `renderer`:
- absent (default) → generic renderer from blocks. **Preferred**: zero client code.
- `"native:<module>.<name>"` → a component shipped in the client (WebUI: `src/app/plugins/<module>/`,
  registered in `plugins/registry.ts`), for app-quality screens blocks can't do (live workout logger, outfit
  composer). Still declared, routed, made visible and permission-checked by the contract; data still only from
  the module's sources/actions. Shown only while the module is registered.
- `"element:<url>"` → reserved for module-shipped web components (not in v1).

### 4.8 Dashboards (Agora)

```json
{ "id": "home", "title": "Home", "icon": "grid", "auto": true, "created_by": "user|oracle", "clients": ["*"],
  "items": [ {"widget": "scout.new_listings", "x": 0, "y": 0, "w": 2, "h": 1, "params": {"city": "Milano"},
              "title": "Case a Milano"} ] }
```

- **Home** (`auto: true`): built from every visible `auto` widget, ordered by module; once the user edits it,
  it becomes a normal dashboard (new auto widgets are appended at the end, never moved).
- Users: create, rename, delete, edit mode (add from catalog, drag to move, resize s/m/l/xl, per-item params from
  `configurable`, title override). Dashboards appear in the sidebar under *Dashboard*.
- Oracle (MCP, domain `ui`): `ui_widgets(q?)` (catalog for the model, compact), `dashboard_list`,
  `dashboard_create(title, items)`, `dashboard_update(id, add?, remove?, title?)`. Created directly when the
  user asks in chat (reversible user content, marked "creata da Hestia"); Athena may only *suggest* via Hermes.

### 4.9 Endpoints

Module (via `plugin_client`): `GET /api/ui/manifest`. Its sources/actions are its own routes.

Agora (via Hub `/route/agora/…`):

| Method | Path | |
|---|---|---|
| POST | `/api/plugins/register` | module sends manifest (idempotent, by module + version) |
| GET | `/api/plugins/catalog` | `client, kinds` → modules (online from Hub) + surfaces + visibility + `revision` |
| GET | `/api/plugins/revision` | change marker (catalog + dashboards) |
| GET/POST | `/api/dashboards` | list / create |
| GET/PUT/DELETE | `/api/dashboards/{id}` | read / replace / delete |

WebUI backend (`/api/webui/plugins/*`, token-protected): `catalog`, `data/{module}/{source}` (query →
path params + query), `action/{module}/{action}` (body), `dashboards*`. It checks the module/source/action exist in
the catalog before calling Hub — no free proxy.

### 4.10 Rules for plugin authors

- Sources are **read-only** and fast (< 1 s); heavy work stays in the module's own jobs (agenda).
- Return labels in Italian, already formatted for people (money, dates as ISO + client formats them).
- Images: `https` URLs or module routes (`/api/ui/files/{id}` through Hub); never data from other modules.
- No secrets or raw personal data in manifests (the repo is public; manifests are code).
- A module's notifications (Hermes) may carry `_link: {module, page, id}` → WebUI opens the plugin page.

## 5. Scout plugin (first implementation)

- Sources: `listings` (search over Archive `real_estate`: q, city, status, price range, rooms, sqm, sort, paging),
  `listing/{id}` (detail: fields, summary, features, link to the ad, map link from geocoding), `stats`
  (kpi: totale, disponibili, in trattativa, venduti, prezzo medio, €/m² medio; charts: nuove case per settimana,
  per stato, prezzo per città; `cities` for the filter).
- Page **Case**: KPI row, filters, cards (price, m², rooms, city, status badge, score, "Apri annuncio"), detail page.
  Page tab **Statistiche**: charts.
- Actions: *Controlla email* (existing cycle), *Cambia stato* (patch `listing_status`), *Preferita* / *Scarta*
  (new user flag `user_flag: favorite|discarded`, discarded hidden by default).
- Widgets (auto): *Case in numeri* (s), *Nuove case* (m); manual: *Preferite* (m), *Prezzi per città* (l).
- Notifications: Scout's `entity.upserted` events gain `_link` to the listing.

## 6. Acceptance criteria

1. A module that calls `PluginClient(...).declare(...); start()` appears in the WebUI (sidebar page + widgets in the
   catalog) with **no WebUI code change** (generic renderer), within a minute of starting.
2. Module stopped → its pages show "non raggiungibile" and widgets a muted offline state; no errors elsewhere.
3. Impostazioni → Plugin: hiding Scout's page on WebUI removes the sidebar entry; Telegram unaffected; reset works.
4. Home dashboard shows Scout's auto widgets; user can add/move/resize/remove widgets, create a second dashboard.
5. In chat "creami una dashboard con le case a Milano" → Oracle uses `ui_widgets` + `dashboard_create`; it appears
   in the sidebar marked as created by Hestia.
6. Scout page: filter, open detail, change status, mark favourite, run "Controlla email" with toast + refresh.
7. WebUI proxy rejects undeclared modules/sources/actions (403).
8. Phone layout usable (sidebar burger, one-column dashboard, cards stack).

## 7. Phases

- **P1 Contract + Agora**: `plugin_client` (declare, validate kinds/fields, manifest router, register/re-assert,
  visibility settings), Agora service (catalog, dashboards, Archive store `ui_dashboards`, MCP tools), compose
  global + rpi, Hub tags, swagger, docs.
- **P2 WebUI runtime**: .NET `PluginsController`; frontend `features/plugins/` (catalog store, dynamic sidebar
  group, page renderer, 12 block components, action forms, dashboard page + edit mode), Impostazioni → Plugin,
  DESIGN-SYSTEM § Plugins. Verified with `ng build` + Playwright on mocked API.
- **P3 Scout plugin**: sources, actions, user flag, manifest, `_link` on events, docs.
- **P4 Oracle**: domain `ui` routing for the dashboard tools, prompt hints; end-to-end check of criterion 5.

Tests: written for `plugin_client` validation and Agora (unit/api), not run here (user rule).

## 8. Decisions to confirm (Marko)

1. **New module Agora** owns catalog + dashboards (recommended) — alternative: catalog in Hub, dashboards in Themis.
2. **Rich apps**: declarative blocks first + `native:` WebUI components when blocks are not enough (recommended);
   module-shipped web components later.
3. **Oracle creates dashboards directly** when asked in chat (recommended, reversible); Athena only suggests.
4. Visibility per **client** (webui/telegram) in v1; per **device** (phone vs desk) later.
