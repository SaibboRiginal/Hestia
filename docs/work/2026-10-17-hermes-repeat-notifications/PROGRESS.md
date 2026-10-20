# PROGRESS — Hermes repeat notifications

- [x] SPEC v1.0 written
- [x] Marko confirms the SPEC (2026-10-17)
- [x] P1 Hermes: replaces, chain/counter, superseded, resolves, inbox, setting, tests (written, not run)
- [x] P2 Telegram: superseded delete/fallback, repeat line, button on replaced message
- [x] P3 WebUI frontend: superseded removal, repeat badge (card + toast)
- [x] P4 Docs + swagger + ARCHITECTURE; Self care / Guardaroba / Coach threads told via channel session
- [x] Root CHANGELOG line
- [ ] Marko: real run (up-all.bat --build), then a module using `replaces` (Self care / Guardaroba / Coach)
- [x] Real run on the cloud bench (2026-10-19) with Self care: same reminder 3 days → one live notification «Saltato 2 volte · dal 19 ott», the replaced one answers 409, «Fatto» closes the chain and logs the routine, the next one starts from zero → `docs/work/2026-10-19-prove-reali-banco/`. Telegram delete/edit not testable from the cloud
