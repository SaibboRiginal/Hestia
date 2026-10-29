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
- [x] PR + CI green + merge (PR #38, 7961538)
- Left for W7 (WebUI): plugin bundles (`ui/`) of the seven modules (Persone, Scadenze, Alimentazione, Casa,
  Documenti, Immagini with flow upload, Aspetto settings) and the WebUI drawing `/api/appearance/now` (palette,
  effect, pet).
- Left for W8: cloud bench flows (`tools/cloud_test/flows.py`) for the seven modules.

## W6 — «Adesso» and «Scopri» backend
- [x] Archive `metis-store` (MetisRecord, router, swagger)
- [x] Metis `core/usage.py`: taps, habits, agenda items, ideas (use case `metis.adesso`), Scopri, stats, prune
- [x] Metis endpoints `/api/metis/usage`, `/usage/stats`, `/adesso`, `/adesso/refresh`, `/scopri`; tools
      `metis_adesso`, `metis_scopri` (display cards); agenda jobs `metis.adesso.0700/1230/1800`; `when_to_use` fixed
      (it described memory notes, which live in Oracle)
- [x] Telegram: taps pushed at every action start; Oggi card «Adesso» with reasons (fallback fixed actions);
      `/adesso`, `/scopri`
- [x] tests: `Hestia-Metis/tests/test_usage.py` (Metis added to the CI matrix, it was missing), Telegram `TestAdesso` + commands
- [x] docs: hestia-metis.md, hestia-telegram.md, hestia-archive.md, swagger, ARCHITECTURE, flow map, SPEC v1.6
- [x] fix: `hestia_common.feeds` empty registry cache looked fresh right after boot (CI runner), regression test in Hecate
- [x] PR + CI green + merge (PR #39, dadbc79)
- Left for W7: WebUI Home «Adesso» row, Ctrl+K palette entries, «Scopri» page, WebUI taps (pages + actions).

## W7 — WebUI, part 1: pages of the seven new modules
- [x] shared `ModuleKit.webui()` (PluginClient + manifest router + Hub capabilities); Dockerfiles build `ui/` in a
      node stage (`/code/ui/dist`, not hidden by the compose mounts)
- [x] Hera «Persone» / «Persona» + widget; endpoints `POST /{id}/gift`, `/{id}/gift/{gid}/done`, `/{id}/like`
- [x] Kairos «Scadenze» / «Scadenza» + widget (proposals, Fatto, Dopo, advice)
- [x] Demeter «Alimentazione», «Dieta», «Integratori» + widget (meals with «Annulla», supplements «Preso»)
- [x] Lares «Casa» + widget + quick action «Casa» (`GET /quick` chips)
- [x] Calliope «Documenti creati» (`GET /{id}/b64` download through the Hub)
- [x] Apollo «Immagini», «Immagine», «Flussi» (`GET /jobs/{id}/image/{n}`)
- [x] Aphrodite «Aspetto» (`GET /image/{blob}`, `POST /pets/{id}/image/{pose}`)
- [x] tests `tests/test_webui_plugin.py` in each module (manifest elements = bundle elements, new endpoints); docs, swagger
- [x] PR + CI green + merge (PR #40, c25e52a)

## W7 — WebUI, part 2: pages in the system modules
- [x] Chronos «Routine» (new in words, gallery, run / pause / delete) and «Eventi speciali» (add, remove); owner routes
      also under `/api/agenda/` (plugin prefix); `_link` of the special notices
- [x] Athena «Cosa ho imparato» (learning log with «Annulla», pending proposals, «Rivedi cosa sai di me»;
      `GET /memory/proposals`; proposal cards link here)
- [x] Argus «Prestazioni» (last sample over the limits, storage, 24 h chart)
- [x] Hephaestus Sviluppo: «Revisione automatica» card; states `reviewing` / `waiting_limit` labelled and counted open
- [x] Echo «Voce → La tua voce» (voiceprint, dictionary) + «Correggi la trascrizione» → `/dictionary/learn`
- [x] Hecate plugin «Dispositivi» (Garmin, phone) — first Hecate bundle (Dockerfile Node stage)
- [x] tests (Chronos plugin routes, Athena proposals, Argus/Athena manifests, Forge counts, Hecate manifest); docs, swagger
- [x] PR + CI green + merge (PR #41, a7c3aba)

## W7 — WebUI, part 3a (Angular shell)
- [x] Home «Adesso» row, Ctrl+K group «Adesso», «Scopri» page (`/scopri`), WebUI taps (`services/metis.service.ts`)
- [x] palette, effect and pet from `GET /api/appearance/now` (`services/appearance.service.ts`, `hx-appearance-layer`,
      `ThemeService.setPalette`); Personali → Aspetto row
- [x] Web Push: `services/push.service.ts`, `public/sw.js` push + notificationclick; Personali → Messaggi row;
      Hermes doors `/api/ui/push/*`
- [x] Hermes inbox: «Da decidere», secret form (`/api/ui/inbox/{id}/secret`), `execute: command` → Comandi
- [x] Hestia-MCP Comandi deep link `?command=&args=&run=1`
- [x] `ng build` ok; Hermes test `test_ui_doors_for_secret_form_and_web_push`; docs (webui, DESIGN-SYSTEM, hermes, mcp), swagger
- [x] PR + CI green + merge (PR #43, f535dce)

## W7 — WebUI, part 3b (Angular shell + conversations)
- [x] Cindy 26 backend: Archive `chat_session_meta` + `/api/chat/sessions/list|tags|{id}/meta`; Oracle
      `core/services/chat_sessions.py`, tools `chat_tag` (undo) / `chat_list` (Telegram card), `/api/ui/chats*`
- [x] new sidebar: SVG logo, Cerca + Parla, Generale above Fissati, Conversazioni (pinned or 3 latest), history
      sidebar (search, dates, tags, pin, title), Sistema as one entry + `/sistema` page
- [x] live overlay from anywhere (sidebar, Home, Ctrl+Shift+Space; pet as face) + «Detta» in the chat (`webui.dettatura`)
- [x] answer components (```hestia-ui), «Ho fatto» with «Annulla» (changes frame), origin label; .NET `OracleEvent`
      gets `items` + `origin` (not built here: no dotnet)
- [x] tests: Archive `test_chat_sessions.py`, Oracle `test_chat_sessions.py`; `ng build` ok; docs, swagger
- [x] PR + CI green + merge (PR #45, c958b4b)

## W8
- [ ] see SPEC §3
