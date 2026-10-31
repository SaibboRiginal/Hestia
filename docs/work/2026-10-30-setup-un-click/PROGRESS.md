# PROGRESS — One-click setup

- [x] Read today's setup (up-all.bat, init_env.py, SETUP.md, compose socket mounts)
- [x] SPEC v1.0 written
- [x] SPEC v2.0: guided setup, downloads, roles/satellites, GHCR images
- [x] Marko's ok on SPEC (v2.2, 2026-10-30)
- [x] P1 GHCR images (CI: images.yml, one package, tag → <svc>-<ver>, release) + docker-compose.images.yml (generator + --check) + install.sh (Linux + simple macOS) + up-all.sh + installer.yml CI + init_env --generate-secrets + default Ollama models
- [ ] P1/P2 PR green and merged (real Linux run: Actions → Installer → real_run)
- [x] P2 install.ps1 (PS 5.1, ASCII only with ~e accent markers so irm | iex works, CRLF) + Installa-Hestia.cmd (Windows, WSL2 resume via RunOnce) + .gitattributes
- [ ] P3 Hephaestus setup endpoint + guided setup «Benvenuto» + Telegram one-time code
- [ ] P4 hestia_common.downloads + Download page
- [ ] P5 Roles and satellites (pairing, join token, Dispositivi)
- [ ] P6 «Aggiorna Hestia»
- [ ] P7 Docs (readme, SETUP, TESTING, module docs, swagger, ARCHITECTURE)
