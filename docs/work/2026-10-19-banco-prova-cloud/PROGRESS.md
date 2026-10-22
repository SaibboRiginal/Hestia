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
- [x] v1.2 Codespaces in one click (`start`, recommended secrets, compose overlay for Telegram/Google test credentials); `start` tried on the Claude bench (2026-10-20)
- [x] Fix 2026-10-20: `start` in Codespaces waits up to 120 s for the docker-in-docker daemon (postStartCommand can run before it is up) and logs to `.cloud-test/start.log`
- [x] Fix 2026-10-20: no docker CLI in the container (Codespace not built from the devcontainer) → clear message with «Full Rebuild Container» instead of a traceback
- [x] Fix 2026-10-22: Codespace in recovery mode — `devcontainers/python:3.12` is now Debian 13 (trixie) where the docker-in-docker feature (moby) fails; image pinned to `3.12-bookworm`
- [ ] Marko opens a Codespace with his test secrets
