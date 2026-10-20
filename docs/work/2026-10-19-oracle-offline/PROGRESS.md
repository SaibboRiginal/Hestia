# Progress

- [x] Read brainstorm §0 item 2, Argus/Hermes/Telegram/WebUI chat code (facts in SPEC)
- [x] SPEC v1.0 draft
- [x] Marko approved, v2.0 simplification on presence (2026-10-19)
- [x] Archive: `chat_queue` table + `/api/chat-queue` (CAS claim) + api tests
- [x] Argus: signal `oracle.offline` with grace setting, notice via Hermes, fixed texts while offline + unit tests
- [x] Chronos: overlay `oracle_offline`, effect `chat.reply`, drain call on relax (capability `chat_queue_drain`) + tests
- [x] Telegram: enqueue on Oracle failure, fixed reply, drain endpoint (capability `chat_queue_drain`) and at startup + tests
- [x] WebUI: backend queue + drain endpoint, chat strip from `chat.notice` + queued bubble
- [x] Docs: Argus/Chronos/Archive/Telegram/WebUI md, swagger, ARCHITECTURE, readme, root CHANGELOG
- [x] Cloud bench run: stop Oracle, chat, screenshots, restart, answers
- [x] PR #6, CI green
- [x] Merge (PR #6, 5c2485e)
- [x] v2.2: name «Cervello offline» 🧠 → «Oracle offline» ⚠️ everywhere (texts, signal, overlay, setting, notice key, Argus module, dossier folder)
- [ ] Marko's real run with Telegram (the bench has no bot token)

## Cloud bench run 2026-10-19 12:04 (fake LLM)
Oracle stopped → WebUI message queued at once (Hub 502) with «In coda» bubble; overlay «Oracle offline» after 90 s
(grace 60 s + monitor cycle); Hermes notice «Oracle offline» delivered to webui; second message queued too. Oracle
started → both answered (attempts 1) 50 s later, presence back to «Sveglio», notice closed + «Di nuovo online dopo 2 min».
Screenshots: /mnt/project-files/cervello-offline/screenshots/ (taken before the v2.2 rename).
