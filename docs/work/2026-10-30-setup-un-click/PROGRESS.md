# PROGRESS — One-click setup

- [x] Read today's setup (up-all.bat, init_env.py, SETUP.md, compose socket mounts)
- [x] SPEC v1.0 written
- [x] SPEC v2.0: guided setup, downloads, roles/satellites, GHCR images
- [x] Marko's ok on SPEC (v2.2, 2026-10-30)
- [x] P1 GHCR images (CI: images.yml, one package, tag → <svc>-<ver>, release) + docker-compose.images.yml (generator + --check) + install.sh (Linux + simple macOS) + up-all.sh + installer.yml CI + init_env --generate-secrets + default Ollama models
- [x] P1/P2 merged PR #70 (b8c0595) 2026-10-31; real Linux run still to do by hand (Actions → Installer → real_run)
- [x] P2 install.ps1 (PS 5.1, ASCII only with ~e accent markers so irm | iex works, CRLF) + Installa-Hestia.cmd (Windows, WSL2 resume via RunOnce) + .gitattributes
- [x] P3 Hephaestus setup endpoint (`app/setup/`: whitelisted secrets, container re-create) + Oracle `/api/llm/setup/*` (catalog, Prova, chains, downloads) + WebUI `/benvenuto` + Home «Da finire» card + Telegram one-time code + installers write hardware.json and open the setup (Marko real run pending); merged PR #71 (a71165b) 2026-10-31
- [x] P4 hestia_common.downloads + Download page (`/download`) + Oracle models / Echo voices through it + setup «Voce» + Telegram tools (Marko real run pending); merged PR #72 (47bf447) 2026-10-31
- [x] P5 Roles and satellites: Hub pairing code + node token + relay mode (satellite Hub forwards to the central, registrations rewritten to the LAN address; tried with two Hubs), satellite instance first / central copy as fallback, Oracle `use_machine` (local models on a satellite's Ollama), Hephaestus `/api/setup/machines*` + MCP tools `macchine_*`, installers `--role` / `--join --central` (`-Role`, `-Join -Central`), compose hub env, WebUI page «Macchine» (Marko real run with two machines pending)
- [ ] P5b «Da fuori casa» (cloudflared quick tunnel + setup screen)
- [ ] P6 «Aggiorna Hestia»
- [ ] P7 Docs (readme, SETUP, TESTING, module docs, swagger, ARCHITECTURE)
