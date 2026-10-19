# Progress

- [x] Read brainstorm §0 item 2, Argus/Hermes/Telegram/WebUI chat code (facts in SPEC)
- [x] SPEC v1.0 draft
- [x] Marko approved, v2.0 simplification on presence (2026-10-19)
- [ ] Archive: `chat_queue` table + `/api/chat-queue` (CAS claim) + api tests
- [ ] Argus: signal `brain.offline` with grace setting, notice via Hermes, fixed texts while offline + unit tests
- [ ] Chronos: overlay `brain_offline`, effect `chat.reply`, drain call on relax (capability `chat_queue_drain`) + tests
- [ ] Telegram: enqueue on Oracle failure, fixed reply, drain endpoint (capability `chat_queue_drain`) and at startup + tests
- [ ] WebUI: backend queue + drain endpoint, chat strip from `chat.notice` + queued bubble
- [ ] Docs: Argus/Chronos/Archive/Telegram/WebUI md, swagger, ARCHITECTURE, readme, root CHANGELOG
- [ ] Cloud bench run: stop Oracle, chat, screenshots, restart, answers
- [ ] PR, CI green, merge
