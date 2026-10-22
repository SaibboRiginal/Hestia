# Hestia-Scout 🏠

**Role:** Domain Module — House Hunting
**Node:** Main PC (High-Power)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

Finds, extracts, and evaluates real estate listings from email alerts. Owns the `real_estate` domain in Archive. Scout is the first domain module and serves as the reference implementation for future modules.

Scout is also an event producer for proactive workflows: when entities are created/updated, Scout emits generic domain events for Hermes.

---

## Pipeline

```
[Hecate watcher → Iris dispatch]  ← push: Iris stores listing mails in Archive, rings /api/scout/mail
        │  raw emails (Archive, real_estate, unevaluated)
        ▼
[Scout: pre_parser.py]          ← URL extraction, zero LLM calls
        │  url→record_id map
        ▼
[Archive: get_all_entity_ids]   ← known URL deduplication
        │
        ├─ known entities ──► [StatusUpdater]  ← keyword status scan only
        │
        └─ new entities  ──► [select_representative_records]
                                     │  minimal email set covering all new URLs
                                     ▼
                             [Extractor: LLM batches]
                                     │  structured listing + listing_status
                                     ▼
                             [Archive: real_estate domain]
                                     │
                                     ▼
                             [Hermes: entity.upserted event]
```

1. **Startup:** Scout subscribes to Iris (`MailClient("scout")`, key `listings`, rules from `scout.mail.*`) and runs one cycle on the mails that arrived while it was down.
2. **Push:** Hecate's watcher sees new mail, Iris stores the matching ones in Archive (`real_estate`, `reference_id = mail:real_estate:<gmail id>`) and calls `POST /api/scout/mail` → the cycle runs on the unevaluated records. Scout never polls mail.
3. **Pre-parse (no LLM):** `pre_parser.py` strips HTML, extracts `[PROPERTY_LINK: url]` markers from every record. Builds a `url → record_id` map and a `record_id → clean_text` map.
4. **Deduplication:** `archive_client.get_all_entity_ids()` fetches all known property URLs from Archive. New vs. existing URLs are classified without any LLM call.
5. **Status update path (existing):** For known entities whose URL appeared in the new emails, `StatusUpdater` runs a regex keyword scan on the email text to detect `listing_status` changes (`available → in_negotiation → sold` etc.). If the status changed, only the `listing_status` field is patched in Archive — no full LLM extraction.
6. **Representative record selection (new):** `select_representative_records()` picks the richest (longest-text) email per new URL, producing a minimal set that covers all new URLs.
7. **LLM extraction (new entities only):** The minimal representative set is passed to the LLM extractor in batches. The LLM extracts structured property data including `listing_status`.
8. **Storage:** Structured listings are saved to Archive under the `real_estate` domain.
9. **Event emission:** Scout publishes `entity.upserted` event to Hermes (via Hub routing).
10. **Mark parsed:** All processed mail records are marked parsed regardless of which path handled them.
11. **Availability:** Oracle queries module tools / Archive for `real_estate` data.
12. **Shutdown:** nothing to stop (no polling; mails arriving meanwhile wait in Archive).

---

## LLM Extractor (via Oracle)

Extraction calls Oracle `POST /api/llm/generate` through Hub (`evaluators/oracle_evaluator.py`) with
`{"prompt", "use_case": "scout.annunci"}`: Oracle owns provider keys **and the model choice**. Scout declares the use
case in its Hub registration (`capabilities.llm_usecases`, `hestia_common.oracle_usecases`, suggested chain `veloce`);
Marko picks its chain in Oracle → Cervello → Modelli. A model out of quota (429) is skipped and the next step of the
chain answers (the old `SCOUT_LLM_MODELS` hop). No Scout env var for the model.

Per-call timeout = central setting `scout.llm.timeout` (default 120 s, live).

Provider keys live only in Oracle (`ORACLE_KEY_<NAME>`). (Previously Scout embedded its own Gemini client and key; the unused
`OllamaEvaluator` was removed.)

