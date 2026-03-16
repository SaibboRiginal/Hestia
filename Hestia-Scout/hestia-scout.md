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
[Scout: Entity Extractor]  ←── Internal LLM Evaluator
        │  structured listing
        ▼
[Archive: real_estate domain]
        │
        ▼
[Oracle: queries on user request]
```

1. **Startup:** Scout registers a `GmailIMAPFetcher` connector with Ingest (credentials from env).
2. **Scheduled fetch:** Scout calls Ingest to retrieve new emails from the configured Gmail account.
3. **Entity extraction:** Each raw email is passed to the internal LLM evaluator. The LLM extracts structured property data: price, location, size, features, URL, etc.
4. **Storage:** The structured listing is saved to Archive under the `real_estate` domain.
5. **Event emission:** Scout publishes `entity.upserted` event to Hermes (via Hub routing).
6. **Availability:** Oracle queries module tools / Archive for `real_estate` data.
7. **Shutdown:** Scout deregisters its Ingest connector.

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
  "raw_text": "string"
}
```

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
- `worker/runner.py`: ingest/evaluation cycle orchestration.
- `worker/extractor.py`: email sanitization, LLM extraction parsing, payload enrichment.
- `tools/retrieval.py`: module query translation + scoring/filtering.
- `tools/geocoding.py`: geocoding + distance calculations.
- `tools/schemas.py`: Pydantic request contracts.

---

## Enrichment Pipeline

After AI extraction, each entity goes through a multi-stage enrichment:

1. **Geolocation**: expanded candidate queries with ", Italia" fallback, city-only last resort.
2. **Page Atlas**: shared `Hestia-Atlas` via Hub route preferred, then local Playwright, then HTTP fallback.
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
- `[PLAYWRIGHT]`: browser launch, success/failure, content size
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
| `SCOUT_FETCH_API_URL` | Hub route endpoint to shared fetch service (recommended: `http://hestia_hub:8005/api/route/fetch/api/fetch/html`) |
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
