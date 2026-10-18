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
- Status is the daily tool: Nell'armadio · In lavanderia · Prestato · Messo via · Da riparare · Da donare · Donato ·
  Venduto · Desiderato · Archiviato. Only «Nell'armadio» pieces are suggested.
- «Indossato» is **occasional**, never assumed daily: usage numbers (most worn, cost per wear, forgotten) are hints.
  Optional goal `wardrobe.tracking.goal_times` per day/week/month; one mark per outfit per day.
- «Cosa mi metto» is deterministic (no LLM): saved outfits + combinations generated from available pieces, filtered by
  season and weather (warmth band of the upper layers, rain), scored on occasion/formality, style, colour harmony
  (≤ 1 accent colour), pattern clash, recently worn (`suggest.exclude_recent_days`), rotation of forgotten pieces,
  favourites and rating. Every result carries its reasons. The assistant adds taste on top.
- Photos: orientation fixed, metadata (GPS) dropped by re-encoding, three sizes (original JPEG/WebP, medium 768,
  thumb 256 WebP). «Riconosci con AI» sends the medium photo to Oracle `/api/llm/chat` (profile `wardrobe.ai.profile`)
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

- Tools (`wardrobe` domain via `module_tool_domains`, REST `/api/wardrobe/tools/<name>`): `guardaroba_riepilogo`,
  `guardaroba_cerca`, `guardaroba_capo`, `guardaroba_aggiungi`, `guardaroba_modifica` (status: laundry, lent…),
  `guardaroba_outfit`, `guardaroba_crea_outfit`, `guardaroba_suggerisci`, `guardaroba_indossato`,
  `guardaroba_statistiche`, `guardaroba_valigia`, `guardaroba_elimina`. Pieces and outfits are found by name.
- `guardaroba_elimina` never deletes: it asks through Hermes with **Elimina / Archivia / Tieni**.
- `GET /api/module/context?budget=` → `{module, domain, updated_at, text}`: one caveman line (counts, style, laundry,
  forgotten, last outfit, goal). Hub capability `context_endpoint`, tag `context`.

## Notifications (both off by default, through Hermes, target `owner`)

- Agenda job `wardrobe.reminder` (daily 08:30, time editable in the agenda) → `POST /api/wardrobe/reminder/check`.
  Sends only when `wardrobe.reminder.enabled`, a goal exists, nothing marked today, the goal is behind (or daily) and
  under `wardrobe.reminder.max_per_week`. One live reminder (`replaces: wardrobe.reminder`), actions = favourite
  outfits (`resolves: true`) + **Salta**. Marking from anywhere closes it (`closes` + decision done).
- Agenda job `wardrobe.review` (first Sunday of the month 10:00) → `POST /api/wardrobe/review/run` when
  `wardrobe.review.enabled`: forgotten, to repair, long in laundry, outfits to review.

## Client UI (plugin contract)

Bundle `ui/src/index.ts` → `/ui/webui/wardrobe.js` (built in the Dockerfile). Pages: capi, capi/:id, accessori,
outfit, outfit/:id, cosa-mi-metto, statistiche, liste, liste/:id, vocabolari. Widgets: oggi (auto, one-tap
«Indossato» chips), suggerito, lavanderia, dimenticati (auto), numeri (auto), ultimi. Quick action `indossato`
(chips = favourite outfits + today's idea, undo). Multi-select on Guardaroba: In lavanderia / Nell'armadio /
Crea outfit / Da donare. A UI change needs `up-all.bat --build wardrobe`.

## Settings (Themis, `wardrobe.*`)

forgotten_days (180), currency (EUR), photo.max_mb (10), suggest.count (3), suggest.exclude_recent_days (4),
tracking.goal_times (0 = no goal), tracking.goal_per (week), reminder.enabled (false), reminder.max_per_week (2),
review.enabled (false), ai.profile (cloud).

## API (via Hub `/route/wardrobe/...`)

See `Hestia-Swagger/swagger.yml` tag *Wardrobe*. Groups: meta, vocabularies, pieces (+bulk, photos, cover),
files/{photo_id} (`{mime, data_b64}`), outfits (+photos, worn), wears, suggest (+save), stats, summary,
collections (+packing, check), describe-photo, export/import (JSON), quick (Home chips), reminder/check,
reminder/skip, review/run.

## Configuration (infrastructure only)

`SERVICE_NAME`, `SERVICE_BASE_URL`, `HUB_API_URL`, `TZ` (local day for marks and goal), `WARDROBE_UI_DIST`.

## Tests

`python -m pytest -q -m "unit or format" Hestia-Wardrobe/tests` (fake Hub with Archive store and blobs in memory).
