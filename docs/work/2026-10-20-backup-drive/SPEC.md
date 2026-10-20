# Backup on Google Drive

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via Project thread — brainstorm 2026-10-19 item 8 («Backup su Google Drive — cartella `.hestia` (riusabile per tutto), scope `drive.file` nell'app Google di Hecate, job Chronos di backup cifrato di Archive, prova di ripristino»); started by Marko 2026-10-20 («voglio che venga fatto tutto») |
| **Status** | Draft — waiting for Marko's approval |

## 1. Goal
Diary, gym, wardrobe, expenses: data that cannot be recreated lives in one Postgres database on one PC. Every
night Hestia makes an **encrypted copy of the whole database** and puts it in a `.hestia` folder on Marko's Google
Drive. Once a month it **proves the copy can be restored** (restore into a scratch database, compare counts). If the
PC dies, a new install + the passphrase + one Google login bring everything back with one command.

Not in scope: picking single items to move between two Hestia (that is «Importa ed esporta dati», §8).

## 2. What Marko sees
- **WebUI → Sistema → Backup** (new page, icons and tones from the design system, no emoji):
  - state card: last backup (when, size, «verificato il …»), next run (read from the agenda), Drive connected or not;
  - list of backups on Drive: date, size, kind (giornaliero / mensile), verified mark;
  - buttons «Esegui ora» and «Verifica ora»; when Drive is not authorized, «Collega Google Drive» (the existing
    Google re-authorization flow).
- **Agenda**: two rules he can move, pause or cancel like any other: «Backup» (every day 03:30) and
  «Verifica backup» (1st of the month 04:00).
- **Notifications** (via the normal notifier, generic texts that name no module): only when something is wrong —
  «Backup non riuscito: …», «Verifica del backup fallita: …», «Backup fermo: manca la passphrase», «Backup in attesa:
  Google Drive non collegato (copia tenuta in locale)». A fixed problem closes with «Backup di nuovo regolare».
- **Assistant**: read-only tool `backup_status` (last backup, last verification, problems), so «quando è stato
  l'ultimo backup?» works in any chat. No tool to start a restore.

## 3. Architecture (module boundaries kept)
| Who | Does | Why there |
|---|---|---|
| **Archive** | dump, encrypt, upload through Hub, retention, verify, restore command | only DB owner; the plaintext dump never leaves its container |
| **Hecate** | generic Google Drive file API confined to the `.hestia` folder | owns external providers and the Google OAuth token |
| **Chronos** | two agenda rules registered by Archive with `agenda_client` | scheduling = agenda, no timers |
| **Themis** | retention settings declared by Archive | tunables are settings |
| **Hermes** | the problem notices | only outbound messenger |
| **WebUI** | page «Backup» served as Archive's plugin (core plugin pattern) | client |

No new service, no direct URL (Archive → `POST {HUB}/route/hecate/api/drive/...`), no new LLM client, no new DB.

### 3.1 Hecate: Drive files API (generic, reusable)
Scope `https://www.googleapis.com/auth/drive.file` added to the default Google scopes: Hestia sees **only the files
it created**, never the rest of the Drive. Root folder `.hestia` (created on first use, found again by its
`appProperties.hestia=root`); callers name a subfolder (`backup`, later `export`, `documenti`…).

| Method | Path | |
|---|---|---|
| GET | `/api/drive/status` | `{connected, scope_ok, root_id}` |
| GET | `/api/drive/files?folder=backup` | `[{id, name, size, created_at, app_properties}]` |
| POST | `/api/drive/upload/start` | `{folder, name, mime, size, app_properties}` → `{upload_id}` (Drive resumable upload) |
| POST | `/api/drive/upload/{upload_id}/chunk` | `{offset, data_b64}` (≤ 4 MB per call, so the Hub envelope stays small) |
| POST | `/api/drive/upload/{upload_id}/finish` | → file metadata |
| GET | `/api/drive/files/{id}/chunk?offset=&length=` | `{data_b64, eof}` |
| DELETE | `/api/drive/files/{id}` | moves to Drive trash |

Missing scope → `409 {error:"drive_scope_missing"}` and Hecate's existing «riautentica Google» notice. Logs
`event=drive_upload|drive_download|drive_delete folder=… bytes=…`.

### 3.2 Shared encryption: `hestia_common.crypto`
Streaming encryption with a passphrase: scrypt (N=2^17) → AES-256-GCM in 1 MB chunks, header
`HESTIA-ENC1 | salt | chunk size`, per-chunk nonce = counter, last chunk flagged (truncation is detected). Library
`cryptography` (new dependency of Archive and of the modules that use the helper). The same helper is offered to «Importa ed esporta dati» for its
optional password on the `.hestia` file (its open question 2), so Hestia has one encryption format.

Passphrase = secret → env `HESTIA_BACKUP_PASSPHRASE` in `.env` (allowed: env is for secrets). It cannot live in the
database, or it would be inside the backup it protects. **If it is lost, the backups cannot be opened**: the docs
and the WebUI page say to keep it in a password manager.

### 3.3 Archive: backup, retention, verify
- `POST /api/backup/run` (agenda job `archive.backup`, daily 03:30):
  `pg_dump -Fc` → temp file in a new volume `hestia_backups` → encrypt → upload in chunks to `backup/` as
  `hestia-backup-AAAA-MM-GG-HHMM.dump.enc` with `app_properties {kind, sha256, tables: {name: rows}}` → row in a new
  table `backups` (id, drive_file_id, name, size, sha256, row counts, created_at, status, verified_at, verify_result)
  → retention → temp file deleted.
- **Drive not reachable / not authorized**: the encrypted file stays in `hestia_backups` (at most 3 kept), the next
  run uploads the pending ones first (`[🔄] event=backup_upload_retry`). Nothing is lost silently.
- **Retention** (settings, §4): keep the last `keep_daily` backups + the first backup of each month for
  `keep_monthly` months; older ones go to the Drive trash.
- `POST /api/backup/verify` (agenda job `archive.backup_verify`, 1st of the month 04:00): download the newest
  backup, check sha256, decrypt, `pg_restore` into a scratch database `hestia_restore_check`, compare per-table row
  counts with those recorded at dump time, drop the scratch database, record the result.
- `GET /api/backup/status`, `GET /api/backup/list` (WebUI page + `backup_status` tool).
- `pg_dump`/`pg_restore` in the Archive image: `postgresql-client` from the PGDG repo pinned to the server's
  major version; at start Archive compares `pg_dump --version` with `SHOW server_version` and logs
  `event=backup_client_mismatch` (the backup page shows it) instead of producing an unusable dump.
- Logs: `event=backup_done name=… bytes=… seconds=…`, `event=backup_failed step=… error=…`,
  `event=backup_verify ok=… tables=… mismatched=…`.

### 3.4 Restore (deliberately a terminal command)
`python tools/hestia_backup.py restore [--latest | --file <path> | --name <drive name>]`, run on the host:
asks to type `RIPRISTINA`, stops the services that write to the database, runs `pg_restore --clean` inside the
Archive container, starts them again, prints counts. On a brand-new PC: install, put the passphrase in `.env`,
connect Google once in the WebUI (Hecate token is a file in `Hestia-Hecate/data`, not in the database), run the
command. Also `tools/hestia_backup.py list` and `decrypt <file>` (for a copy downloaded by hand from drive.google.com).
No restore button in the WebUI or tool for the assistant: overwriting everything is a deliberate act.

## 4. Settings (Themis, declared by Archive)
| Key | Default | |
|---|---|---|
| `archive.backup.keep_daily` | 7 | recent backups kept |
| `archive.backup.keep_monthly` | 12 | monthly backups kept |

Schedule lives in the agenda, not in settings. No on/off switch: the backup always runs; pausing the agenda rule is
Marko's decision.

## 5. What goes in the backup
The whole `hestia_memory` database (every module's records, blobs incl. wardrobe photos, settings, chat history,
memory, agenda, MCP accesses). Not included: `.env`, Hecate's OAuth token file, `data/` folders, Docker volumes of
other services, Forge worktrees (the code is on GitHub).

## 6. Phases
- **P1** `hestia_common.crypto` + tests (round trip, wrong passphrase, truncated/tampered file).
- **P2** Hecate Drive API (`drive.file`, `.hestia` root, resumable upload/download in chunks) + tests with a fake
  Drive; swagger; scope note in `.env.example`.
- **P3** Archive backup/verify/retention, `backups` table, agenda rules, settings, `backup_status` tool,
  `postgresql-client` in the image, volume `hestia_backups` + tests (real `pg_dump` on the cloud bench).
- **P4** `tools/hestia_backup.py` (restore, list, decrypt) + Archive plugin page «Backup».
- **P5** docs (`hestia-archive.md`, `hestia-hecate.md`, swagger, ARCHITECTURE, AI-GUIDE, README, TESTING) + cloud
  bench flow `backup` (fake Drive: backup → verify → restore into a clean stack, screenshots).

## 7. Acceptance
- A backup runs from the agenda, lands in `.hestia/backup` on Drive encrypted (the file does not start with the
  `PGDMP` header), the list and the page show it.
- Verification restores it into a scratch database and the counts match; a tampered file fails with a notice.
- With Drive disconnected the backup is kept locally and uploaded at the next run.
- Retention keeps exactly `keep_daily` + monthly ones.
- `restore --latest` on a clean bench stack brings back the data of the original one.
- No passphrase, token or personal data in any tracked file.

## 8. Alignment with «Importa ed esporta dati»
Two tools, two jobs, no second format for the same thing:
- **Backup** = disaster recovery: the whole database as an encrypted `pg_dump` (`.dump.enc`), restored all at once.
- **Transfer** = selective JSON `.hestia` file built by each module, merged with modes and preview.
Shared pieces: `hestia_common.crypto` (one encryption format) and Hecate's Drive API with the `.hestia` root
(transfer can later add «Salva su Drive» into `.hestia/export`).

## 9. What Marko does once (outside the code)
1. Google Cloud console, the same project as today's Hestia OAuth app: enable **Google Drive API**.
2. OAuth consent screen: add scope `.../auth/drive.file`.
3. `.env`: `HESTIA_BACKUP_PASSPHRASE=<long passphrase>`, also saved in a password manager.
4. WebUI: «Collega Google Drive» (re-authorizes Google once; Calendar and Gmail keep working).

## 10. Open questions for Marko
1. Restore only by terminal command (recommended), or also a button in the WebUI?
2. Defaults ok: every night 03:30, 7 daily + 12 monthly, verification monthly?
3. Keep also one local copy of the last backup on the PC (in `hestia_backups`) even when Drive works? Default: no,
   only while Drive is unreachable.
