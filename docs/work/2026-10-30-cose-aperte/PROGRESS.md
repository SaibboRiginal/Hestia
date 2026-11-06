# Progress — cose aperte

- [x] Census of open items (code + dossiers), decisions proposed to Marko
- [x] Roadmap section removed from docs/ARCHITECTURE.md (Marko: no roadmap)
- [x] 1 Real «Annulla riparazione»: Archive trash + `/api/module/maintenance/undo`, Hephaestus rollback, Riparazioni page, docs, swagger, tests
- [ ] 1 PR, CI green, merge
- [x] 4 Telegram parity: backup/restore/export/import, presence (`presence_set`), repair history (`hephaestus_tasks`)
      were already tools; added `memory_proposals` / `memory_proposal_apply` / `memory_proposal_dismiss` and
      `athena_commitments` / `athena_commitment_resolve` (check_telegram: every tool lands in an area)
- [x] 5a Wardrobe piece from a chat photo: `attachment_handlers` on Wardrobe → `/api/wardrobe/attachments`, saved with photo, tests
- [x] 2a Metis datasets persisted: `$METIS_DATA_DIR/datasets/<name>.json`, read back on first use, test
- [x] Tidy stale unchecked boxes in older dossiers: merged PRs ticked, dropped items marked dropped; what is left there is Marko's real run
