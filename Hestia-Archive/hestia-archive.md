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
- **Presence store** (`/api/presence-store/*`): tables `presence_signals` (key, value, meta, expires_at),
  `presence_snapshot` (one row), `presence_changes` (last 100). Pure storage for Chronos' presence engine.

---

## API Highlights

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/entities` | Upsert one entity |
| `POST` | `/api/entities/search` | Generic hybrid search |
| `POST` | `/api/module/maintenance/reconcile` | Run generic maintenance reconcile (standard contract) |
| `POST` | `/api/maintenance/reconcile` | Compatibility alias for maintenance reconcile |
| `GET` | `/api/memory/active` | Active preferences |
| `POST` | `/api/subscriptions` | Create/update subscription |
| `GET` | `/api/subscriptions/active` | List active subscriptions |
| `POST` | `/api/dispatch/logs` | Write delivery result |
| `GET`/`PUT`/`DELETE` | `/api/settings-store/values` | Setting values (Themis only) |
| `GET` | `/api/settings-store/history` | Setting change log |
| `GET`/`POST`/`PATCH` | `/api/settings-store/proposals[/{id}]` | Assistant proposals (first answer wins) |
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
