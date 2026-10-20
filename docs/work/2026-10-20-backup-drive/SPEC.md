# Backup on Google Drive

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via Project thread — brainstorm 2026-10-19 item 8 («Backup su Google Drive — cartella `.hestia` (riusabile per tutto), scope `drive.file` nell'app Google di Hecate, job Chronos di backup cifrato di Archive, prova di ripristino»); started by Marko 2026-10-20 («voglio che venga fatto tutto»); v1.1 answers of Marko 2026-10-20 (§10) |
| **Status** | Approved — in progress |

## 1. Goal
Diary, gym, wardrobe, expenses: data that cannot be recreated lives in one Postgres database on one PC. Every
night Hestia makes an **encrypted copy of the whole database** and puts it in a `.hestia` folder on Marko's Google
Drive. Once a month it **proves the copy can be restored** (restore into a scratch database, compare counts).
From the settings Marko sees the **history of backups and can roll back** to any of them, with an «Annulla
ripristino» if the rollback was a mistake. On a new PC: install, passphrase, one Google login, «Ripristina».

Not in scope: picking single items to move between two Hestia (that is «Importa ed esporta dati», §8).

## 2. What Marko sees
- **WebUI → Impostazioni → Sistema → Archivio** (a little hidden on purpose): under the retention settings a
  **Backup** panel (icons and tones from the design system, no emoji):
  - state: last backup (when, size, «verificato il …»), Google Drive connected or not, a job in progress (step);
  - **history** of backups on Drive: date, size, verified mark, «Ripristina» on each one;
  - «Esegui backup ora», «Verifica ora»; when Drive is not authorized, «Collega Google Drive» (existing Google
    re-authorization flow);
  - after a rollback: «Annulla ripristino» (back to the database as it was just before).
  «Ripristina» asks for a confirmation that says what happens («I dati tornano al … Tutto quello che è cambiato
  dopo viene sostituito. Puoi annullare finché non fai un altro ripristino.»).
- **Agenda**: two rules he can move, pause or cancel like any other: «Backup» (every day 03:30) and
  «Verifica backup» (1st of the month 04:00).
- **Notifications** (normal notifier, generic texts that name no module) only when something is wrong:
  «Backup non riuscito: …», «Verifica del backup fallita: …», «Backup fermo: manca la passphrase», «Backup in
  attesa: Google Drive non collegato». A fixed problem closes with «Backup di nuovo regolare». A rollback sends
  one «Dati ripristinati al …».
- **Assistant**: read-only tool `backup_status` («quando è stato l'ultimo backup?»). No tool restores.

## 3. Architecture (module boundaries kept)
| Who | Does | Why there |
|---|---|---|
| **Archive** | dump, encrypt, upload through Hub, retention, verify, restore/rollback | only DB owner; the plaintext dump never leaves its container |
| **Hecate** | generic Google Drive file API confined to the `.hestia` folder | owns external providers and the Google OAuth token |
| **Chronos** | two agenda rules registered by Archive with `agenda_client` | scheduling = agenda, no timers |
| **Themis** | retention settings declared by Archive | tunables are settings |
| **Hermes** | the problem notices | only outbound messenger |
| **WebUI** | the Backup panel = Archive's plugin element shown inside Archive's settings (new generic plugin contribution `settings_panel`) | client; any module can add a panel to its own settings |

No new service, no direct URL (Archive → `POST {HUB}/route/hecate/api/gateway/drive/...`), no new LLM client, no
new DB.

### 3.1 Hecate: Drive files API (generic, reusable)
Scope `https://www.googleapis.com/auth/drive.file` added to the default Google scopes: Hestia sees **only the files
it created**, never the rest of the Drive. Root folder `.hestia` (created on first use, found again by its
`appProperties.hestia=root`); callers name a subfolder (`backup`, later `export`…).

| Method | Path (`/api/gateway/drive/…`) | |
|---|---|---|
| GET | `status` | `{connected, scope_ok, error}` |
| GET | `files?folder=backup` | `[{id, name, size, created_at, app_properties}]` |
| POST | `upload/start` | `{folder, name, mime, size, app_properties}` → `{upload_id}` (Drive resumable upload) |
| POST | `upload/{upload_id}/chunk` | `{offset, data_b64}` (2 MB per call, keeps the Hub envelope small) → `{received, done, file?}` |
| GET | `files/{id}/chunk?offset=&length=` | `{data_b64, eof, size}` |
| PATCH | `files/{id}` | `{app_properties}` (e.g. verification result) |
| DELETE | `files/{id}` | moves to Drive trash |

Missing scope → `409 {error:"drive_scope_missing"}`. Logs `event=drive_upload|drive_download|drive_delete …`.

### 3.2 Shared encryption: `hestia_common.crypto`
Streaming encryption with a passphrase: scrypt → AES-256-GCM in 1 MB chunks (header `HESTIA-ENC1`, salt, KDF
params, nonce prefix; chunk counter in the nonce, last chunk flagged in the authenticated data, so truncation and
tampering are detected). Library `cryptography`. «Importa ed esporta dati» reuses it for its optional file
password (agreed with that thread), so Hestia has one encryption format.

Passphrase = secret → env `HESTIA_BACKUP_PASSPHRASE` in `.env`. It cannot live in the database (it would be inside
the backup it protects). **If it is lost, the backups cannot be opened**: docs and panel say so.

### 3.3 Archive: backup, retention, verify
- File content (before encryption): `HESTIA-BACKUP1` + a JSON manifest (created_at, Postgres version, row count
  per table) + the `pg_dump -Fc` archive. Counts and dump come from **one snapshot** (`pg_export_snapshot` +
  `pg_dump --snapshot`), so they match exactly.
- `POST /api/backup/run` (agenda job `archive.backup`, daily 03:30; returns at once, works in background):
  dump → encrypt into the volume `hestia_backups` → upload in chunks to `.hestia/backup/` as
  `hestia-backup-AAAA-MM-GG-HHMM.enc` with `appProperties {hestia: backup, sha256, created_at}` → retention →
  local file deleted.
- The **history is Drive itself** (list of `backup/`), not a table: a rollback replaces every table, a list kept in
  the database would roll back with it. Job state and last results live in `hestia_backups/state.json`.
- **Drive not reachable / not authorized**: the encrypted file stays in `hestia_backups` (at most 3), the next run
  uploads the pending ones first (`[🔄] event=backup_upload_retry`). No other local copy (Marko, §10.3).
- **Retention** (settings §4): the newest `keep_daily` backups + the first backup of each of the last
  `keep_monthly` months; the rest goes to the Drive trash.
- `POST /api/backup/verify` (agenda job `archive.backup_verify`, 1st of the month 04:00): download the newest
  backup, check sha256, decrypt, restore into a scratch database `hestia_restore_check`, compare the row counts
  with the manifest, drop the scratch database, write `verified_at`/`verify` into the file's appProperties.
- `pg_dump`/`pg_restore` in the Archive image: `postgresql-client` from the PGDG repository for the majors
  15, 16, 17; Archive uses the one matching the server (`SHOW server_version_num`), else the newest.
- Logs: `event=backup_done name=… bytes=… seconds=…`, `event=backup_failed step=… error=…`,
  `event=backup_verify ok=… tables=… mismatched=…`, `event=backup_restore step=…`.

### 3.4 Rollback (restore) from the settings
`POST /api/backup/restore {file_id}` (background job, progress in `status`):
1. download, check sha256, decrypt, restore into a new database `hestia_memory_restore`, run Archive's schema
   migrations on it (an older backup gains today's tables/columns), compare counts with the manifest;
   any failure here → the scratch database is dropped and nothing changed;
2. **swap**: Archive answers 503 to everything else for a few seconds (modules already retry: `[🔄]`), closes its
   connections, renames `hestia_memory` → `hestia_memory_prev` and `hestia_memory_restore` → `hestia_memory`,
   reconnects;
3. a new **data epoch** is written: every store answer carries `epoch`; a module whose mirror saw another epoch
   drops the mirror and reloads (Hercules, Hygieia, Wardrobe, Plutus), so no stale row is written back;
4. one notice «Dati ripristinati al …».

`POST /api/backup/undo` swaps back with `hestia_memory_prev` (available until the next rollback, which replaces it).
CLI for a PC without WebUI yet or a file downloaded by hand: `python tools/hestia_backup.py list | restore
<name|--file path> | undo | decrypt <file>` (runs inside the Archive container, asks to type `RIPRISTINA`).

## 4. Settings (Themis, declared by Archive, group «Backup»)
| Key | Default | |
|---|---|---|
| `archive.backup.keep_daily` | 3 | recent backups kept (one per day) |
| `archive.backup.keep_monthly` | 3 | monthly backups kept |

Time and frequency of backup and verification are the agenda rules (editable). No on/off switch: pausing the
agenda rule is Marko's decision.

## 5. What goes in the backup
The whole `hestia_memory` database (every module's records, blobs incl. wardrobe photos, settings, chat history,
memory, agenda, MCP accesses). Not included: `.env`, Hecate's OAuth token file, `data/` folders, other volumes,
Forge worktrees (code is on GitHub).

## 6. Phases
- **P1** `hestia_common.crypto` + tests (round trip, wrong passphrase, truncated/tampered file).
- **P2** Hecate Drive API + tests with a fake Drive; swagger; scope in defaults and `.env.example`.
- **P3** Archive backup/verify/retention/restore/undo, epoch in store answers, agenda rules, settings,
  `backup_status` tool, `postgresql-client` in the image, volume `hestia_backups` + tests; module mirrors follow
  the epoch.
- **P4** plugin contribution `settings_panel` (plugin_client, Hub catalog, WebUI .NET + Angular) + Archive bundle
  `archive-backup-panel`; `tools/hestia_backup.py`.
- **P5** docs (`hestia-archive.md`, `hestia-hecate.md`, swagger, ARCHITECTURE, AI-GUIDE, README, TESTING) + real
  run on the bench (Postgres 15: backup → verify → rollback → undo).

## 7. Acceptance
- A backup lands in `.hestia/backup` encrypted (no `PGDMP` header visible), the history shows it.
- Verification restores it into a scratch database and the counts match; a tampered file fails with a notice.
- With Drive disconnected the backup is kept locally and uploaded at the next run.
- Retention keeps exactly `keep_daily` + monthly ones.
- Rollback brings back the data of that day, module mirrors reload, «Annulla ripristino» brings back the data of
  just before.
- No passphrase, token or personal data in any tracked file.

## 8. Alignment with «Importa ed esporta dati» (agreed 2026-10-20)
- **Backup** = disaster recovery and rollback: the whole database as an encrypted `pg_dump` (`.enc`).
- **Transfer** = selective JSON `.hestia` file built by each module, merged with modes and preview.
Shared, owned here: `hestia_common.crypto` and Hecate's Drive API with the `.hestia` root (transfer later adds
«Salva su Drive» into `.hestia/export`).

## 9. What Marko does once (outside the code)
1. Google Cloud console, same project as the Hestia OAuth app: enable **Google Drive API**.
2. OAuth consent screen: add scope `.../auth/drive.file`.
3. `.env`: `HESTIA_BACKUP_PASSPHRASE=<long passphrase>`, also saved in a password manager.
4. WebUI: «Collega Google Drive» (re-authorizes Google once; Calendar and Gmail keep working).

## 10. Decisions (Marko 2026-10-20)
1. Restore: in the settings, a bit hidden, as a history of backups to roll back to (not only a terminal command).
2. One backup per day; how many are kept is configurable (defaults lowered to 3 daily + 3 monthly).
3. No permanent local copy: only while Drive is unreachable.
