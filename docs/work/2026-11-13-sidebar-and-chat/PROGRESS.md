# PROGRESS

- [x] Sidebar: top (bell, Chat, Cerca), Sistema as a section, module folding, active + parent, auto-open, breadcrumb
- [x] Bell with unread count (sidebar + phone menu button)
- [x] Conversations: «…» in the sidebar, delete in Cronologia; Archive `DELETE /chat/sessions/{id}`, Oracle `DELETE /api/ui/chats/{id}`
- [x] Bubble «Scrivi qui» / «Parla»
- [x] One microphone (tap = dictate, hold = voice message), always visible
- [x] «Ascolta»: spinner, reason on failure, «Apri Voce»
- [x] «Prepara la voce adesso» in the Voce page; Download links to it
- [x] Dividers: day + model in the WebUI chat; model line in Telegram; `final.model`, `chat_history.model`
- [x] Time of each owner message in the model's history; compaction keeps time and model
- [x] Tests: Archive 69, Oracle 737, Telegram 155 passed; `ng build` clean; browser check (12 scenes, mocked API)
- [x] Docs: module docs, swagger, DESIGN-SYSTEM, root CHANGELOG

Not verified here: the .NET build (one field added to `OracleEvent`), the Echo page bundle (built in Docker), a real
microphone (hold/tap checked by reading the code only), a real stack.
