# Cloud test bench — run the whole Hestia stack in a Claude cloud session

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via external chat (Marko: «"Banco di prova cloud" si ma funziona se non abbiamo tutto e oracle? non ho piu accesso per 2 settimane al mio PC locale») |
| **Status** | Implemented on branch `claude/project-thread-gohyx3` 2026-10-19; first full run green |

## Goal
Marko cannot reach his PC for two weeks. A Claude cloud session must be able to start the **whole** stack
(every compose service, WebUI .NET + Angular included), drive it like a user and report back with screenshots,
so the "Marko build + real run" step stops waiting on his PC.

## Facts checked in a cloud session (2026-10-19)
- `dockerd` is installed and starts as root (overlayfs). 4 CPU, 15 GB RAM, no GPU, ~30 GB free disk.
- Docker Hub answers `429 Too Many Requests` (shared anonymous IP). `mirror.gcr.io/library/*`,
  `mirror.gcr.io/ankane/pgvector`, `mcr.microsoft.com/dotnet/*` pull fine.
- Containers reach the internet only through the session's TLS proxy: builds must trust its CA.
- An inbound tunnel (`cloudflared`) is blocked by the session's safety guard; the container is ephemeral.
  So the bench is **not** a public Hestia: it is driven from inside the session.
- (v1.1) Network policy: Debian's apt servers (`deb.debian.org`) and Alpine's CDN are blocked, Ubuntu's archive is
  allowed; pypi, npm, NuGet, Microsoft's registry and Google's Gemini API are allowed; `api.deepseek.com`,
  Hugging Face and the Ollama registry are blocked (no real local model can be downloaded).
- (v1.1) Two interception CAs: the agent proxy's (host tools) and the egress gateway's (direct connections, what
  containers use). Both are in `/root/.ccr/ca-bundle.crt`.

## Scope
1. `docker-compose.cloud-test.yml` override (no change to `docker-compose.global.yml` behaviour):
   images from `mirror.gcr.io`, proxy CA injected at build/run time only when a CA file is given, no host
   Ollama, Atlas excluded (host-only service).
2. LLM for Oracle, chosen by what the environment provides:
   - Gemini or Claude key as an **environment secret** of the cloud environment (never in the repo) → real chat;
   - no key → a deterministic fake Ollama (`tools/cloud_test/fake_ollama.py`) so every flow that does not
     need real reasoning still runs; its answers start with «[LLM finto]».
3. `tools/cloud_test.py`: generate throwaway `.env` files from `.env.example` with random test secrets
   (never committed), build, start, wait for health, run a smoke list through the Hub, drive the WebUI with
   Playwright (Chromium is pre-installed), write a report + screenshots.
4. Docs: `TESTING.md` section «Banco di prova cloud», AI-GUIDE pointer, root CHANGELOG.

## Decisions (v1.1, Marko 2026-10-19)
- No 24/7 hosting needed. Two ways in: Claude cloud session (Claude runs it, sends report + screenshots) and
  **GitHub Codespaces** for Marko to click himself (private forwarded port, GitHub login) — one configuration.
- Fake LLM is a stand-alone stdlib server in `tools/cloud_test/` (not Hestia-Dummy): it speaks the Ollama API, so
  Oracle needs only `OLLAMA_URL` changed — no new provider, no settings change.
- Restricted network: Ubuntu 24.04 stand-ins for `python:3.12-slim` and `dotnet/aspnet:9.0` under the same tags
  (Dockerfiles unchanged); images labelled `hestia.cloud-test` so they are never mistaken for official ones.

## Out of scope
- 24/7 hosting (Oracle Cloud Free + Cloudflare Tunnel + Access): not needed (Marko).
- Telegram bot live run (needs Marko's bot token; a test bot token as env secret would enable it later).
- Google/Microsoft OAuth flows (need Marko's consent in a browser).

## Acceptance criteria
- One command in a fresh cloud session brings every service to healthy (or reports exactly which is not and why).
- The report lists: build result per service, health per service, smoke checks, WebUI screenshots
  (Home, Chat, Sistema, each domain plugin), and whether the LLM was real or fake.
- No personal data, token or generated `.env` is tracked; works without any secret (fake LLM).

## Design decisions
- Override file instead of editing the global compose: Marko's local run stays exactly as it is.
- Oracle stays the only LLM caller: the fake LLM only replaces the Ollama host.
- The proxy CA path is an infrastructure input (env), not a Themis setting.

## First run (2026-10-19)
- 21 services built and healthy (Telegram skipped: no bot token); .NET WebUI + Angular built in the cloud.
- Smoke: Hub 18 registered, Oracle answers (fake), Themis 15 modules, Hestia-MCP ok; WebUI 41 pages screenshotted,
  0 JavaScript errors, chat round trip works.
- **Bug found and fixed**: *Mappa* showed WebUI and Hermes offline after 3 min (and a Hub restart would forget
  them, so Hub routing to Hermes would fail until a container restart). Hermes started its keepalive thread only
  when every first registration failed; the WebUI had no keepalive. Both now re-register every 60 s; regression
  test `TestHubKeepalive` (Hermes); verified on the bench (both online after > 3 min).
