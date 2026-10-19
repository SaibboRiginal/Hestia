# Progress

- [x] Read brainstorm §0 item 2, Argus/Hermes/Telegram/WebUI chat code (facts in SPEC)
- [x] SPEC v1.0 draft
- [ ] Marko approves SPEC (or asks changes → SPEC v1.x)
- [ ] Archive: `chat_queue` table + `/api/chat-queue` (CAS claim) + api tests
- [ ] Argus: brain state, `/api/argus/brain`, `/brain/report`, grace setting, fixed texts while offline, `system.brain` events + unit tests
- [ ] Hermes: `_system` pass-through to clients, narration skip while offline, `system.brain` bootstrap subscription + tests
- [ ] Telegram: enqueue on Oracle failure, fixed reply, report to Argus, drain on `system.brain online` and at startup + tests
- [ ] WebUI: backend `/api/system/brain`, queue + drain, SignalR banner/queued bubble; frontend banner
- [ ] Docs: Argus/Hermes/Archive/Telegram/WebUI md, swagger, ARCHITECTURE, readme, root CHANGELOG
- [ ] Cloud bench run: stop Oracle, chat, screenshots, restart, answers
- [ ] PR, CI green, merge
