# Export and import per module

| | |
|---|---|
| **Version** | 2.0 |
| **Source** | user via Project thread (Marko 2026-10-20: «funzione di importazione ed esportazione configurazioni e dati per modulo … esportare quello che configuro e quello che aggiungo e le mie info … in modo granulare … da casa importarlo nella mia originale, ma non intendo api e secrets … opzioni tipo appendere o sovrascrittura … semplice minimalista ma mantenere la granularità e dettagli») |
| **Status** | Implemented (PR) — Marko's real run pending |

## 1. Goal
Take what Marko configures and adds on one Hestia (today: the cloud bench in a Codespace) and bring it into
another one (home), choosing exactly what: by module, by section, down to single items. One file, a preview
before anything is written, and an easy way back if the import was wrong. Never secrets, tokens or API keys.

## 2. What a user sees (WebUI, Impostazioni → «Esporta e importa»)
**Export**
1. A list of modules that have something to export, each with its sections and counts
   (e.g. Allenamento: Esercizi 84 · Schede 6 · Sessioni 41 · Misure 12 · Impostazioni 9).
2. Tick a whole module, a section, or open a section to pick single items (search + list).
3. Options: «Solo modifiche dal …» (date: only what changed after it), «Includi foto» (where a module has them).
4. «Esporta» → downloads `hestia-AAAA-MM-GG.hestia`.

**Import**
1. Choose a `.hestia` file → same tree as export, read from the file, everything ticked; untick sections you don't
   want (single items are chosen on export; the preview lists every item).
2. Choose the mode (§5), globally or per section.
3. «Anteprima» (dry run, always first) → per section: nuovi · aggiornati · invariati · ignorati (più vecchi) ·
   da eliminare (only Sostituisci) · problemi; each count opens the items.
4. «Importa» → same report, done. A restore point is made first (§6).

**Ripristino**: the restore points (§6), each with «Ripristina» (opens it in Importa with Sostituisci) and «Elimina».

Minimal: one page, three tabs (Esporta · Importa · Ripristino), the tree, one mode selector, preview, done. Icons and
tones from the design system, no emoji. Deep link `/settings?tab=transfer`.

## 3. Architecture (module boundaries kept)
- **Each module exports and imports only its own data**, through one shared contract (§4) implemented with a new
  helper `hestia_common.transfer`. The module knows what its records mean, which ones depend on others and how to
  migrate an older format. Archive keeps storing; nothing new reads Archive tables from outside their owner.
- **Themis exports and imports every module's settings** (it owns the values): one Themis section per module
  (id = module name), shown as «Impostazioni» under that module; Themis' own section = personal settings. «Scegli»
  picks single settings (each with its group), so Marko can bring home his preferences without the bench's
  free-model choices. Layers system, profile and client travel; session copies never do.
- **The client orchestrates**: the WebUI asks Hub which modules advertise the `transfer` capability, calls each
  through Hub, and builds/reads the file. No new service, no new URL, no new env var.
- A small CLI `tools/hestia_transfer.py modules|export|preview|import` does the same from a terminal (Codespace or
  home; it writes a local backup file before importing). The cloud bench has a flow `transfer`.
- The assistant has no import tool: importing is a user action only.

