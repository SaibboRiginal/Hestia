# README clearer — compact public front page

| Version | Source | Status |
|---|---|---|
| 1.4 | user via external chat (project thread «Riscrivere il README più chiaro») | done |

## Goal
`readme.md` had grown into a deep reference (every env variable, MCP tool names, tunnel commands). A first-time
visitor must understand in a minute what Hestia is, how it works at a high level, how to start and how to use it.
Compact, very clear, well organised visually, with a banner at the top that Marko generates with Gemini.

## Scope
- New `readme.md`: banner (`<picture>` with `docs/assets/banner-dark.png` / `banner-light.png`), tagline, five
  badges, three pillars, «What it does» by area, simple mermaid + the four house rules, five-step quick start,
  Codespace link, «Using it» table, full module table folded in `<details>`, developer links, docs index.
- Knowledge is moved, not deleted: configuration tables, optional integrations, Forge flow and «Connect an
  external AI» (tokens, OAuth connectors, named tunnel, external MCP servers) → new `docs/SETUP.md`; roadmap →
  `docs/ARCHITECTURE.md` (Persistent Hub registry dropped: done in PR #16).
- `docs/SETUP.md` also lists the integrations of the new modules (Home Assistant, ComfyUI, Garmin/phone,
  llama-server).
- Placeholder banners (plain wordmark) so the page never shows a broken image; Marko overwrites them with the same
  file names. Gemini prompt in `docs/assets/BANNER.md`.

## Acceptance criteria
- README readable top to bottom in about two screens before the folded module list.
- No emoji, no personal data, every module of `docker-compose.global.yml` in the module table with its port.
- Every link resolves; relative links in `docs/SETUP.md` point one level up.

## Design decisions
- English stays (repo docs are English, decided in `2026-10-04-readme-rework`).
- No emoji in headings (clean style, same spirit as the client rule); feature names in Italian quotes «…» as the user
  sees them.
- v1.3: colour comes from stroke icon tiles drawn from the WebUI icon set (same paths, tone colours), never emoji;
  regenerate with `python tools/readme_icons.py`. Text inside HTML cells uses `<b>`/`<i>` (renders everywhere).
