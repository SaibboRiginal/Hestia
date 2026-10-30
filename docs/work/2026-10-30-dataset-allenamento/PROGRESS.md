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

## D2 Correggi (next)
- [ ] Oracle use case `metis.dataset.review` (cloud chain), rules sheet, masking of personal data (names from People,
      emails, phones, IBAN, addresses) with local map, verdict keep/fix/drop + confidence
- [ ] Nightly agenda job, «Da rivedere» on the Miglioramento page + Telegram tool, undo signal

## D3 Esporta (next)
- [ ] `sft.jsonl`, `dpo.jsonl`, `eval.jsonl` (split by session), `card.json`; download zip (WebUI + Telegram);
      export option real vs masked data (default masked, question open to Marko)
