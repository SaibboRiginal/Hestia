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
- [ ] PR + CI green + merge
- Left for W7 (WebUI): «Cosa ho imparato» in Memoria (learning log + Annulla), Prestazioni page in Sistema, review card
  in Sviluppo.

## W4–W8
- [ ] see SPEC §3
