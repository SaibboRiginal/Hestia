# Progress

- [x] SPEC v1.0
- [x] Setting `hephaestus.forge.paused` in `forge_settings.py`
- [x] Forge: hold in submit, worker loop, scheduler; manual approve bypasses; `status.paused`; `set_paused`
- [x] `POST /api/hephaestus/forge/pause` + MCP tool `forge_pause`
- [x] WebUI: proxy `POST /api/webui/forge/pause`, Sviluppo header Pausa/Riprendi + banner (`ng build` ok)
- [x] Regression test `Hestia-Hephaestus/tests/test_forge_pause.py` (smoke-run, pytest suite not run)
- [x] Docs: hestia-hephaestus.md, hestia-webui.md, swagger.yml, root CHANGELOG
- [x] v2.0 dedup `hephaestus.forge.dedup_days` (Forge.find_duplicate), `approve {engine}`, proposer in WebUI + brief
- [x] v2.0 tests in `test_forge_pause.py` (smoke-run), `ng build` ok, docs + swagger
- [ ] Marko: .NET build + real run (`up-all.bat --build`), try Pausa on the Sviluppo page
