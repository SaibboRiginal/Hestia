# Progress

- [x] Read brainstorm decisions (item 8, §3 «Backup su Drive?», §4 Drive folder) and the «Importa ed esporta dati» SPEC
- [x] SPEC v1.0 (draft)
- [ ] Marko approves SPEC (open questions §10)
- [ ] P1 `hestia_common.crypto` + tests
- [ ] P2 Hecate Drive API (`drive.file`, `.hestia` root, chunked upload/download) + tests, swagger
- [ ] P3 Archive backup/verify/retention, `backups` table, agenda rules, settings, `backup_status` tool, pg client, volume
- [ ] P4 `tools/hestia_backup.py` + Archive plugin page «Backup»
- [ ] P5 docs + cloud bench flow `backup`
- [ ] PR, CI green, merge

## Notes
- Format alignment with «Importa ed esporta dati»: backup = encrypted pg_dump, transfer = per-module JSON `.hestia`; shared crypto helper and Drive `.hestia` root.
