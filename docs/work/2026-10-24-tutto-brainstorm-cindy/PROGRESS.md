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
- [ ] PR + CI green + merge
- Left for W7 (WebUI): Chronos plugin pages «Routine» and «Eventi speciali» (Hermes `_link` already points to
  `chronos/routine`), secret form and «Da decidere» counter in the inbox, Web Push service worker.

## W3–W8
- [ ] see SPEC §3
