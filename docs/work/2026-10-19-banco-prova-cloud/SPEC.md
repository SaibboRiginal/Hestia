# Cloud test bench — run the whole Hestia stack in a Claude cloud session

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (Marko: «"Banco di prova cloud" si ma funziona se non abbiamo tutto e oracle? non ho piu accesso per 2 settimane al mio PC locale») |
| **Status** | Draft — waiting Marko's choice (bench / 24/7 hosting / both) before coding |

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

## Scope
1. `docker-compose.cloud-test.yml` override (no change to `docker-compose.global.yml` behaviour):
   images from `mirror.gcr.io`, proxy CA injected at build/run time only when a CA file is given, no host
   Ollama, Atlas excluded (host-only service).
2. LLM for Oracle, chosen by what the environment provides:
   - Gemini or Claude key as an **environment secret** of the cloud environment (never in the repo) → real chat;
   - no key → a deterministic fake LLM (in Hestia-Dummy, which exists for testing) so every flow that does not
     need real reasoning still runs.
3. `tools/cloud_test.py`: generate throwaway `.env` files from `.env.example` with random test secrets
   (never committed), build, start, wait for health, run a smoke list through the Hub, drive the WebUI with
   Playwright (Chromium is pre-installed), write a report + screenshots.
4. Docs: `TESTING.md` section «Banco di prova cloud», AI-GUIDE pointer, root CHANGELOG.

## Out of scope
- 24/7 hosting (Oracle Cloud Free + Cloudflare Tunnel + Access): separate dossier if Marko picks it.
- Telegram bot live run (needs Marko's bot token; a test bot token as env secret would enable it later).
- Google/Microsoft OAuth flows (need Marko's consent in a browser).

## Acceptance criteria
- One command in a fresh cloud session brings every service to healthy (or reports exactly which is not and why).
- The report lists: build result per service, health per service, smoke checks, WebUI screenshots
  (Home, Chat, Sistema, each domain plugin), and whether the LLM was real or fake.
- No personal data, token or generated `.env` is tracked; works without any secret (fake LLM).

## Design decisions
- Override file instead of editing the global compose: Marko's local run stays exactly as it is.
- Fake LLM lives in Hestia-Dummy and is reached by Oracle as a normal provider endpoint (Oracle stays the only
  LLM caller, no new client elsewhere).
- The proxy CA path is an infrastructure input (env), not a Themis setting.
