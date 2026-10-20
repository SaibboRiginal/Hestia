# Export and import per module

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via Project thread (Marko 2026-10-20: «funzione di importazione ed esportazione configurazioni e dati per modulo … esportare quello che configuro e quello che aggiungo e le mie info … in modo granulare … da casa importarlo nella mia originale, ma non intendo api e secrets … opzioni tipo appendere o sovrascrittura … semplice minimalista ma mantenere la granularità e dettagli») |
| **Status** | Draft — waiting for Marko's approval |

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
1. Choose a `.hestia` file → same tree as export, read from the file, everything ticked; untick what you don't want.
2. Choose the mode (§5), globally or per section.
3. «Anteprima» (dry run, always first) → per section: nuovi · aggiornati · invariati · ignorati (più vecchi) ·
   da eliminare (only Sostituisci) · problemi; each count opens the items.
4. «Importa» → same report, done. A restore point is made first (§6).

Minimal: one page, two tabs, the tree, one mode selector, preview, done. Icons and tones from the design system,
no emoji.

## 3. Architecture (module boundaries kept)
- **Each module exports and imports only its own data**, through one shared contract (§4) implemented with a new
  helper `hestia_common.transfer`. The module knows what its records mean, which ones depend on others and how to
  migrate an older format. Archive keeps storing; nothing new reads Archive tables from outside their owner.
- **Themis exports and imports every module's settings** (it owns the values). In the tree they appear as the
  section «Impostazioni» under each module, split by setting group (e.g. Oracle: «Modelli» separate from
  «Chat»), so Marko can bring home his personal settings without the bench's free-model choices.
- **The client orchestrates**: the WebUI asks Hub which modules advertise the `transfer` capability, calls each
  through Hub, and builds/reads the file. No new service, no new URL, no new env var.
- A small CLI `tools/hestia_transfer.py export|import|preview` does the same from a terminal (Codespace or home),
  and the cloud bench uses it in its flow test.
- The assistant has no import tool: importing is a user action only.

## 4. Module contract (via Hub `/route/<svc>/...`)
| Method | Path | |
|---|---|---|
| GET | `/api/transfer/describe` | sections `{id, label, icon, count, depends_on[], has_files, schema}` |
| POST | `/api/transfer/items` | `{section, q, limit, offset}` → `{id, title, subtitle, updated_at}` for the item picker |
| POST | `/api/transfer/export` | `{sections: {id: {ids?}}, since?, include_files}` → `{module, schema, sections: {id: [records]}, files: [{id, mime, sha256}]}` |
| GET | `/api/transfer/files/{id}` | one referenced file `{mime, data_b64}` (the module reads its own Archive blob) |
| POST | `/api/transfer/import` | `{schema, sections, mode, dry_run, files_map}` → report (§2 counts + item lists) |
| POST | `/api/transfer/files` | upload one file → `{old_id, new_id}`; references are rewritten on import |

- **Dependencies**: selecting items pulls in what they reference (a session pulls its exercises; an outfit its
  pieces). The preview lists what was added this way. On import a record whose reference is missing in both
  the file and the target is reported as a problem, not written.
- **Records** carry their own `id`, `updated_at`, `deleted` (same shape as the module stores already used by
  Hercules, Hygieia, Wardrobe, Plutus): for those four the helper builds the sections from the store `kind`s
  with almost no code per module.
- **Versioning**: the file has `format: 1`; each module section has its own `schema` number. Older schema →
  the module migrates on import; newer than the module knows → that section is refused with «aggiorna Hestia».
- Registration: Hub capability `transfer: {sections, schema}`. Swagger documents the contract once.

## 5. Modes
| Mode | New records | Existing records (same id) | Records only at home |
|---|---|---|---|
| **Aggiungi** | added | left as they are | kept |
| **Unisci** (default) | added | updated only if the file's copy is newer (`updated_at`) | kept |
| **Sostituisci** | added | file wins | deleted (soft, tombstone) — only inside the ticked sections |

Settings follow the same rule: Aggiungi = only keys still at their default at home; Unisci = file value if it was
changed after the home value; Sostituisci = every ticked value. Values are validated against the home schema;
unknown keys or a module not installed at home → skipped and reported. History actor `import`.
Other options: «Solo modifiche dal …» on export (incremental), item-level selection on both sides, dry run.

## 6. Safety
- **Restore point**: before writing, the client exports the same sections from the target and stores the file
  in Archive blobs (tag `transfer-restore`); the page lists them with «Ripristina» (= import with Sostituisci).
  How many are kept is a WebUI setting in Themis (`webui.transfer.restore_points`, default 5).
- **Never exported**: env and secrets, Hecate OAuth tokens, MCP accesses/OAuth clients, logs, LLM usage, runtime
  state (presence signals, chat queue, caches), Forge worktrees. Records synced from an external provider
  (Google/Outlook calendar, Gmail) are not exported: home syncs them itself.
- The file contains personal data: download only, never written into the repo; `.hestia` added to `.gitignore`.
- Logs: `event=transfer_export|transfer_import module=… section=… mode=… added=… updated=… deleted=…`.

## 7. What each module exports (proposal)
| Module | Sections | Phase |
|---|---|---|
| Themis | settings of every module, by group; personal settings | P2 |
| Hercules | esercizi, schede, programmi, sessioni+serie, misure, obiettivi, piani, check-in, feedback | P3 |
| Hygieia | prodotti, routine (+versioni), registro, diario, opzioni | P3 |
| Wardrobe | capi, outfit, indossati, vocabolari, liste, foto (optional) | P3 |
| Plutus | movimenti, categorie, regole, budget, conti, ricorrenti | P3 |
| Chronos | agenda rules created or edited by Marko; own calendar items (not provider-synced) | P3 |
| Oracle | memoria (preferences), documenti, cronologia chat | P5 (ask) |
| Scout | annunci salvati + valutazioni | P5 (ask) |
| Hephaestus | lista sviluppi (task list, not worktrees) | P5 (ask) |
| Athena · Hermes | pensieri · notifiche/iscrizioni | P5 (ask) |

## 8. Phases
- **P1** `hestia_common.transfer` (contract, store-backed sections, dependencies, modes, dry run, files) + tests.
- **P2** Themis settings export/import.
- **P3** Hercules, Hygieia, Wardrobe (with photos), Plutus, Chronos.
- **P4** WebUI page «Esporta e importa» + restore points; CLI `tools/hestia_transfer.py`.
- **P5** the modules Marko picks from the «ask» rows.
- **P6** docs (module md, swagger, ARCHITECTURE, AI-GUIDE, README), cloud bench flow `transfer`
  (export on one stack, import in a clean one, screenshots).

## 9. Acceptance
- Export from the bench, import at home: chosen items arrive, nothing else changes; preview counts match the result.
- Each mode behaves as in §5 for records and settings; Sostituisci touches only ticked sections.
- No secret, token or key in any file (test scans the export).
- A restore point brings the target back to its state before the import.
- File from an older Hestia imports; from a newer one, the section says «aggiorna Hestia».

## 10. Open questions for Marko
1. P5: which of Oracle (memoria, documenti, chat), Scout, Hephaestus, Athena, Hermes do you want?
2. Password on the file (encrypted)? Default no; the Drive backup will need encryption anyway and can reuse it.
