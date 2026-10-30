# Progress

- [x] Read brainstorm decisions (item 8, §3 «Backup su Drive?», §4 Drive folder) and the «Importa ed esporta dati» SPEC
- [x] SPEC v1.0 (draft)
- [x] Marko approves SPEC (answers to §10 → v1.1, 2026-10-20)
- [x] P1 `hestia_common.crypto` + tests (13)
- [x] P2 Hecate Drive API (`drive.file`, `.hestia` root, chunked upload/download) + tests (9)
- [x] P3 Archive backup/verify/retention/restore/undo, gate, data epoch in store answers and module mirrors, agenda
      rules, settings, pg clients in the image, volume `hestia_archive_backups` + tests (fake + real Postgres 15)
- [x] P4 plugin contribution `settings_panel` (plugin_client, Hub, WebUI .NET + Angular), Archive panel
      `archive-backup-panel`, CLI `tools/hestia_backup.py` (+ `app/backup/cli.py`)
- [x] P5 docs (swagger, Hecate, Shared, ARCHITECTURE, AI-GUIDE, README, TESTING, root CHANGELOG) + bench run: whole stack
      healthy, backup with Drive away kept locally, CLI `restore --file` rolled back a record written after the backup,
      new epoch, `undo` and redo OK (2026-10-22)
- [x] PR, CI green, merge — on main (checked 2026-10-30, docs/work/2026-10-30-cose-aperte)
- [ ] Marko: one-time setup (SPEC §9) and real run

## Notes
- Format alignment with «Importa ed esporta dati»: backup = encrypted pg_dump, transfer = per-module JSON `.hestia`; shared crypto helper and Drive `.hestia` root.
- 2026-10-20: «Importa ed esporta dati» agreed (its SPEC v1.1): this dossier owns `hestia_common.crypto` and Hecate's Drive API; transfer reuses crypto for its file password and writes to `.hestia/export/` later.
- Real Postgres test: `ARCHIVE_TEST_PG_URL=postgresql://…@localhost:55432/hestia_memory python -m pytest -m integration Hestia-Archive/tests/test_backup_pg_live.py` (backup → verify → restore → undo → redo), passed on PG 15 with pg_dump 16.
- 2026-10-21: Archive image failed on the bench because `requirements.txt` had no final newline (`requests==2.32.3cryptography>=42`); fixed.
- 2026-10-22 bench fixes: Drive-unreachable notice repeated itself and showed the Hub URL (now plain, details in the log); CLI wrapper did not forward piped stdin to the confirmation.
