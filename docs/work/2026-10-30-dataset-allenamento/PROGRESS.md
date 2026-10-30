# PROGRESS — Dataset di Hestia (SPEC v2.0)

Scope v2.0: dataset only (capture, correction, export + download); training and adapter loading out of scope.

## D1 Registra
- [x] Archive: `dataset-store` (`dataset_records`), generic `GET /count` on module stores, chat meta `training_off`
      (+ `GET /api/chat/sessions/{id}/meta`)
- [x] Oracle: `core/services/turn_trace.py`, trace pushed from `_record_turn` on all three routes (system prompt via
      `run_agent_loop(trace_out=)` / `_quick_answer(trace_out=)`, `tool_log[].result_text` hidden from clients),
      `final` frame carries `trace_id`; delete chat / `training_off` → Metis forgets the session; `chat_tag training_off`
- [x] Metis: `core/traces.py` (trace + toolset + signals rephrase / correction / tool_failed, forget, prune, status,
      recent), endpoints `/api/metis/traces*`, setting `metis.traces.keep_days`, prune in `metis.adesso.*` job
- [x] Telegram: 👍/👎 callback carries trace_id → feedback `interaction_id`
- [x] WebUI: `traceId` from `final` → vote `interactionId`; history panel «Non usare per l'allenamento»; .NET
      `OracleEvent.TraceId`
- [x] Tests: Metis `test_traces.py`, Oracle `test_turn_trace.py`, Telegram `test_voice.py` (vote id); `ng build` ok
- [x] Docs: hestia-metis/oracle/archive/telegram/webui.md, swagger, root CHANGELOG
- [ ] Undo signal (an «Annulla» of this turn's write) — moved to D2 (needs the undo path to name the trace)
- [ ] Marko: real run (.NET build, a few chats, `GET /api/metis/traces/status`)

D1 merged to main via PR #60 (47cdc98) on 2026-10-30.

## D2 Correggi
- [x] `Hestia-Metis/app/core/review.py`: Masker (Persone names from Hera, e-mails, phones, IBAN, addresses; local
      map, unmask), rules sheet R1–R8, teacher prompt, strict JSON verdict, auto-accept / pending, owner decisions
- [x] Use case `metis.dataset.review` (default chain `cloud`, new in Oracle `DEFAULT_CHAINS`), agenda job
      `metis.dataset.review` 02:30, settings `metis.review.auto_accept` / `metis.review.batch`
- [x] Endpoints `/api/metis/review/run|pending|{id}`, tools `metis_rivedi` + `metis_rivedi_decidi` (Telegram),
      WebUI Miglioramento: «Dataset di allenamento» + «Da rivedere» (Accetta / Correggi io / Scarta)
- [x] Tests `Hestia-Metis/tests/test_review.py`; docs metis/oracle.md, swagger
- [ ] Undo signal (an «Annulla» of this turn's write) — later, needs the undo path to name the trace

## D3 Esporta (next)
- [ ] `sft.jsonl`, `dpo.jsonl`, `eval.jsonl` (split by session), `card.json`; download zip (WebUI + Telegram);
      export option real vs masked data (default masked, question open to Marko)
