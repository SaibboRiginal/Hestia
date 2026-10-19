# PROGRESS — Prove reali sul banco cloud

- [x] SPEC v1.0 (scope: the real runs the pending dossiers wait for, on the cloud bench, fake LLM)
- [x] Fake LLM scripted tools (`#tool name {args}` → native `tool_calls` / `<tool_call>`, current turn only)
- [x] `tools/cloud_test/flows.py` + `python tools/cloud_test.py flows [area…]`: 9 areas (hercules, hygieia,
      wardrobe, agenda, presence, settings, plugins, mcp, webui), report `.cloud-test/flows.md`, screenshots `.cloud-test/flows/`
- [x] Fix: Hercules suggested the bodyweight as kg on bodyweight exercises (+ test)
- [x] Fix: Hygieia AHA «suggested» after a retinol evening; clash reason names the product (+ test)
- [x] Fix: Wardrobe Italian labels («ufficio») → vocabulary keys, occasion no longer ignored (+ test)
- [x] Fix: Oracle WebUI chats count as user activity for presence (+ test)
- [x] Fix: 7 plugin icons missing in the WebUI (flows check covers every catalog icon)
- [x] Presence SPEC v2.4: state tool is `stato`, not `assistant_state`
- [x] PROGRESS of every pending dossier updated with what the bench verified
- [x] Docs: module md (hercules, hygieia, wardrobe, oracle, webui), DESIGN-SYSTEM, TESTING.md, root CHANGELOG
- [x] Full run: 47/47 green (report `cloud-test/2026-10-19/prove-reali.md` in the project files)
- [ ] PR merged with CI green
- [ ] Left for Marko (not possible from the cloud): Telegram, a real model (Gemini key or Ollama), claude.ai connector over the tunnel, his own real use
