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
- **Signals store** (`/api/signals-store/*`): table `signal_records`, same shape and protocol. Reflection layer
  (`docs/work/2026-10-20-riflessione-a-livelli`): modules write their signals (`kind=signal`, id `<module>:<key>`) and
  weekly metrics (`kind=metric`, id `<module>:<name>:<YYYY-Www>`) with `ref_id=<module>`, `parent_id=<domain>`; Athena
  writes its observations (`kind=observation`, `ref_id=athena`). Shape in `hestia_common.signals_client`.
  All are built by the generic `routers/module_store.py` (`build_router(prefix, model)`, one table per owner module,
  own `<table>_seq` cursor): the way to add a store for a new module.
- **Blobs** (`/api/blobs`): table `blobs` (blob_id, owner_module, content_type, size, sha256, data, meta, created_at),
  deduplicated per module by sha256, max 15 MB each. Generic byte storage for module files (Wardrobe photos, Plutus
  statement PDFs; owner `chat` = chat attachments stored by Oracle for a module's attachment handler).
- **MCP access store** (`/api/mcp-access-store/*`): table `mcp_accesses` (access_id, name, kind token|oauth,
  scope read|write, tools, token_hash (sha256, unique), expires_at, revoked_at, last_used_at, calls_day/date/total,
  meta; OAuth grants also client_id, refresh_hash, prev_refresh_hash, token_expires_at), `mcp_oauth_clients`
  (client_id, name, redirect_uris, auth_method, secret_hash) and `mcp_oauth_codes` (code_hash, PKCE challenge, consent
  choices, used_at). Pure storage for Hestia-MCP (who may use Hestia's MCP from outside); no endpoint returns a hash.
- **LLM usage store** (`/api/llm-usage-store/*`, Oracle only, dossier `docs/work/2026-10-19-oracle-a-blocchi` §E):
  table `llm_usage`, one row per LLM call (at, module, use_case, chain, step, provider, model, client, session_id,
  input/cached/output tokens, context_window, duration_ms, cost_usd, cost_kind, outcome, detail). Oracle sends its
  retention with each write and older rows are deleted then (no timer).
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
| `PUT`/`GET` | `/api/signals-store/records` · `GET /api/signals-store/cursor` | reflection signals / metrics (each module its own rows) and Athena observations |
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
| `POST` | `/api/chat-queue` | Queue a chat message written while Oracle was offline `{client, session_id, text, target?, client_ref?, meta?}` → item + `position` |
| `GET` | `/api/chat-queue` · `/counts` | Items oldest first (`client`, `state` default `queued`) · waiting per client |
| `POST` | `/api/chat-queue/{id}/claim` · `/done` | Compare-and-set `queued → answering` (409 = someone else; a claim older than `stale_seconds` 600 is free again) · `{ok, detail}`: answered, or back to queued (failed after 5 attempts) |
| `GET` | `/health` | Archive health |

| `GET` | `/api/backup/status` | Backup panel state: `job {kind, step}`, `last_backup`, `last_verify`, `last_restore`, `problem`, `passphrase_set`, `drive {connected, scope_ok}`, `undo_available`, `settings` (`?fresh=true` re-checks Drive). Answers also during the rollback swap |
| `GET` | `/api/backup/list` | History = the Drive folder `.hestia/backup` (`items` with `verify`/`verified_at`/`monthly`) + `pending` (local copies waiting for Drive) + `error` |
| `POST` | `/api/backup/run` · `/verify` `{file_id?}` | Start a backup · a verification (newest when no id); answer at once (`started`), 409 `busy` while another job runs. Agenda jobs `archive.backup` (daily 03:30) and `archive.backup_verify` (1st of the month 04:00) |
| `POST` | `/api/backup/restore` `{file_id | local, confirm: true}` · `/undo` `{confirm: true}` | Rollback to a backup · swap back with the database kept from before the rollback (404 `nothing_to_undo`) |
| `POST` | `/api/backup/drive/connect` | Google authorization link from Hecate (panel «Collega Google Drive») |

---

## Backup on Google Drive (docs/work/2026-10-20-backup-drive)

- **What:** every night (agenda rule «Backup», editable) the whole `hestia_memory` database: `pg_dump -Fc` and the
  row count of every table taken from **one snapshot**, wrapped with a JSON manifest and encrypted with
  `hestia_common.crypto` (scrypt + AES-256-GCM, passphrase `HESTIA_BACKUP_PASSPHRASE` from the root `.env`), uploaded
  in 2 MB chunks through Hub to Hecate's Drive API (`.hestia/backup/hestia-backup-AAAA-MM-GG-HHMMSS.enc`, scope
  `drive.file`: Hestia sees only its own files). No passphrase → no backup and a notice. **Lost passphrase = the
  backups cannot be opened.**
- **Drive unreachable / not authorized:** the encrypted copy waits in the volume `hestia_archive_backups`
  (`/code/backups/pending`, at most 3) and goes up first at the next run; a notice with «Ricollega Google».
- **Retention** (Themis, group «Backup»): `archive.backup.keep_daily` (3) newest + the first backup of each of the last
  `archive.backup.keep_monthly` (3) months; the rest goes to the Drive trash. The newest is never removed.
- **Verification** (agenda «Verifica backup», monthly, or «Verifica ora»): download, sha256, decrypt, restore into the
  scratch database `hestia_restore_check`, compare the counts with the manifest, drop it, write `verify`/`verified_at`
  into the file's appProperties. Failure → notice.
- **Rollback** (Impostazioni → Sistema → Archive → Backup → «Ripristina»): restore into `hestia_memory_restore`, run the
  schema migrations (`app/schema.py`, an old backup gains today's tables/columns), compare counts; only then the
  **swap**: the maintenance gate answers 503 for a few seconds (except `/health` and `/api/backup/status`), Archive
  closes its connections, `hestia_memory` → `hestia_memory_prev`, `hestia_memory_restore` → `hestia_memory`. A new
  **data epoch** (`/code/backups/epoch`) is returned by every module store (`epoch` in `GET …-store/records|cursor`):
  Hercules, Hygieia, Wardrobe and Plutus drop their mirror when it changes and reload, so no stale row is written back.
  «Annulla ripristino» (`/undo`) exchanges `hestia_memory` and `hestia_memory_prev` (again = redo); the next rollback
  replaces `_prev`.
- **State** (job, last results, problem) lives in `/code/backups/state.json`, not in the database (a rollback replaces it);
  the history is the Drive folder itself.
- **Image:** `postgresql-client-15/16/17` from the PGDG repository (`ARG PG_CLIENTS`); the client matching the server major
  is used (`/usr/lib/postgresql/<major>/bin`), else the closest newer.
- **Panel:** Archive ships a plugin bundle (`ui/` → `archive.js`) with one `settings_panel` (`archive-backup-panel`), shown by
  the WebUI under Archive's settings. Texts name no module.
- **Not in the backup:** `.env`, Hecate's Google token (`Hestia-Hecate/data`), other volumes, Forge worktrees.
- **New PC:** install, set `HESTIA_BACKUP_PASSPHRASE`, start, connect Google once, open the Backup panel, «Ripristina».
- **Terminal** (no WebUI yet, or a file downloaded by hand): `python tools/hestia_backup.py list | status | restore <name>
  | restore --file <path.enc> | undo | decrypt <path.enc>`. It runs `python -m app.backup.cli` in `hestia_archive`, which
  calls this same API (gate and epoch as in the panel) and asks to type `RIPRISTINA`; `--file` copies the file to
  `/code/backups/import/` and restores it with `{local: <name>}`; `decrypt` writes the plain `pg_dump` next to the file.
- Logs: `event=backup_step kind=… step=…`, `backup_done`, `backup_failed`, `backup_verify ok=…`, `backup_restore ok=…`,
  `[🔄] backup_problem code=…`, `[🔄] backup_upload_retry`.
- Tests: `tests/test_backup_service.py` (fake Postgres + Drive), `tests/test_crypto.py`, `tests/test_backup_pg_live.py`
  (marker `integration`, real Postgres: `ARCHIVE_TEST_PG_URL=postgresql://…` + `pg_dump` installed).

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
- 2026-10-20: `/api/signals-store` (reflection signals, metrics, Athena observations) on the generic module store.
- 2026-10-19: generic `module_store` router → `/api/finance-store` (Plutus) and `/api/iris-store` (Iris); raw mail
  records delivered by Iris land in `/api/archive` under the subscriber's domain (`reference_id = mail:<domain>:<gmail id>`).
- 2026-10-20: backup to Google Drive, verification and rollback (section above); schema bootstrap moved to `app/schema.py`;
  module store answers carry `epoch`; Archive registers a plugin bundle (settings panel «Backup»).
