# SPEC — Wardrobe module (Guardaroba): pieces, accessories, outfits, wear diary, stats

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | User via external chat (Claude Code cloud session, project thread "Modulo Guardaroba") · 2026-10-17 |
| **Status** | Draft — waiting for user approval. UI part (§7) follows the plugin contract `docs/work/2026-10-17-client-plugins/SPEC.md` §4 (itself a draft); built once that contract is on main |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the project chat, 2026-10-17): new modules that enrich what the
assistant knows about me, **complete like serious standalone apps**. Wardrobe: the list of every single piece
I own, styles, seasons, **outfits grouping pieces**, the list of **accessories**; seeing outfits as photos put
together is a future nice-to-have, to build step by step. Everything functional, easy to use (UX/UI), and
exposed over MCP for the AI as usual. Pages always visible, widgets for dashboards (Oracle could build them),
per-client show/hide — through the plugin system designed in its own thread.

Sibling modules started the same day: Self care (thread "Modulo Self care"), Coach (thread "Modulo Coach
allenamenti"). Shared choices agreed between threads are marked **[shared]**.

---

## 1. Goal

One module that is the truth about Marko's wardrobe: what he owns (each piece individually, with photo), how
pieces combine into outfits, what he actually wears and when. The assistant reads it (MCP tools + a short
context summary) to answer "cosa mi metto?", "ho già una giacca blu?", "cosa non metto da mesi?", and to
suggest outfits for an occasion, a season, the weather or a trip.

## 2. Today (starting point)

- No wardrobe data anywhere. Archive has generic entities (`/api/entities`, JSONB payload + 768 vector) used by
  Scout; it has **no binary storage** (documents keep only extracted text).
- Oracle can already analyse images (`/api/chat/document[/json]` accept image/*, vision when the model has it); W5 adds or reuses a plain "describe this image as JSON" call there, still inside Oracle.
- WebUI pages are hand-written in Angular; the plugin contract that lets a module install pages/widgets in a
  client is being designed in thread "Plugin dei moduli nei client".

## 3. Scope

### In
- New domain module **`Hestia-Wardrobe`** (service `wardrobe`, container `hestia_wardrobe`, port **19017**
  [shared: Self care 19018, Coach 19019]), FastAPI, same skeleton as Scout/Dummy, registered on Hub, layer
  `domain`.
- Data stored in **Archive** only, in typed tables behind a storage-only router `/api/wardrobe-store/*`
  [shared pattern with Self care / Coach: `/api/<module>-store`, like `presence.py`; meaning and validation stay
  in the module, Archive only stores and queries].
- New **generic blob store in Archive** (`/api/blobs`) for photos [shared: owned by this thread, reusable by
  Self care / Coach].
- REST API (consumed by WebUI through Hub), MCP tools (Oracle, Telegram, MCP gateway), assistant context
  summary, statistics, rule-based outfit suggestions, wear diary, laundry/status tracking, wishlist.
- Optional AI help through **Oracle only**: describe a photo to prefill a new piece.
- Settings through Themis (`SettingsClient("wardrobe")`), scheduling through the agenda, notifications through
  Hermes.
- WebUI pages + dashboard widgets through the plugin contract (§7).

### Out (now)
- Automatic outfit images (background removal + composition): §8 phase W6, later and step by step.
- Shopping/price tracking on shops, weather provider (the module takes weather as an input; whoever owns
  weather passes it).
- Multi-user wardrobes (single owner, like the rest of Hestia).

## 4. Data model (Archive tables, storage router `/api/wardrobe-store`)

Tables `wardrobe_pieces`, `wardrobe_outfits`, `wardrobe_outfit_pieces` (outfit_id, piece_id, slot, order),
`wardrobe_wears`, `wardrobe_wear_pieces` (wear_id, piece_id), `wardrobe_taxonomies`, `wardrobe_collections`.
Ids are UUID strings; filterable fields are real columns (kind, category, status, seasons/styles/occasions as
text arrays with GIN, favorite, purchase date/price, wear date), the rest in a `data` JSONB column; every row has
`created_at`/`updated_at`. `wardrobe_pieces.embedding` = Vector(768) of a short text description (name, colours,
material, style) made by Oracle, for semantic search ("la camicia azzurra di lino"). Join tables let stats ask
"wears per piece in a period" in SQL instead of loading everything. Auto-migrated like the other Archive tables
(`create_all` + `ADD COLUMN IF NOT EXISTS`).

### 4.1 Piece (`wardrobe_pieces`) — one physical thing you own (garment, shoes or accessory)
| Field | Type | Notes |
|---|---|---|
| `kind` | `garment` · `shoes` · `accessory` | pages split by kind; one model so search, stats, outfits work the same |
| `name` | str | "Camicia Oxford azzurra" |
| `category` / `subcategory` | taxonomy keys | e.g. top/shirt, bottom/jeans, outerwear/coat, shoes/sneakers, accessory/watch |
| `brand`, `model` | str? | |
| `colors` | `[{name, hex, share}]` | primary first |
| `pattern` | taxonomy | plain, striped, checked, printed, … |
| `materials` | `[{name, percent}]` | from the label |
| `size`, `fit` | str?, taxonomy? | fit: slim/regular/oversize… |
| `seasons` | subset of spring/summer/autumn/winter | |
| `styles` | taxonomy list | casual, smart casual, formal, sport, streetwear, … (user-editable) |
| `occasions` | taxonomy list | work, evening, travel, home, sport, ceremony… |
| `warmth`, `formality` | 1–5 | used by suggestions |
| `weather` | `{min_c?, max_c?, rain_ok}` | optional override of what warmth implies |
| `condition` | new · good · worn · to_repair | |
| `status` | active · laundry · lent · stored · to_donate · donated · sold · wishlist · archived | `wishlist` = wanted, not owned |
| `location` | taxonomy | wardrobe, drawer, storage box, other house… |
| `care` | `{wash_c?, machine, dry_clean, iron, notes}` | |
| `purchase` | `{date?, price?, currency, store?, gift}` | cost per wear in stats |
| `photos` | `[blob_id]` | first = cover; thumbnails generated (§4.6) |
| `favorite`, `tags`, `notes` | bool, list, str | |
| `wear_count`, `last_worn` | derived | recomputed from the diary, never typed by hand |

Accessories use the same model (`kind=accessory`) with categories bag, belt, watch, jewellery, glasses, hat,
scarf, gloves, tie, wallet, other; they get their own page and filters.

### 4.2 Outfit (`wardrobe_outfits` + `wardrobe_outfit_pieces`) — a combination of pieces
`name`, `slots: [{slot, piece_id}]` (slots: base layer, top, mid layer, outerwear, bottom, one-piece, shoes,
accessories ×n — a slot can be empty), `styles`, `occasions`, `seasons` (default = intersection of the pieces'),
`weather` range, `rating` 1–5, `favorite`, `photos` (pictures of it worn), `board` (future layout for W6),
`source` (user · assistant), `status` (active · archived), `notes`. Derived: `wear_count`, `last_worn`,
`complete` (false when a piece is donated/archived → shown as "da rivedere").

### 4.3 Wear (`wardrobe_wears` + `wardrobe_wear_pieces`) — diary entry (what was worn on a day)
`date`, `outfit_id?` or `piece_ids[]` (ad-hoc outfit), `occasion?`, `weather? {temp_c, condition}`,
`rating?` (how it felt), `notes?`, `source` (webui · telegram · assistant). Writing/deleting a wear updates
`wear_count`/`last_worn` on the pieces and the outfit.

### 4.4 Vocabularies (`wardrobe_taxonomies`) — editable
One row per vocabulary (`category`, `pattern`, `fit`, `style`, `occasion`, `location`, `color`): `{values:
[{key, label, parent?, icon?, order, hidden}]}`. Seeded with Italian labels on first start (idempotent);
the user adds/renames/hides values from the UI or chat. These are **data**, not Themis settings.

### 4.5 Collections (light, phase W5)
`wardrobe_collections` — named groups: capsule wardrobe, packing list for a trip (`{trip dates, place,
items checked}`), "da comprare". Packing list = pieces + outfits + checkbox state.

### 4.6 Photos — Archive blob store [shared]
New generic Archive API, pure storage (no meaning):
- `POST /api/blobs` `{owner_module, content_type, data_base64, meta?}` → `{blob_id, size, sha256}`
  (dedupe by sha256 per module), `GET /api/blobs/{id}` → bytes, `GET /api/blobs/{id}/meta`,
  `DELETE /api/blobs/{id}`, `GET /api/blobs?owner_module=` (admin/cleanup).
- Table `blobs` (`blob_id`, `owner_module`, `content_type`, `size`, `sha256`, `data bytea`, `meta jsonb`,
  `created_at`). Max size enforced by the caller module (setting) and a hard Archive cap (env infra
  `ARCHIVE_BLOB_MAX_MB`, default 15).
- Wardrobe stores the original (EXIF orientation fixed, GPS stripped) + thumbnails 256 px and 768 px (WebP,
  Pillow), all as blobs; the piece keeps `{original, thumb, medium}` ids.
- Upload follows the plugin contract §4.5: the client resizes on device (long side ≤ 2048 px) and sends
  `{name, mime, data_b64}` (≤ 8 MB) in the JSON body; Telegram photos arrive the same way. Images are served
  back by the module route `GET /api/ui/files/{blob_id}?size=thumb|medium|original` (plugin contract §4.11),
  cached by the browser (immutable ids).

## 5. Module API (REST, via Hub `route/wardrobe/...`)

| Method | Path | What |
|---|---|---|
| GET/POST | `/api/wardrobe/pieces` | list (filters: kind, category, status, season, style, occasion, color, q semantic/text, favorite, not_worn_days; sort; paging) / create |
| GET/PATCH/DELETE | `/api/wardrobe/pieces/{id}` | detail (with outfits using it and last wears) / edit / delete (soft → `archived` unless `hard=true`) |
| POST | `/api/wardrobe/pieces/{id}/photos` · DELETE `.../photos/{blob_id}` | add/remove photo, set cover |
| POST | `/api/wardrobe/pieces/bulk` | bulk status change (e.g. 5 pieces → laundry) |
| GET/POST, GET/PATCH/DELETE | `/api/wardrobe/outfits[/{id}]` | same as pieces |
| GET/POST, DELETE | `/api/wardrobe/wears[/{id}]` | diary (range `from`/`to`) / log a wear |
| POST | `/api/wardrobe/suggest` | `{date?, occasion?, styles?, weather?, exclude_recent_days?, count?}` → ranked outfits (saved + generated) with reasons |
| GET | `/api/wardrobe/stats` | totals by kind/category/colour/season/style, value, cost per wear, most/least worn, forgotten pieces, gaps (e.g. no winter shoes) |
| GET/PUT | `/api/wardrobe/taxonomies[/{name}]` | vocabularies |
| GET/POST, PATCH | `/api/wardrobe/collections[/{id}]` | capsules, packing lists |
| POST | `/api/wardrobe/describe-photo` | photo → Oracle (vision) → proposed piece fields (never saved by itself) |
| GET | `/api/ui/files/{blob_id}` | image bytes (`size` = original/medium/thumb) |
| GET | `/api/ui/*` | plugin sources in the block shapes of the plugin contract §4.4 (cards, stat, chart, timeline…) |
| GET | `/api/module/context` | assistant summary [shared contract, §6.2] |
| GET | `/api/wardrobe/export` · POST `/api/wardrobe/import` | JSON export/import (backup, bulk entry from a spreadsheet later) |

Validation lives in the module (pydantic); Archive only stores.

### Suggestion engine (deterministic, no LLM)
Candidates = saved outfits + generated combinations from active pieces (top+bottom or one-piece, + shoes,
+ outerwear when cold). Hard filters: status active (not laundry/lent), season, weather vs warmth/rain_ok.
Score: occasion/style match, formality spread inside the outfit, colour harmony (simple rules on hue:
neutrals go with everything, ≤ 2 accent hues, no pattern clash), recency penalty (worn in the last N days),
rotation bonus for forgotten pieces, favourites and rating. Every result carries `reasons[]` so the assistant
can explain. Oracle adds the reasoning/taste on top through the tools; the module never calls an LLM for this.

## 6. Assistant integration

### 6.1 MCP tools (`hestia_common.mcp_helpers.MCPTool`, telegram group `guardaroba`)
| Tool | Does | Writes? |
|---|---|---|
| `guardaroba_cerca` | search pieces/accessories (text + semantic + filters) | no |
| `guardaroba_capo` | piece detail with outfits and wears | no |
| `guardaroba_aggiungi` | add a piece ("ho comprato una camicia blu di lino") | yes, direct (the user asked) |
| `guardaroba_modifica` | edit fields / status (laundry, lent, to donate…) | yes, direct |
| `guardaroba_outfit` | list / detail outfits | no |
| `guardaroba_crea_outfit` | save an outfit from pieces | yes, direct |
| `guardaroba_suggerisci` | "cosa mi metto" → engine results with reasons | no |
| `guardaroba_indossato` | log today's (or a date's) outfit/pieces | yes, direct |
| `guardaroba_statistiche` | stats and forgotten pieces | no |
| `guardaroba_valigia` | packing list for a trip (collection) | yes, direct |
| `guardaroba_riepilogo` | same text as `/api/module/context` (on-demand summary) | no |
| `guardaroba_elimina` | delete a piece/outfit | **confirm via Hermes** (button) before acting |

Telegram: a photo sent with "aggiungi al guardaroba" → `describe-photo` → draft shown → user confirms.

### 6.2 Assistant context contract [shared, defined here; Self care and Coach reuse it]
The plugin contract leaves assistant context out (its §4.10), so this dossier defines it for every module:
- Route `GET /api/module/context?budget=<chars, default 600>` → `{module, domain, updated_at, text}`. `text` =
  caveman-style lines, already trimmed to `budget`, no secrets, e.g. `guardaroba: 84 capi (41 top, 18 bottom…),
  12 outfit; stile prevalente smart casual; in lavanderia 3; dimenticati >180g: 7; ultimo outfit 16/10
  "ufficio blu"`. Cheap (< 200 ms, computed from counters, cached 5 min).
- The same text is offered as an on-demand MCP tool `<prefix>_riepilogo` (here `guardaroba_riepilogo`; Coach /
  Self care may name theirs `coach_summary` / `selfcare_overview`), so the agent can pull it any time.
- Discovery: the module's Hub registration carries the tag `context` (Hub vocabulary extended). Oracle (the only
  consumer) may add the `text` of modules whose `domain` matches the classified chat domain as one context line,
  within its own budget setting. That Oracle step is a small separate change owned by Oracle, done after the
  first module ships; until then the tool alone gives the assistant the data.
- A shared helper `hestia_common.context_client.ModuleContext(module, domain, build_fn)` mounts the route
  and caching so the three modules don't copy code (written in W2 by this thread).

### 6.3 Settings (Themis, `SettingsClient("wardrobe")`)
| Key | Default | Apply |
|---|---|---|
| `wardrobe.forgotten_days` | 180 | live — "dimenticato" threshold |
| `wardrobe.suggest.count` | 3 | live |
| `wardrobe.suggest.exclude_recent_days` | 4 | live |
| `wardrobe.photo.max_mb` | 10 | live |
| `wardrobe.currency` | EUR | live |
| `wardrobe.review.enabled` | false | live — monthly review notification |
| `wardrobe.log.level` | INFO | live |

### 6.4 Agenda + Hermes
- Job `wardrobe.review` (monthly, 1st Sunday 10:00, registered with `agenda_client`, runs only when
  `wardrobe.review.enabled`): Hermes notification to `owner` with forgotten pieces, pieces to repair, laundry
  older than 7 days, outfits to review. User edits/pauses in the agenda win.
- Optional evening nudge "cosa hai indossato oggi?" as a second agenda job `wardrobe.diary_prompt` (disabled
  by default) — diary quality drives stats and suggestions.

## 7. UI (WebUI) — through the plugin contract

Declared with `hestia_common.plugin_client` (plugin contract §4.1) once it is on main: parent page
`guardaroba` (no sections, opens the first child) with sub-pages via `parent`, sources under `/api/ui/*`,
actions with `fields` (forms, image upload), widgets with `auto`/`configurable`. Visibility per client comes
for free from the contract (Themis `wardrobe.ui.<surface>.visible`). Generic blocks where they fit; `native:`
renderers (`Hestia-WebUI/frontend/src/app/plugins/wardrobe/`) only for the outfit builder, the diary calendar
and the add-piece fast path. Rules: `Hestia-WebUI/frontend/DESIGN-SYSTEM.md`, every resizable side panel uses
`<hx-resize>`, phone-first usable.

**Pages** (always visible group "Guardaroba", hideable per client by the plugin settings):
1. **Capi** (`cards` block + filters) — photo grid (cards: cover, name, colour dots, wear count) / list toggle; search bar; filter chips
   (kind, category, season, style, status) + side filter panel (`<hx-resize key="wardrobe-filters">`); quick
   actions on a card (in lavanderia, indossato oggi, preferito); "+" opens the add flow.
2. **Accessori** — same view preset on `kind=accessory`.
3. **Dettaglio capo** — side drawer (`<hx-resize key="wardrobe-piece">`) or full page on phone: photos
   carousel, all fields editable inline, outfits that use it, wear history, cost per wear.
4. **Aggiungi capo** (`native:wardrobe.add_piece`) — fast path: take/choose photo → "Compila con l'AI" (describe-photo) → review → save;
   only name + category required, the rest optional; "aggiungi un altro" keeps category/brand.
5. **Outfit** (`cards`; builder = `native:wardrobe.outfit_builder`) — cards with a mosaic of piece thumbnails by slot; **builder**: slots on the left, piece picker
   on the right filtered by slot (`<hx-resize key="wardrobe-builder">`); save, rate, mark worn.
6. **Diario** (`native:wardrobe.diary`, `timeline` fallback for other clients) — month calendar with the outfit thumbnail per day; tap a day to log/edit.
7. **Suggerimenti** — "Cosa mi metto": occasion/weather inputs, ranked outfits with reasons, "indossa" / "salva".
8. **Statistiche** (`stat` + `chart` + `list` blocks) — charts: category/colour/season distribution, most/least worn, cost per wear, forgotten
   pieces with action buttons (archivia, da donare).
9. **Wishlist e valigie** — wishlist pieces; packing lists with checkboxes.
10. **Vocabolari** (in the module's settings page) — edit styles, categories, occasions, locations.

**Widgets** (dashboard, also composable by Oracle via the contract's `dashboard_*` tools): *Outfit di oggi*
(`cards`, auto, `configurable`: occasion), *In lavanderia* (`list`), *Capi dimenticati* (`list`, auto),
*Guardaroba in numeri* (`stat`, auto), *Ultimi outfit* (`timeline`).

## 8. Phases

| Phase | Content | Depends on |
|---|---|---|
| **W1** | Archive blob store + `wardrobe_*` tables and `/api/wardrobe-store`; module skeleton (service, Dockerfile, compose global, Hub registration, settings, startup); data model + validation; CRUD pieces/outfits/wears/taxonomies with seed; photos + thumbnails; swagger; docs; tests | — |
| **W2** | MCP tools; `hestia_common.context_client` + `/api/module/context`; Telegram photo → draft piece; Hermes confirm for delete | W1 |
| **W3** | Stats, suggestion engine, derived counters, forgotten/gaps, agenda jobs + Hermes review | W1 |
| **W4** | WebUI pages + widgets via the plugin contract | W1–W3 + plugin contract on main |
| **W5** | describe-photo (Oracle vision), collections (capsule, packing lists), export/import | W1 |
| **W6** (later, step by step) | Outfit board: manual collage of piece photos in the builder (drag/scale, saved in `outfit.board`) → then automatic cut-outs (background removal, run where the hardware allows) → auto-composed outfit image | W4 |

## 9. Acceptance criteria

1. A piece with photo can be added from WebUI in ≤ 3 taps after the photo (name + category), and from Telegram
   by text or photo.
2. Every field of §4 is editable; pieces filter by kind/category/season/style/status/colour and are found by
   semantic search ("giacca pesante scura").
3. Outfits can be built from pieces by slot, rated, worn; donating a piece flags its outfits "da rivedere".
4. Logging a wear updates wear count / last worn of pieces and outfit; the diary shows every day.
5. "Cosa mi metto domani per ufficio, 8 gradi, pioggia" through chat returns 3 outfits from available pieces
   (no laundry, right season/warmth, not worn in the last days) with reasons.
6. Stats show cost per wear, forgotten pieces and gaps; the monthly review (when enabled) arrives through Hermes.
7. The assistant answers wardrobe questions using only the tools/context (no data in Oracle).
8. No direct service URLs (Hub only), no DB outside Archive, no LLM call outside Oracle, no new env tunables
   (only infra: port/URLs, `ARCHIVE_BLOB_MAX_MB`), no personal data in tracked files.
9. Tests: unit (validation, derived counters, suggestion scoring, thumbnails), api (routes with mocked Hub),
   format (tool declarations, plugin manifest); Archive blob store and wardrobe-store tests.

## 10. Design decisions

- **Typed tables behind a storage-only router** (v1.1, aligned with Self care and Coach): stats by period and
  by piece are SQL queries, not scans of JSON in Python; Archive still holds no meaning (validation, derived
  counters and rules stay in the module), same pattern as the settings and presence stores.
- **One `piece` model for garments, shoes and accessories**: same search/stats/outfits code; the UI splits them.
- **Blob store generic in Archive** (not files in a module `data/` volume): Archive is the only storage owner and
  backups stay in one place; the sibling modules reuse it.
- **Suggestions deterministic in the module, taste/explanation in Oracle**: cheap, testable, explainable; local
  models get compact tool results instead of the whole wardrobe.
- **Assistant writes directly when the user asks**, deletes only after Hermes confirmation (Hermes owns
  confirmations).
- **Name `Hestia-Wardrobe`**: domain modules use plain names (Scout); can be renamed before W1.