## 4. Module contract (via Hub `/route/<svc>/...`)
| Method | Path | |
|---|---|---|
| GET | `/api/transfer/describe` | sections `{id, label, icon, count, depends_on[], has_files, schema}` |
| POST | `/api/transfer/items` | `{section, q, limit, offset}` → `{items: [{key, title, subtitle, updated_at}], total}` for the item picker |
| POST | `/api/transfer/export` | `{sections?: {id: {keys?}}, since?, include_files}` → `{module, format, exported_at, since, sections: {id: {schema, label, partial, records}}, pulled, files: [blob ids]}` |
| GET | `/api/transfer/files/{id}` | one referenced file `{id, mime, sha256, meta, data_b64}` (only the module's own Archive blobs) |
| POST | `/api/transfer/import` | `{data: <module block>, mode, modes?: {section: mode}, dry_run (default true), sections?, files_map?}` → `{sections: {id: {added, updated, unchanged, skipped, deleted, problems, related, partial, items}}, totals}` |
| POST | `/api/transfer/files` | upload one file → `{old_id, new_id}`; references are rewritten on import |

- **Dependencies**: a section names the sections it refers to (`depends_on`); exporting chosen items pulls in the
  records whose id appears in them (a session pulls its template and exercises; an outfit its pieces), and an
  item's children travel with it (a session's sets, a routine's versions). The export lists what was pulled
  (`pulled`). Photos are pulled only with «Includi foto».
- **Counts** are items (what the picker shows); children are reported as `related`.
- **Records** carry their own `id`, `updated_at`, `deleted` (same shape as the module stores already used by
  Hercules, Hygieia, Wardrobe, Plutus): for those four the helper builds the sections from the store `kind`s
  with almost no code per module.
- **Versioning**: the file has `format: 1`; each module section has its own `schema` number. Older schema →
  the module migrates on import; newer than the module knows → that section is refused with «aggiorna Hestia».
- Registration: Hub capability `transfer: {endpoint, format, sections: {id: schema}}` (Themis: `settings: true`).
  Swagger documents the contract once (tag `transfer`).
- **File** `hestia-AAAA-MM-GG.hestia` = gzip JSON `{hestia: "transfer", format: 1, exported_at, since, include_files,
  modules: {<owner>: <export>}, files: {<owner>: {<blob id>: {mime, sha256, meta, data_b64}}}}` (plain JSON is
  read too).

## 5. Modes
| Mode | New records | Existing records (same id) | Records only at home |
|---|---|---|---|
| **Aggiungi** | added | left as they are | kept |
| **Unisci** (default) | added | updated only if the file's copy is newer (`updated_at`) | kept |
| **Sostituisci** | added | file wins | deleted (soft, tombstone) — only inside the ticked sections |

Settings follow the same rule: Aggiungi = only keys still at their default at home; Unisci = file value if it was
changed after the home value; Sostituisci = every ticked value. Values are validated against the home schema;
unknown keys or a module not installed at home → skipped and reported. History actor `import`.
Other options: «Solo modifiche dal …» on export (incremental, deletions included as tombstones), item-level
selection on export, a mode per section on import, dry run. A partial section (chosen items or «solo modifiche
dal») never deletes, even with Sostituisci.

## 6. Safety
- **Restore point**: before writing, the client exports the same sections (whole) from the target and stores the
  file as a WebUI Archive blob (gzip, meta `kind: transfer-restore`); the page lists them with «Ripristina»
  (= import with Sostituisci). The CLI writes the same as a local file.
  How many are kept is a WebUI setting in Themis (`webui.transfer.restore_points`, default 5).
- **Never exported**: env and secrets, Hecate OAuth tokens, MCP accesses/OAuth clients, logs, LLM usage, runtime
  state (presence signals, chat queue, caches), Forge worktrees. Records synced from an external provider
  (Google/Outlook calendar, Gmail) are not exported: home syncs them itself.
- The file contains personal data: download only, never written into the repo; `.hestia` added to `.gitignore`.
- Logs: `event=transfer_export|transfer_import module=… section=… mode=… added=… updated=… deleted=…`.

## 7. What each module exports (Marko 2026-10-20: every domain module; from the core the memories and the agenda;
no chats or sessions for now)
| Module | Sections |
|---|---|
| Themis | settings of every module (one section each) + personal settings |
| Hercules | esercizi · schede e programmi · sessioni (+ serie) · misure · obiettivi e piani · check-in e note |
| Hygieia | prodotti (+ storia) · routine (+ versioni) · registro · diario · liste personali |
| Wardrobe | capi · outfit · indossati · liste · vocabolari · foto (files, optional) |
| Plutus | movimenti · categorie · regole · budget · conti · ricorrenti |
| Scout | annunci (with the user's marks); Sostituisci never deletes (the mail cycle brings them back) |
| Oracle | memorie (preferences, facts, skills, commitments — never `conversational_history`), matched by class + fact |
| Chronos | agenda: items the user created + module rules the user changed; run state stays home |
| not exported | Hephaestus, Athena, Hermes, chats and sessions (Marko: not for now); runtime rows (reminder/alert state, imports, processed mails, adaptations) |

## 8. Phases
- **P1** `hestia_common.transfer` (contract, store-backed sections, dependencies, modes, dry run, files) + tests.
- **P2** Themis settings export/import.
- **P3** Hercules, Hygieia, Wardrobe (with photos), Plutus, Scout, Oracle memories, Chronos agenda.
- **P4** WebUI page «Esporta e importa» + restore points (`webui.transfer.restore_points`); CLI `tools/hestia_transfer.py`.
- **P5** docs (module md, swagger, ARCHITECTURE, AI-GUIDE, README, TESTING), cloud bench flow `transfer`.

## 9. Acceptance
- Export from the bench, import at home: chosen items arrive, nothing else changes; preview counts match the result.
- Each mode behaves as in §5 for records and settings; Sostituisci touches only ticked sections.
- No secret, token or key in any file (test scans the export).
- A restore point brings the target back to its state before the import.
- File from an older Hestia imports; from a newer one, the section says «aggiorna Hestia».

## 10. Decisions (Marko 2026-10-20)
1. Every domain module; from the core the memories and the agenda (+ its settings); no chats or sessions for now.
2. No password on the file. If wanted later it reuses `hestia_common.crypto` (Drive backup dossier).

## 11. Relation with the Drive backup
The backup (dossier «Backup su Drive») is a whole-DB encrypted `pg_dump` for disaster recovery; `.hestia` stays the
only per-module transfer format. A later «Salva su Drive» can write exports into the Hecate Drive folder `.hestia/export/`.
