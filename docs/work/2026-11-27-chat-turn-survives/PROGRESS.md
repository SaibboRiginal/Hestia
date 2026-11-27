# PROGRESS — chat turn survives

- [x] Cause found (disconnect cancels the turn, history saved at the end, chat not reloaded, 4-min cap, Telegram timeout)
- [x] Design agreed with Marko (option «turno lato server ovunque»)
- [x] Oracle live_turns + endpoints live / live/stream / stop + heartbeat
- [x] Engine and document analyser save his message at the start; reasoning saved with the answer
- [x] Archive `chat_history.steps`
- [x] WebUI ChatHub attach/detach/stop, no 4-min cap; frontend reload + reconnect reattach, reasoning from history
- [x] Telegram follows a broken stream again
- [x] Docs + swagger + regression tests
- [ ] PR green and merged
