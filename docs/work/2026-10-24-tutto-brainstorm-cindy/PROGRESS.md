# Progress

Resume rule: read SPEC.md §3 (waves), then continue from the first unchecked box. One PR per wave on branch
`claude/project-thread-98vvlw` (restart it from main after each merge).

## W1 Rules + Oracle core
- [x] Cindy 11 `docs/REGOLE-DI-MARKO.md` + checklist in the SPEC template
- [x] Cindy 19 `hestia_common.redact`
- [x] Cindy 1 loop guard
- [x] Cindy 2 no replay after side effects
- [x] Cindy 6 origin (set by the caller, `hestia_common.origin`) + turn authority (Oracle)
- [x] Cindy 16 vision bridge
- [x] Cindy 23 conversation goal
- [x] Cindy 30 when_to_use + module manual
- [x] Cindy 13 change set (Oracle `changes` in final)
- [x] Cindy 9 hestia-ui blocks (Oracle prompt side)
- [x] D17 llama-server provider
- [x] Telegram: components as text + buttons, origin label, «Ho fatto» with undo tool buttons
- [x] goal settings, `when_to_use`/`manual` in module registrations, `mcp_helpers.undo` (Plutus)
- [x] compose service `llamacpp` (profile), docs, swagger, changelog
- [x] PR + CI green + merge (PR #34)

## W2 Hermes · Chronos · Iris
- [x] Cindy 7 + 27 + 28 routines in words (Chronos `services/routines.py`: agenda rule + instruction, pre-check,
      templates, by time / mail (Iris push) / module signal, delivery Hermes or recap, results in `chronos-store`)
- [x] B6 special events (`services/special.py`, personal setting `themis.personal.birth_date`, proposals, daily job,
      `special_moment` push to `capabilities.special_moment_endpoint`)
- [x] B8 smart calendar (`services/smart_calendar.py`, daily job, «Sposta alle» / «Lascia così»)
- [x] F manual presence + history tools (`/api/presence/manual`, `presence_set/clear/history`)
- [x] `life_api.py`: endpoints, 13 MCP tools (Telegram via dynamic menus), boot rules, recap lines
- [x] Cindy 5 «Da decidere» reminder (Hermes job + setting `hermes.attesa.richiamo_ore`)
- [x] Cindy 20 ring only on the client in use (setting `hermes.consegna.client_attivo_minuti`)
- [x] Cindy 4 secret form (Hermes `_secret` + `/secret`, Telegram «Inserisci» Mini App button)
- [x] C15 Web Push backend (Hermes `webpush.py`, `/api/push/*`, VAPID env, Archive `hermes-store`)
- [x] Archive stores `hermes-store`, `chronos-store`
- [x] tests (Chronos `test_brainstorm_life.py`, Hermes `test_hermes_brainstorm.py`), docs, swagger, changelog
- [x] PR + CI green + merge (PR #35)
- Left for W7 (WebUI): Chronos plugin pages «Routine» and «Eventi speciali» (Hermes `_link` already points to
  `chronos/routine`), secret form and «Da decidere» counter in the inbox, Web Push service worker.

## W3 Athena · Argus · Hephaestus · Atlas · Archive · Telegram parity
- [x] Cindy 3 reviewer (`Hestia-Hephaestus/app/forge/review.py`, state `reviewing`, one fix round, `review.json`)
- [x] Cindy 31 team plan (≥ `hephaestus.forge.squadra.min_servizi` services, pieces in one worktree, engine per difficulty)
- [x] Cindy 15 resume after the Claude limit (`waiting_limit`, `refs/forge/resume/<id>`, agenda `forge.resume.<id>`)
- [x] Cindy 8 quoted facts + skip when nothing new (Athena consolidator)
- [x] Cindy 18 learning log + undo, «Rivedi cosa sai di me» proposals (`learning.py`, Archive `athena-store`)
- [x] Cindy 29 docs check (`docs_check.py`, monthly job `athena.docs_check`)
- [x] D16 + 25 performance and storage growth (Argus `performance.py`, Archive `/api/blobs/usage`, «Prestazioni» settings)
- [x] Cindy 19 usage: Argus analysis and Forge proposals already redact (W1); verified
- [x] Cindy 12 site recipes (Atlas `recipes.py`, `Hestia-Atlas/recipes/*.json`, tool `atlas_ricetta`)
- [x] F: `system_performance`, `system_incidents`, `settings_proposals`, Athena thinking/signals on Telegram,
      backup tools (Archive), Telegram «Esporta i dati» / «Importa dati» / «Ripristina un backup»
- [x] tests (Forge review, Athena learning/consolidator, Argus performance, Atlas recipes, Telegram transfer), docs, swagger
- [x] PR + CI green + merge (PR #36)
- Left for W7 (WebUI): «Cosa ho imparato» in Memoria (learning log + Annulla), Prestazioni page in Sistema, review card
  in Sviluppo.

## W4 Echo · Hygieia · Hecate (+ Hercules, Plutus, Athena, Telegram)
- [x] Cindy 10 voiceprint (Echo `voiceprint.py`, filter before transcription and before live end of turn) + live
      end of turn on 1250 ms of real silence
- [x] Cindy 17 personal dictionary (Echo `dictionary.py`, hint to every engine, learns from corrections, tool
      `voce_correzione`)
- [x] B9 spoken evening diary (Hygieia `/journal/voice`, tool `selfcare_diario_voce`, use `hygieia.diario`, recap
      button via `recap.piece(actions=)` + Athena `piece_actions`, signal `diario`; Telegram takes voice notes in
      file fields)
- [x] B10 Garmin (Hecate `providers/garmin.py`, `devices_api.py`, secret form login, agenda `hecate.garmin.sync`,
      feed `wearable.daily` → Hercules activities/check-in, Hygieia sleep; presence `wearable.woke_at`)
- [x] Cindy 32 phone (Hecate `/api/gateway/phone/push` + token, presence `phone.home`/`phone.charging`, overlay
      «Fuori casa», feed `phone.notification` → Plutus transactions to review)
- [x] shared `hestia_common.feeds`; tests (Echo, Hygieia, Athena, Hecate, Hercules, Plutus); docs, swagger, env, TESTING
- [x] PR + CI green + merge (PR #37)
- Left for W7 (WebUI): page «Voce» → La tua voce (dictionary list, record voiceprint), transcript correction in the
  chat (→ `/dictionary/learn`), Hermes `command` actions opening the tool form (recap «Racconta la giornata»),
  Hecate «Dispositivi» page.

## W5 — new modules
- [x] shared `hestia_common.module_kit` (+ `FakeArchive` with blobs) and `display.file` / `display.files` (Telegram
      sends them under the card)
- [x] A4 Hera «Persone» (19025): cards, dates → Chronos special events, gift ideas on `special_moment`, `hera.daily`
- [x] B7 Kairos «Scadenze» (19028): categories + advice (`kairos.consiglio`), recurrence, calendar mirror, mail push
      → proposals, `kairos.daily`
- [x] A5 Demeter «Alimentazione» (19026): diet, meals (`demeter.stima`), supplements + intakes, coach needs
- [x] A3 Lares «Casa» (19024): HA websocket mirror, commands, scenes, quick actions, `home.present` (+ Hecate
      «Fuori casa» fix: `== false` per source)
- [x] Cindy 21 Calliope «Documenti» (19027, `/api/office`): HTML → PDF/DOCX/XLSX, 3 themes, final check, blobs
- [x] A1 Apollo «Immagini» (19022): flows, job worker, ComfyUI websocket, blobs, callback push, missing-flow notice
- [x] A2 Aphrodite «Aspetto» (19023): profiles, moments, holidays/seasons, per-client choice, pets, pictures via Apollo
- [x] Hub allowed tags/domains for the seven modules (CI caught the 422; test covers module_kit registrations)
- [x] Archive stores (7), compose services, CI matrix, Telegram areas, swagger, .env.example, docs, tests
- [ ] PR + CI green + merge
- Left for W7 (WebUI): plugin bundles (`ui/`) of the seven modules (Persone, Scadenze, Alimentazione, Casa,
  Documenti, Immagini with flow upload, Aspetto settings) and the WebUI drawing `/api/appearance/now` (palette,
  effect, pet).
- Left for W8: cloud bench flows (`tools/cloud_test/flows.py`) for the seven modules.

## W6–W8
- [ ] see SPEC §3
