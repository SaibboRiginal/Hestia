# Progress

- [x] Read brainstorm §0 item 2, Argus/Hermes/Telegram/WebUI chat code (facts in SPEC)
- [x] SPEC v1.0 draft
- [x] Marko approved, v2.0 simplification on presence (2026-10-19)
- [ ] Archive: `chat_queue` table + `/api/chat-queue` (CAS claim) + api tests
- [ ] Argus: signal `brain.offline` with grace setting, notice via Hermes, fixed texts while offline + unit tests
- [ ] Chronos: overlay `brain_offline`, effect `chat.reply`, drain call on relax (capability `chat_queue_drain`) + tests
- [ ] Telegram: enqueue on Oracle failure, fixed reply, report to Argus, drain on `system.brain online` and at startup + tests
- [ ] WebUI: backend `/api/system/brain`, queue + drain, chat strip from `chat.notice` + queued bubble
- [ ] Docs: Argus/Hermes/Archive/Telegram/WebUI md, swagger, ARCHITECTURE, readme, root CHANGELOG
- [ ] Cloud bench run: stop Oracle, chat, screenshots, restart, answers
- [ ] PR, CI green, merge
