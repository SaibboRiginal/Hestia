# Hestia-Archive 🗄️

**Role:** Generic Storage + Query Gateway
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · PostgreSQL + pgvector · Docker

---

## Responsibility

Archive is the only database access service in Hestia.
It stores and serves all persistent state through generic APIs.

---

## Data Areas

- Raw records (`/api/archive`)
- Processed entities (`/api/entities`)
- Chat sessions (`/api/chat/history`)
- User memory/preferences (`/api/memory`)
- **Alert subscriptions** (`/api/subscriptions`) for proactive dispatch
- **Dispatch delivery log** (`/api/dispatch/logs`) for auditing and dedupe
- **Settings store** (`/api/settings-store/*`): tables `setting_values`, `setting_history` (last 10 per key,
  trimmed on write), `setting_proposals`. Pure storage: meaning, validation and permissions live in Themis,
  its only caller.
- **Hercules store** (`/api/hercules-store/*`): table `hercules_records` (kind, id, parent_id, ref_id, at, data JSONB,
  updated_at, deleted, seq). Last-write-wins writes, tombstones, `seq` cursor for sync. Pure storage for Hercules.
- **Self care store** (`/api/selfcare-store/*`): table `selfcare_records`, same columns and protocol as the Hercules
  store. Pure storage for Hygieia.
- **Wardrobe store** (`/api/wardrobe-store/*`): table `wardrobe_records`, same shape and rules as the Hercules store.
  Pure storage for Wardrobe.
- **Blobs** (`/api/blobs`): table `blobs` (blob_id, owner_module, content_type, size, sha256, data, meta, created_at),
  deduplicated per module by sha256, max 15 MB each. Generic byte storage for module files (Wardrobe photos first).