## Data Model: `real_estate` Listing

```json
{
  "id": "uuid",
  "source": "gmail",
  "raw_email_id": "string",
  "fetched_at": "datetime",
  "processed_at": "datetime",
  "price": "number | null",
  "location": "string | null",
  "size_sqm": "number | null",
  "rooms": "number | null",
  "features": ["string"],
  "url": "string | null",
  "summary": "string",
  "score": "number | null",
  "raw_text": "string",
  "listing_status": "available | in_negotiation | investment_occupied | sold | unknown"
}
```

### Listing Status (`listing_status`)

`ListingStatus` is a standardized enum (`domain/listing_status.py`).

| Value | Meaning |
|---|---|
| `available` | Actively on market |
| `in_negotiation` | Offer made / under contract |
| `investment_occupied` | Sold as investment, tenant still occupying |
| `sold` | Transaction closed |
| `unknown` | Not yet determined |

- **New entities:** the LLM extractor outputs `listing_status` as part of its JSON; `coerce_listing_status()` maps LLM strings safely to the enum.
- **Existing entities:** `StatusUpdater` runs a priority-ordered regex keyword scan on the raw email text. If a higher-priority status is detected and differs from the stored value, only `listing_status` is patched — no full LLM call.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health |
| `GET` | `/api/module-tools/domains` | Lists domains exposed by this module |
| `POST` | `/api/module-tools/query` | Generic module-tool query contract (domain + query + constraints) |
| `GET` | `/api/tools` | Optional module-local tool listing |
| `POST` | `/api/tools/real_estate/search` | Optional direct domain endpoint (internal/debug use) |
| `POST` | `/api/module/maintenance/reconcile` | Run standardized module maintenance reconcile |
| `POST` | `/api/maintenance/reconcile` | Compatibility alias for module maintenance reconcile |
| `POST` | `/api/scout/cycle` | Run the email → listings cycle `{trigger, wait}` (default async; one cycle at a time, `busy` otherwise) |
| `GET` | `/api/scout/cycle` | Cycle state: running, last start/finish/trigger/error, `mail: push`, subscription `scout:listings` |
| `POST` | `/api/scout/mail` | Iris doorbell `{owner, key, domain, count, reference_ids, source}` → runs the cycle (async) on the pending records |
| `POST` | `/api/scout/check` | «Controlla email»: Iris backfill of the last day + cycle (MCP tool `scout_fetch`) |
| `GET` | `/api/ui/manifest` | WebUI plugin manifest (`hestia_common.plugin_client`) |
| `GET` | `/ui/webui/scout.js` | Plugin bundle (built in the image from `ui/`) |
| `GET` | `/api/ui/listings` | Listings for the plugin: `q, city, status, flag (''=da valutare, favorite, discarded, all), price_min/max, rooms_min, surface_min, days, sort (new, price_asc, price_desc, ppm2, surface), offset, limit` → `{total, items, cities, statuses}` |
| `GET` | `/api/ui/listings/{key}` | One listing with photos, features, summary (`key` = 12 hex of sha1(entity_id)) |
| `PATCH` | `/api/ui/listings/{key}` | `{flag?: favorite\|discarded\|'', status?: ListingStatus}` |
| `POST/DELETE` | `/api/ui/listings/{key}/favorite` | Quick action "Preferita" and its undo |
| `GET` | `/api/ui/stats?city=` | KPI, new per week (8), by status, price by city, cities |
| `GET` | `/api/ui/quick/new` | Home chips: newest listings not yet marked |
| `POST/GET` | `/api/ui/cycle` | POST = same as `/api/scout/check` (backfill + cycle); GET = cycle state, for the plugin |

### WebUI plugin (2026-10-17, dossier `docs/work/2026-10-17-client-plugins/`)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Favourite badge text «preferita»; address map-pin.

