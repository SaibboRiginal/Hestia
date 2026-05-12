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
[Ingest: GmailIMAPFetcher]
        │  raw emails
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

1. **Startup:** Scout registers a `GmailIMAPFetcher` connector with Ingest (credentials from env).
2. **Scheduled fetch:** Scout calls Ingest to retrieve new emails from the configured Gmail account.
3. **Pre-parse (no LLM):** `pre_parser.py` strips HTML, extracts `[PROPERTY_LINK: url]` markers from every record. Builds a `url → record_id` map and a `record_id → clean_text` map.
4. **Deduplication:** `archive_client.get_all_entity_ids()` fetches all known property URLs from Archive. New vs. existing URLs are classified without any LLM call.
5. **Status update path (existing):** For known entities whose URL appeared in the new emails, `StatusUpdater` runs a regex keyword scan on the email text to detect `listing_status` changes (`available → in_negotiation → sold` etc.). If the status changed, only the `listing_status` field is patched in Archive — no full LLM extraction.
6. **Representative record selection (new):** `select_representative_records()` picks the richest (longest-text) email per new URL, producing a minimal set that covers all new URLs.
7. **LLM extraction (new entities only):** The minimal representative set is passed to the LLM extractor in batches. The LLM extracts structured property data including `listing_status`.
8. **Storage:** Structured listings are saved to Archive under the `real_estate` domain.
9. **Event emission:** Scout publishes `entity.upserted` event to Hermes (via Hub routing).
10. **Mark parsed:** All processed Ingest records are marked parsed regardless of which path handled them.
11. **Availability:** Oracle queries module tools / Archive for `real_estate` data.
12. **Shutdown:** Scout deregisters its Ingest connector.

---

## Internal LLM Evaluator

Scout manages its own LLM connector independently from Oracle. This is intentional — batch entity extraction and conversational inference are separate concerns with different latency and cost profiles.

- Switchable between cloud providers and local Ollama via env config.
- Used only for structured extraction — not for conversation.

---

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

Scout also runs on an internal schedule (configurable interval via env).

### Worker batching policy
- `min_batch_size=1` (no hard wait for 5 items)
- debounce window before processing to accumulate near-simultaneous mails
- `max_batch_size=5` per model call
- cooldown between batches for quota safety

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

## Configuration (env)

| Variable | Description |
|---|---|
| `GMAIL_EMAIL` | Gmail account to fetch from |
| `GMAIL_PASSWORD` | App password for IMAP |
| `GMAIL_FOLDER` | Mailbox folder to watch (e.g. `Immobiliare`) |
| `SCOUT_EMAIL_SENDERS` | Comma-separated sender list used to build IMAP filters (e.g. `nonrispondere@idealista.it,noreply@notifiche.immobiliare.it`) |
| `SCOUT_FILTER_QUERIES` | Optional advanced IMAP filters separated by `\|\|` (overrides sender list) |
| `SCOUT_FETCH_API_URL` | Hub route endpoint to shared fetch service (recommended: `http://hestia_hub:19001/api/route/atlas/api/fetch/html`) |
| `SCOUT_FETCH_VIA_HUB` | `true` to send route-envelope payload to Hub, `false` for direct fetch service call |
| `LLM_PROVIDER` | `ollama` or `cloud` |
| `LLM_MODEL` | Model name (e.g. `llama3`, `gpt-4o`) |
| `FETCH_INTERVAL_MINUTES` | How often to run the pipeline |

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
