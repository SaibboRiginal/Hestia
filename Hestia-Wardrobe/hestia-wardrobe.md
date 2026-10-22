# Hestia-Wardrobe 👕

**Role:** Wardrobe — every garment, shoe and accessory, outfits, «Cosa mi metto», laundry, packing lists, stats
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Pillow · Docker · WebUI plugin bundle (Lit, `ui/`)
**Port:** 19017 · Dossier: `docs/work/2026-10-17-modulo-guardaroba/`

---

## Responsibility

- Owns the wardrobe: pieces (kind garment | shoes | accessory, category/subcategory, colours, pattern, materials,
  size, fit, seasons, styles, occasions, warmth/formality 1–5, rain, care, purchase, status, location, photos),
  outfits (pieces by slot base/top/mid/outer/bottom/onepiece/shoes/accessory, occasions, styles, seasons, rating,
  favourite, worn photos), «Indossato» marks, collections (capsule, packing list, shopping list) and the user's own
  vocabularies (categories with default slot, styles, occasions, colours with hex, patterns, fits, places).
  Styles and occasions typed as labels («Ufficio», «Elegante», from chat or the UI) are stored as their vocabulary
  key (`office`, `formal`); unknown words stay free tags. Suggestions and packing map them the same way.
- Status is the daily tool: Nell'armadio · In lavanderia · Prestato · Messo via · Da riparare · Da donare · Donato ·
  Venduto · Desiderato · Archiviato. Only «Nell'armadio» pieces are suggested.
- «Indossato» is **occasional**, never assumed daily: usage numbers (most worn, cost per wear, forgotten) are hints.
  Optional goal `wardrobe.tracking.goal_times` per day/week/month; one mark per outfit per day.
- «Cosa mi metto» is deterministic (no LLM): saved outfits + combinations generated from available pieces, filtered by
  season and weather (warmth band of the upper layers, rain), scored on occasion/formality, style, colour harmony
  (≤ 1 accent colour), pattern clash, recently worn (`suggest.exclude_recent_days`), rotation of forgotten pieces,
  favourites and rating. Every result carries its reasons. The assistant adds taste on top.
- Photos: orientation fixed, metadata (GPS) dropped by re-encoding, three sizes (original JPEG/WebP, medium 768,
  thumb 256 WebP). «Riconosci con AI» sends the medium photo to Oracle `/api/llm/chat` (use case `wardrobe.foto`, declared in the Hub registration; its chain, which must see images, is chosen in Oracle → Cervello → Modelli)
  and only **proposes** fields; the user saves.
- Does not call models directly, has no database: rows in Archive `wardrobe-store`, bytes in Archive `blobs`.

## Storage

- Archive `/api/wardrobe-store/records`: one table `wardrobe_records (kind, id)` with `data` JSONB, `parent_id`,
  `ref_id`, `at`, `updated_at`, `deleted`, `seq` (same pattern as Hercules: last write wins, cursor). Kinds: piece,
  outfit, wear, taxonomy, collection, reminder, photo.
- Archive `/api/blobs`: photo bytes (`owner_module=wardrobe`, deduplicated by sha256). A `photo` row groups the blob ids
  `{original, medium, thumb}`; removing the photo deletes the blobs no other photo uses.
- In-memory mirror refreshed by cursor: reads and stats are instant; Archive away → reads keep working
  (`[🔄] event=wardrobe_mirror_refresh_failed`), writes answer 503.

## Assistant

- Tools (`wardrobe` domain via `module_tool_domains`, REST `/api/wardrobe/tools/<name>`): `wardrobe_summary`,
  `wardrobe_search`, `wardrobe_piece`, `wardrobe_add`, `wardrobe_update` (status: laundry, lent…),
  `wardrobe_outfits`, `wardrobe_create_outfit`, `wardrobe_suggest`, `wardrobe_log_worn`,
  `wardrobe_stats`, `wardrobe_packing`, `wardrobe_delete`. Pieces and outfits are found by name.
- `wardrobe_delete` never deletes: it asks through Hermes with **Elimina / Archivia / Tieni**.
- `GET /api/module/context?budget=` → `{module, domain, updated_at, text}`: one caveman line (counts, style, laundry,
  forgotten, last outfit, goal). Hub capability `context_endpoint`, tag `context`. `&topic=<signal key>`
  (`forgotten`, `laundry_backlog`, `to_repair`) → the detail behind that signal (names, days); unknown topic → the
  normal line.