- **MCP access store** (`/api/mcp-access-store/*`): table `mcp_accesses` (access_id, name, kind token|oauth,
  scope read|write, tools, token_hash (sha256, unique), expires_at, revoked_at, last_used_at, calls_day/date/total,
  meta; OAuth grants also client_id, refresh_hash, prev_refresh_hash, token_expires_at), `mcp_oauth_clients`
  (client_id, name, redirect_uris, auth_method, secret_hash) and `mcp_oauth_codes` (code_hash, PKCE challenge, consent
  choices, used_at). Pure storage for Hestia-MCP (who may use Hestia's MCP from outside); no endpoint returns a hash.
- **LLM usage store** (`/api/llm-usage-store/*`, Oracle only, dossier `docs/work/2026-10-19-oracle-a-blocchi` §E):
  table `llm_usage`, one row per LLM call (at, module, use_case, chain, step, provider, model, client, session_id,
  input/cached/output tokens, context_window, duration_ms, cost_usd, cost_kind, outcome, detail). Oracle sends its
  retention with each write and older rows are deleted then (no timer).
- **Presence store** (`/api/presence-store/*`): tables `presence_signals` (key, value, meta, expires_at),
  `presence_snapshot` (one row), `presence_changes` (last 100). Pure storage for Chronos' presence engine.

---

## API Highlights

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/entities` | Upsert one entity |
| `POST` | `/api/entities/search` | Generic hybrid search |
| `GET` | `/api/entities/records` | Raw rows (domain, status, limit); `include_embedding=false` drops the vectors (module UIs) |
| `POST` | `/api/module/maintenance/reconcile` | Run generic maintenance reconcile (standard contract) |
| `POST` | `/api/maintenance/reconcile` | Compatibility alias for maintenance reconcile |
| `GET` | `/api/memory/active` | Active preferences |
| `POST` | `/api/subscriptions` | Create/update subscription |
| `GET` | `/api/subscriptions/active` | List active subscriptions |
| `POST` | `/api/dispatch/logs` | Write delivery result |
| `GET`/`PUT`/`DELETE` | `/api/settings-store/values` | Setting values (Themis only) |
| `GET` | `/api/settings-store/history` | Setting change log |
| `GET`/`POST`/`PATCH` | `/api/settings-store/proposals[/{id}]` | Assistant proposals (first answer wins) |
| `PUT` | `/api/hercules-store/records` | Upsert rows (LWW; newer stored rows returned in `stale`) (Hercules only) |
| `GET` | `/api/hercules-store/records` | Rows by kind/parent/ref/ids/at range/`since_seq` |
| `GET` | `/api/hercules-store/cursor` | Current sync cursor |
| `PUT` | `/api/selfcare-store/records` | Upsert rows (LWW; newer stored rows returned in `stale`) (Hygieia only) |
| `GET` | `/api/selfcare-store/records` | Rows by kind/parent/ref/ids/at range/`since_seq` |
| `GET` | `/api/selfcare-store/cursor` | Current cursor |
| `PUT`/`GET` | `/api/wardrobe-store/records` | Wardrobe rows (same contract as hercules-store) (Wardrobe only) |
| `GET` | `/api/wardrobe-store/cursor` | Current sync cursor |
| `POST` | `/api/blobs` | Store bytes `{owner_module, content_type, data_base64, meta}` → meta + `deduped` |
| `GET` | `/api/blobs?owner_module=` | Blob metadata of a module |
| `GET` | `/api/blobs/{id}/meta` · `/api/blobs/{id}/base64` · `/api/blobs/{id}` | Metadata · `{blob_id, mime, data_b64}` · raw bytes |
| `DELETE` | `/api/blobs/{id}` | Delete a blob |
| `POST` | `/api/llm-usage-store/rows` | `{rows: [...], retention_days}` (≤ 500 rows) → `{written, removed}` (Oracle only) |
| `GET` | `/api/llm-usage-store/summary?group=module\|session\|usecase\|model\|step\|day&days=&module=&session_id=&use_case=` | Sums per group: calls, ok, errors, quota, fallbacks, tokens, cost, avg duration, largest prompt, window, first/last |
| `GET` | `/api/llm-usage-store/rows?session_id=&days=&limit=` | Latest single calls, newest first |
| `GET`/`POST` | `/api/mcp-access-store/accesses` | MCP accesses (Hestia-MCP only): list · create `{access_id, name, kind, scope, tools, token_hash, expires_at}` |
| `GET` | `/api/mcp-access-store/accesses/by-hash/{sha256}` | Access of a token (404 = unknown) |
| `PATCH`/`DELETE` | `/api/mcp-access-store/accesses/{id}` | Change (name, scope, tools, token_hash, expiry, `revoked`) · delete |
| `POST` | `/api/mcp-access-store/accesses/{id}/used` | One call made: last use + counters |
| `GET` | `/api/mcp-access-store/accesses/by-refresh/{sha256}` | Access of an OAuth refresh token (`reused: true` = the previous one, a replay) |
| `POST` | `/api/mcp-access-store/accesses/{id}/rotate` | New token + refresh hashes, only if `old_refresh_hash` is current (409 otherwise) |
| `GET`/`POST` | `/api/mcp-access-store/oauth/clients` | OAuth clients (no secret hash) · store a registered one |
| `GET`/`DELETE` | `/api/mcp-access-store/oauth/clients/{id}` · `POST …/check-secret` | One client · delete · `{secret_hash}` matches? → `{ok}` |
| `POST` | `/api/mcp-access-store/oauth/codes` · `/oauth/codes/consume` | Store a code · use it once (`reused` + the access it became on a replay) |
| `GET` | `/api/presence-store` | Presence signals (expired purged) + snapshot (Chronos only) |
| `PUT`/`DELETE` | `/api/presence-store/signals/{key}` | Presence signal |
| `PUT` | `/api/presence-store/snapshot` | Snapshot + optional change appended to history |
| `GET` | `/api/presence-store/history` | Presence state changes |
| `GET` | `/health` | Archive health |

---

## Constraints

- No domain-specific ranking/business rules.
- No notification dispatch decisions.
- No module-specific parsing.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Recent fixes / contract notes

- `GET /api/memory/active` now honours `memory_class` and `limit` (were ignored: skill lifecycle saw user preferences).
- `PATCH /api/memory/{id}`: every field optional (`is_active`, `weight`, `extra_data` merge).
- `POST /api/memory/search/similar`: pgvector values are numpy arrays — they were skipped, so results were always empty.
  Response no longer echoes the embedding.
- `POST /api/entities/search`: numeric filters (`filters_gt/lt`) evaluated over a wider window (was LIMIT 100 before
  filtering) and parsed leniently (`"350.000 €"`); unparsable values exclude the row instead of failing the search.
- `calendar_items.meta` (JSONB, auto-migrated with `ALTER TABLE … ADD COLUMN IF NOT EXISTS`) holds assistant-agenda
  metadata (type, owner, action, skips, rules). Upserts without `meta` keep the stored value.
- New `GET /api/chat/sessions?since=` → `{sessions: [...]}` distinct session ids (Athena consolidator).
- Session summaries for Athena skills are stored as entities with `domain=session_summary`.
- Startup waits for Postgres (`ARCHIVE_DB_WAIT_SECONDS`, 0 = forever) and re-registers on Hub every
  `HUB_KEEPALIVE_SECONDS` (Hub restarts no longer drop Archive).
