# Progress

- [x] Check what a cloud session allows (docker, images, network, tunnel) — SPEC «Facts»
- [x] SPEC v1.0 draft; v1.1 Marko's decisions (no 24/7, Codespaces)
- [x] `docker-compose.cloud-test.yml` (fake LLM, Oracle without Claude Code CLI)
- [x] Base images: mirrors, Ubuntu stand-ins on restricted network, interception CAs (`tools/cloud_test/base/`)
- [x] Fake Ollama `tools/cloud_test/fake_ollama.py`
- [x] `tools/cloud_test.py` (prepare, up, check with smoke + Playwright screenshots, token, logs, down)
- [x] `.devcontainer/devcontainer.json` (Codespaces)
- [x] First full run in a Claude cloud session: all healthy, report + screenshots
- [x] Fix from the run: Hub keepalive in Hermes and WebUI (+ regression test, docs)
- [x] Docs: TESTING.md, CLAUDE.md, AI-GUIDE, ARCHITECTURE, Hermes/WebUI md, swagger, root CHANGELOG
- [ ] Gemini mode tried with a real key (needs `GEMINI_API_KEY` as environment variable / Codespaces secret)
- [ ] Marko tries a Codespace himself
- [x] Real flows: `python tools/cloud_test.py flows [area…]` (fake LLM scripted tools `#tool name {args}`), first full run 47 steps → `docs/work/2026-10-19-prove-reali-banco/`
