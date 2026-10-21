# Progress

- [x] Read brainstorm item 10 and current memory/MCP code
- [x] SPEC v1.0
- [x] Marko approves SPEC (2026-10-20 «ok»)
- [x] Oracle: `POST /api/memory/note`, origin in extra_data, dedup; `memory_note` + `memory_recall` tools
- [x] Oracle plugin: Memoria page (list, search, origin filter, forget); icon `bookmark` in both icon sets
- [x] Tests: `Hestia-Oracle/tests/test_memory_note.py` (Oracle suite 468 passed) + plugin build + tsc + check_icons
- [x] Docs (oracle md, mcp md, swagger, ARCHITECTURE, flow map, root CHANGELOG)
- [x] PR #19, CI green, merged 2026-10-21 (9ca6af0)
- [ ] Marko real run: connect Claude with a write access, say a fact, ask it to note it, see it in Memoria and in a WebUI chat

## Notes
- Existing accesses limited to a tool list need `memory_note` / `memory_recall` added in Accessi AI; `[]` = all tools.
- `memory.save` / `memory.search` stay for Oracle's own chats (not external).
