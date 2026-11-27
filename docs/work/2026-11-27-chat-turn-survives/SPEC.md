# SPEC — A chat answer survives the owner leaving the page

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via external chat (Marko, 2026-11-27: «ho scritto in chat e poi sono uscito e tornato mentre pensava: il messaggio è andato perso con la risposta»; then «perdo anche il ragionamento quando ritorno sulla chat») |
| **Status** | Done |

## 1. Today (verified in code)

- WebUI `ChatHub.OnDisconnectedAsync` → `CancelStream`: the HTTP stream to the Hub is aborted, the Hub closes the
  upstream, Oracle's turn generator stops half way.
- Oracle `engine._save_history` saved **both** the owner's message and the answer only at the end of the turn.
- The WebUI chat page started empty after a reload: the current conversation was not loaded again.
- `OracleStreamService.StreamViaHub` cut every answer after 4 minutes (`CancelAfter`).
- Telegram: a read timeout (Oracle silent while a local model waits in line) or a broken connection lost the turn.
- The reasoning steps were never saved: a reopened chat showed answers without their «Ragionamento».

## 2. Goal

His message is saved at once; the answer is always finished and saved, whoever watches; when he comes back the chat
shows his message, the answer still being written (live, with its reasoning) and then the final one. Same for every
client. Only «Stop» stops an answer.

## 3. Scope and design (agreed with Marko 2026-11-27, option «turno lato server ovunque»)

- **Oracle `core/services/live_turns.py`**: `/api/chat` and the document endpoints start the turn in its own thread
  (`start`); the HTTP response only follows it (`follow`). Every frame is kept in memory while the turn runs and for
  2 minutes after. A silent turn sends `{type: heartbeat}` every 15 s (no proxy/client timeout cuts it).
  `GET /api/chat/live`, `GET /api/chat/live/stream?offset=`, `POST /api/chat/stop`. Response header `X-Hestia-Turn`.
- **Engine**: `_save_user_message` right after the history load (never twice in the prompt; compaction drops the
  trailing copy); `_save_history(..., user_saved=True)` saves the answer and its reasoning frames
  (`live_turns.steps()`: `thinking` / `agent`, max 200, 4000 chars each). Documents: same (`analyser._save_user`).
- **Archive**: additive column `chat_history.steps` (JSONB); `POST/GET /api/chat/history` carry `steps`.
  Oracle `/api/ui/chats/{id}/messages` returns them.
- **WebUI backend**: disconnect = stop reading only; `cancel` = «Stop» → Oracle `/api/chat/stop`; new `attach`
  (answer `live` + the turn's frames from the start + `stream_done`) and `detach` (another conversation opened: the
  answer goes on and is saved); heartbeat frames are not forwarded; no 4-minute cap.
- **WebUI frontend**: on page load the current conversation comes back from Archive (with each answer's reasoning),
  then `attach`; after a SignalR reconnect (or back on the page after the connection gave up) during an answer the
  same. Opening another conversation detaches, it does not stop.
- **Telegram**: when the stream breaks, `follow_live_turn` reads the same turn again from the last frame into the same
  message (3 attempts); heartbeats ignored.
- **Others**: Chronos routines, MCP door and voice use the same Oracle path, so their turns also finish and are saved.

## 4. New feature checklist
1. Real job for the owner: nothing written is lost when he leaves the chat.
2. Owner module (R1): Oracle (turn), Archive (storage), clients only follow.
3. Configuration: none (heartbeat/grace are protocol constants, not tunables).
4. Push or poll: the client follows the turn (push stream); reattach on load/reconnect.
5. Who confirms: nobody — nothing new is done for him, only kept.
6. WebUI / Telegram: same answer bubble / message, no new UI.
7. Stop, correct, undo: «Stop» stops; leaving never does.
8. Docs: hestia-oracle.md, hestia-webui.md, hestia-telegram.md, hestia-archive.md, swagger.
9. Texts: no new texts for people.

## 5. Acceptance criteria
- Write, leave the page (or reload) while it thinks, come back: his message is there, the answer continues live with
  its reasoning, then the final answer; after a later reload both stay, with the reasoning.
- «Stop» still stops the answer; opening another conversation does not.
- A long «Thinking» answer (> 4 min) is no longer cut in the WebUI.
- Telegram: a broken stream continues in the same message.
- Regression tests: `Hestia-Oracle/tests/test_live_turns.py`.