`app/ui_api.py` declares the plugin and serves its data; `ui/src/` is the Lit bundle (built with the shared SDK in
the Node stage of the Dockerfile; `ui/dist/` is git-ignored). The image keeps the bundle in `/ui/dist`
(`SCOUT_UI_DIST`), outside `/code`, because compose mounts `Hestia-Scout/app` over `/code`.
- Pages: **Case** (`/p/scout/case`: KPI, search, città, ordinamento, Da valutare/Preferite/Scartate/Tutte, prezzo
  max, locali, stato; cards with ☆ Preferita and Scarta + Annulla), **Annuncio** (`case/:key`: photos, facts,
  features, description, map link, "Apri annuncio", "Chiedi a Hestia", status correction), **Statistiche case**.
- Widgets: *Case in numeri* and *Nuove case* (param città, giorni) on the automatic Home; *Case preferite*,
  *Prezzi per città*. Quick actions: "Controlla email annunci", and the newest unmarked listings as chips (tap =
  Preferita, Annulla in the toast).
- Writes only `user_flag` (`favorite`/`discarded`, cleared as `none` because Archive keeps old values on empty)
  and `listing_status` in the Archive payload. Reads `GET /api/entities/records?include_embedding=false`, cached 30 s.
- `entity.upserted` events carry `_link: {module: scout, page: case/<key>, list: case}`; the WebUI notification gets
  an "Apri" button (several listings in one batch → the list page).

### Mail by push (Iris subscription, 2026-10-19)

Scout has **no mail polling job**. At boot it subscribes to Iris (`hestia_common.mail_client`, subscription
`scout:listings`, path `/api/scout/mail`, domain `real_estate`; senders from `scout.mail.senders`, or the Gmail queries
of `scout.mail.filter_queries` when set), re-asserted hourly and refreshed at once when those settings change. A new
or changed rule gets a 7-day backfill from Iris. One cycle runs at boot for mails that waited in Archive.
The old 30-minute agenda job `scout.email_cycle` is retired on existing installs (`AgendaClient.retire`), and the
setting `scout.cycle.interval`, the agenda template `extra_check` and the fallback loop are gone.
«Controlla ora» (plugin quick action, `scout_fetch`) = Iris backfill (last day) + cycle. Reconcile/enrichment keep
their own cadence (`scout.reconcile.every_cycles` counts cycles, now one per push).

### Worker batching policy
- `scout.batch.min_size=1` (no hard wait for 5 items)
- debounce window (`scout.batch.debounce`, 45 s) before processing to accumulate near-simultaneous mails
- `scout.batch.max_size=5` per model call
- cooldown between batches (`scout.batch.cooldown`, 15 s) for quota safety

## Internal Architecture (SoC)

- `main.py`: thin composition and API wiring.
- `worker/runner.py`: ingest/evaluation cycle orchestration (7-phase pipeline).
- `worker/pre_parser.py`: zero-LLM URL extraction from email HTML; produces `url→record_id` and `record_id→clean_text` maps.
- `worker/status_updater.py`: keyword-based `listing_status` scan for existing entities; patches Archive without LLM.
- `worker/extractor.py`: email sanitization, LLM extraction, payload enrichment (geocoding, Atlas page scrape).
- `domain/listing_status.py`: `ListingStatus` enum, `detect_listing_status()` regex scanner, `coerce_listing_status()` safe mapper.
- `domain/house_entity.py`: `HouseEntity` and `HousePayload` Pydantic models.
- `core/archive_client.py`: Archive API client including `get_all_entity_ids()` and `get_entity_by_id()`.
- `tools/retrieval.py`: module query translation + scoring/filtering.
- `tools/geocoding.py`: geocoding + distance calculations.
- `tools/schemas.py`: Pydantic request contracts.

---

## Enrichment Pipeline

After AI extraction, each entity goes through a multi-stage enrichment:

1. **Geolocation**: expanded candidate queries with ", Italia" fallback, city-only last resort.
2. **Page retrieval**: shared `Hestia-Atlas` via Hub route (`/api/route/atlas/api/fetch/html`) as the standard fetch path.
3. **Data Extraction** from page (in priority order):
   - JSON-LD structured data
   - Embedded JSON in script tags
   - OpenGraph / meta description tags
   - Visible page content (CSS selectors for description containers)
   - Address from page headings/selectors
