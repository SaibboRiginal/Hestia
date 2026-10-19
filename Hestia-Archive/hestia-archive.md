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
- **Finance store** (`/api/finance-store/*`): table `finance_records`, same shape and protocol as the Hercules store.
  Pure storage for Plutus (expenses: transactions, categories, rules, budgets, accounts, imports, recurring).
- **Iris store** (`/api/iris-store/*`): table `iris_records`, same shape and protocol. Pure storage for Iris (mail
  subscriptions, kind `subscription`, id `<owner>:<key>`).
  Both are built by the generic `routers/module_store.py` (`build_router(prefix, model)`, one table per owner module,
  own `<table>_seq` cursor): the way to add a store for a new module.
- **Blobs** (`/api/blobs`): table `blobs` (blob_id, owner_module, content_type, size, sha256, data, meta, created_at),
  deduplicated per module by sha256, max 15 MB each. Generic byte storage for module files (Wardrobe photos, Plutus
  statement PDFs; owner `chat` = chat attachments stored by Oracle for a module's attachment handler).
- **MCP access store** (`/api/mcp-access-store/*`): table `mcp_accesses` (access_id, name, kind token|oauth,
  scope read|write, tools, token_hash (sha256, unique), expires_at, revoked_at, last_used_at, calls_day/date/total,
  meta; OAuth grants also client_id, refresh_hash, prev_refresh_hash, token_expires_at), `mcp_oauth_clients`
  (client_id, name, redirect_uris, auth_method, secret_hash) and `mcp_oauth_codes` (code_hash, PKCE challenge, consent
  choices, used_at). Pure storage for Hestia-MCP (who may use Hestia's MCP from outside); no endpoint returns a hash.
- **Chat queue** (`/api/chat-queue/*`, table `chat_queue`): chat messages Oracle could not take while Oracle was
  offline; each chat client (Telegram, WebUI) queues its own and answers them when Chronos says Oracle is back
  (SPEC `docs/work/2026-10-19-oracle-offline`).
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
| `PUT`/`GET` | `/api/finance-store/records` · `GET /api/finance-store/cursor` | Plutus rows (same contract as hercules-store) (Plutus only) |
| `PUT`/`GET` | `/api/iris-store/records` · `GET /api/iris-store/cursor` | Iris rows (same contract) (Iris only) |
| `POST` | `/api/blobs` | Store bytes `{owner_module, content_type, data_base64, meta}` → meta + `deduped` |
| `GET` | `/api/blobs?owner_module=` | Blob metadata of a module |
| `GET` | `/api/blobs/{id}/meta` · `/api/blobs/{id}/base64` · `/api/blobs/{id}` | Metadata · `{blob_id, mime, data_b64}` · raw bytes |
| `DELETE` | `/api/blobs/{id}` | Delete a blob |
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
| `POST` | `/api/chat-queue` | Queue a chat message written while Oracle was offline `{client, session_id, text, target?, client_ref?, meta?}` → item + `position` |
| `GET` | `/api/chat-queue` · `/counts` | Items oldest first (`client`, `state` default `queued`) · waiting per client |
| `POST` | `/api/chat-queue/{id}/claim` · `/done` | Compare-and-set `queued → answering` (409 = someone else; a claim older than `stale_seconds` 600 is free again) · `{ok, detail}`: answered, or back to queued (failed after 5 attempts) |
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
- 2026-10-19: generic `module_store` router → `/api/finance-store` (Plutus) and `/api/iris-store` (Iris); raw mail
  records delivered by Iris land in `/api/archive` under the subscriber's domain (`reference_id = mail:<domain>:<gmail id>`).
