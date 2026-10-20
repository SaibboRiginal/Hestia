# PROGRESS — wardrobe module

Spec: `SPEC.md` v1.10 · resume from the first unchecked box.

- [x] Request read, repo studied (Scout skeleton, Archive entities, no blob storage, Oracle image analysis)
- [x] Shared choices sent to the Self care / Coach / plugin threads (ports 19017–19019, `<module>.<kind>` entities, Archive blob store, `/api/module/context`)
- [x] Dossier created (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] SPEC v1.1: typed Archive tables, plugin contract mapping, shared context contract
- [x] SPEC v1.2: UI per plugin contract v2 (module-owned Web Components bundle)
- [x] User approves SPEC (2026-10-18, v1.9)
- [x] Hub vocabulary: service type `module`, tags `context`/`wardrobe`/`fitness`/`selfcare`, domains
- [x] W1 Archive `wardrobe-store` + generic `blobs` router; module skeleton, CRUD, photos (Pillow: orientation, no EXIF, 3 sizes), swagger, docs, tests
- [x] W2 MCP tools (12 `guardaroba_*`), `/api/module/context`, Hermes confirm for delete (Elimina / Archivia / Tieni)
- [x] W3 Stats, suggestion engine with reasons, agenda jobs `wardrobe.reminder` / `wardrobe.review` + Hermes (off by default)
- [x] W4 UI bundle `Hestia-Wardrobe/ui` (10 pages, 6 widgets, quick action `indossato`, `shirt` icon in WebUI + SDK); typecheck + build ok, rendered in Chromium with a fake host
- [x] W5 describe-photo (Oracle, proposes only), collections + packing, export/import JSON
- [x] Docs: `hestia-wardrobe.md`, Archive doc, swagger, AI-GUIDE, ARCHITECTURE (module context + module files), compose
- [x] Root CHANGELOG line
- [ ] User real run: `up-all.bat --build archive wardrobe webui`, add a few pieces with photos, mark an outfit from Home
- [ ] Telegram photo draft (send a photo → proposed piece → confirm): follow-up, needs a Telegram change
- [ ] W6 Outfit board / photo composition (later)
- [ ] W7 Mirror check-in: photo before going out → recognised pieces → wear entry (far future)
- [x] Real run on the cloud bench (2026-10-19, fake LLM): 9 pieces with photo + thumbnail, filters, chat `wardrobe_search`, «Cosa mi metto» (8°, rain, office) API + chat, outfit by slots, «Indossato» from Home, donate → outfit «da rivedere», stats, packing, module context all pass; fix found: Italian labels («ufficio») did not match vocabulary keys, so the occasion was ignored → `docs/work/2026-10-19-prove-reali-banco/`. Not judgeable with the fake LLM: semantic search quality