4. **Summary Quality**: truncated summaries (ending in "...") are penalized heavily; page extraction is re-attempted if summary is truncated or too short.
5. **Normalization**: short truncated-only summaries are stripped entirely.

---

## Logging Contract

All extraction and enrichment steps log with tagged prefixes:
- `[AI-RAW]`: raw data from LLM extraction (summary length, truncation flag)
- `[ENRICH]`: pre/post enrichment state (fetch method, summary length, address, truncation)
- `[EXTRACT]`: per-stage extraction progress (JSON-LD count, summary length at each step)
- `[ENTITY]`: final entity state before upsert (address, geo, summary quality)

Truncation warnings are always logged when a summary still ends with "..." after enrichment.

## Geolocation Strategy

- Scout enriches extracted entities with coordinates (`payload.location.lat/lon`) using geocoding of address text.
- Nearby search is distance-based using stored coordinates and a configurable radius (no hardcoded city-neighbor map).

---

## Central settings (Themis)

Declared in `app/core/scout_settings.py` (owner `scout`), all `apply=live` (read at the point of use);
`GET /api/settings/effective` and `POST /api/settings/reload` are mounted for Themis.

| Key | Type | Default | Effect |
|---|---|---|---|
| `scout.mail.senders` | list | `nonrispondere@idealista.it`, `noreply@notifiche.immobiliare.it` | Portal senders (addresses or domains) → `senders` of the Iris subscription |
| `scout.mail.filter_queries` | list | `[]` | Explicit Gmail queries (advanced, `queries` of the subscription); non-empty → senders ignored |
| `scout.batch.min_size` | int | `1` | Min new emails before extraction |
| `scout.batch.max_size` | int | `5` | Emails per model call |
| `scout.batch.debounce` | int (s) | `45` | Wait to gather near-simultaneous mails (0 = none) |
| `scout.batch.cooldown` | int (s) | `15` | Pause between model batches (quota) |
| `scout.llm.timeout` | int (s) | `120` | Per-call timeout of the Oracle extraction call |
| `scout.reconcile.every_cycles` | int | `1` | Reconcile stored entities every N cycles (0 = never) |
| `scout.enrichment.enabled` | bool | `true` | Listing-page enrichment + retry of pending enrichments |
| `scout.log.level` | enum | boot `LOG_LEVEL` | Log verbosity (live) |

## Export and import (`/api/transfer/*`, dossier `docs/work/2026-10-20-import-export`)

One section `annunci`: the active listings of Scout's domain in Archive (payload with the user's marks
`user_flag`, `listing_status`). Import upserts through Archive's entity merge; «Sostituisci» never deletes (the
mail cycle brings listings back anyway). Settings travel through Themis.

## Configuration (env: infrastructure only)

| Variable | Description |
|---|---|
| `HUB_API_URL` / `ARCHIVE_API_URL` | Hub / Archive base URLs |
| `SCOUT_SERVICE_BASE_URL` / `SCOUT_TOOLS_PORT` / `SCOUT_SERVICE_VERSION` | Hub registration + listening port |
| `STARTUP_WAIT_TIMEOUT_SECONDS` | Startup wait for Hub/dependencies (0 = forever) |
| `LOG_LEVEL` | Boot log level only (live value = `scout.log.level`) |
| `SCOUT_DEBUG_*` | Only for the `scout_debug.py` developer CLI (output paths/print toggles), not the service |

---

## Constraints

- Scout never accesses the database directly — all reads/writes go through Archive.
- Scout never calls Oracle — it only produces data for Oracle to consume.
- Scout never processes data that isn't in the `real_estate` domain.
- LLM evaluator is internal to Scout and not shared with other services.
- Scout emits generic events only (`event_type`, `domain`, `entity_id`, `payload`) without notification channel logic.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
