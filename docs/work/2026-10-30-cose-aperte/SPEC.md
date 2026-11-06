# Cose aperte: fare o buttare

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (Marko, thread «README chiaro», 2026-10-30) | done (PR #69) |

## Goal
Marko: no roadmap anywhere («non ce ne facciamo niente»). What is still open in the code is either done now or
dropped. The `## Roadmap` section of `docs/ARCHITECTURE.md` is removed.

## Census (code + every dossier PROGRESS.md, main @ 44b1cb3)
| # | Open item | Decision |
|---|---|---|
| 1 | «Annulla riparazione» (Hephaestus remediation rollback) only flipped the state | **do** — real undo |
| 2a | Metis datasets in memory, lost on restart | **do** |
| 4 | Telegram parity: backup/restore, presence change, Athena proposals, repair history only in WebUI | **do** |
| 5a | Wardrobe: add a piece from a Telegram photo | **do** |
| 2b | Metis live benchmark + LoRA training script | waits for the local model and collected chats (dataset thread) |
| 3 | Multi-node (Pi + satellites) | covered by the one-click setup SPEC (roles Casa centrale / Satellite) |
| 5b | Wardrobe outfit board, mirror check-in | dropped |
| 6 | Self care photos, barcode, import/export | dropped |
| 7 | Sviluppo page live push instead of polling | dropped (polling is fine) |
| 8 | Voice on the cloud bench | dropped (blocked by network; Marko tests voice at home) |

## Acceptance criteria
- Item 1: a repair waiting for approval or failed is stopped; a succeeded repair that deleted Archive rows gets them
  back; a repair with nothing restorable says so and stays as it is. Tests in Hephaestus and Archive.
- Items 2a, 4, 5a: see their sections when started (one PR each).
- No roadmap section anywhere in the docs.

## Design — item 1
- Contract: a module's `…/maintenance/reconcile` may answer `details.undo_available=true`; then it also serves
  `…/maintenance/undo {task_id}`. Hephaestus marks the task `undoable` and, on rollback, routes to that path via Hub.
- Archive: reconcile (entity cleanup) keeps the deleted rows (payload, status, embedding, created_at) in one entity
  `trash:<task_id>` (domain `archive_trash`, never scanned by cleanup). Undo re-inserts them, skipping entity ids
  recreated meanwhile, and removes the trash. Archive stays the only DB owner.
- Chronos/Iris/Scout reconcile = re-sync ticks: nothing to restore, `nothing_to_undo`.
- WebUI Riparazioni page: «Si può annullare» and the undo outcome replace the git `rollback_ref` line.