## Reflection signals (`hestia_common.signals_client`, dossier `docs/work/2026-10-20-riflessione-a-livelli`)

Deterministic, no LLM; texts say «Guardaroba», never the module name. Stored in Archive `signals-store` through
`Signals("wardrobe", "wardrobe").sync()` (only changes written, signals gone are retracted).

| Key | Severity | When | Page |
|---|---|---|---|
| `forgotten` | info | active pieces not worn for 60+ days (`stats.forgotten`; only once something was ever marked) | statistiche |
| `laundry_backlog` | attenzione | ≥ 3 pieces in laundry unchanged for 7+ days | capi |
| `to_repair` | info | pieces with status or condition «da riparare» | capi |

Weekly metric (12 ISO weeks, current included): `wardrobe.worn` «Capi indossati» = number of «Indossato» marks per
week. Re-evaluated after every mark / piece change (`signals.changed()`, debounced), once after warm-up and by the
agenda job `wardrobe.signals` (daily 17:30, editable) → `POST /api/wardrobe/signals/run`.

## Notifications (both off by default, through Hermes, target `owner`)

- Agenda job `wardrobe.reminder` (daily 08:30, time editable in the agenda) → `POST /api/wardrobe/reminder/check`.
  Sends only when `wardrobe.reminder.enabled`, a goal exists, nothing marked today, the goal is behind (or daily) and
  under `wardrobe.reminder.max_per_week`. One live reminder (`replaces: wardrobe.reminder`), actions = favourite
  outfits (`resolves: true`) + **Salta**. Marking from anywhere closes it (`closes` + decision done).
  "Sent today" and "this week" use the local day of the stored UTC timestamps (2026-10-18 fix: near midnight the UTC date is another day).
- Agenda job `wardrobe.review` (first Sunday of the month 10:00) → `POST /api/wardrobe/review/run` when
  `wardrobe.review.enabled`: forgotten, to repair, long in laundry, outfits to review.

## Client UI (plugin contract)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Seasons leaf/sun/leaf/snowflake, favourites and rating star, rain umbrella, done check.

Bundle `ui/src/index.ts` → `/ui/webui/wardrobe.js` (built in the Dockerfile). Pages: capi, capi/:id, accessori,
outfit, outfit/:id, cosa-mi-metto, statistiche, liste, liste/:id, vocabolari. Widgets: oggi (auto, one-tap
«Indossato» chips), suggerito, lavanderia, dimenticati (auto), numeri (auto), ultimi. Quick action `indossato`
(chips = favourite outfits + today's idea, undo). Multi-select on Guardaroba: In lavanderia / Nell'armadio /
Crea outfit / Da donare. A UI change needs `up-all.bat --build wardrobe`.

## Settings (Themis, `wardrobe.*`)

forgotten_days (180), photo.max_mb (10), suggest.count (3), suggest.exclude_recent_days (4),
tracking.goal_times (0 = no goal), tracking.goal_per (week), reminder.enabled (false), reminder.max_per_week (2),
review.enabled (false), notifiche.voce (true: notifications also as voice). Reminder and voice settings come from
`hestia_common.reminders`; currency and
week start (weekly goal) are the personal settings `themis.personal.*`.

## API (via Hub `/route/wardrobe/...`)

See `Hestia-Swagger/swagger.yml` tag *Wardrobe*. Groups: meta, vocabularies, pieces (+bulk, photos, cover),
files/{photo_id} (`{mime, data_b64}`), outfits (+photos, worn), wears, suggest (+save), stats, summary,
collections (+packing, check), describe-photo, export/import (JSON), quick (Home chips), reminder/check,
reminder/skip, review/run, signals/run.

## Export and import (`/api/transfer/*`, dossier `docs/work/2026-10-20-import-export`)

Sections over `wardrobe-store`: `capi` (piece) · `outfit` · `indossati` (wear) · `liste` (collection) · `vocabolari`
(taxonomy) · `foto` (photo rows + their Archive blobs, only with «Includi foto» or chosen by hand). On import the
blobs are uploaded first (`POST /api/transfer/files`, owner `wardrobe`) and the photo rows get the new blob ids.
Reminder rows are never exported. Settings travel through Themis.

## Configuration (infrastructure only)

`SERVICE_NAME`, `SERVICE_BASE_URL`, `HUB_API_URL`, `TZ` (local day for marks and goal), `WARDROBE_UI_DIST`.

## Tests

`python -m pytest -q -m "unit or api or format" Hestia-Wardrobe/tests` (fake Hub with Archive store and blobs in memory).
