# README rework — public front page

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (project thread "README") | done |

## Goal
The repository is public: `readme.md` must read as a serious open-source front page (intro with badges, quick start
in as few commands as possible with the minimum settings, then capabilities, architecture, roadmap, docs).
The internal content (rules, contracts, per-service notes) must not be lost.

## Scope
- Move the old `readme.md` verbatim to `docs/ARCHITECTURE.md` (git rename, history kept) with a short header.
- New English `readme.md` (repo docs are English): badges, features, quick start, configuration (minimum +
  optional integrations), architecture (mermaid + service table), Forge flow, structure, development, roadmap,
  documentation index, license note.
- `tools/init_env.py`: creates every `.env` compose needs from `.env.example` (never overwrites, never prints values).
- Missing templates: `Hestia-Telegram/app/.env.example`, `Hestia-Scout/app/.env.example`; the optional compose
  variables (WebUI keys, Claude Code build flag, RPi DB URL) added to the root `.env.example` created by the
  db-hardening task (`HESTIA_DB_PASSWORD`). No real values.
- "Global rules" location moves to `docs/ARCHITECTURE.md`: `tools/governance/check_docs_sync.py` (gate + topology
  check), `CLAUDE.md`, `docs/AI-GUIDE.md`, Forge prompt (`Hestia-Hephaestus/app/forge/prompts.py`).

## Acceptance criteria
- Quick start = clone → `python tools/init_env.py` → 2 values in Telegram `.env` + `HESTIA_DB_PASSWORD` (+ notify chat id) → pull models →
  `docker compose up`.
- No credentials or real ids in examples.
- `check_readme_topology_coverage()` passes on `docs/ARCHITECTURE.md` (WebUI section added, was missing).

## Design decisions
- File name stays `readme.md` (renaming case on Windows checkouts is error-prone; GitHub renders it anyway).
- The public README is no longer gated by the docs-sync check; the rules doc is.
- Roadmap built from the old "Known Gaps", "Deployment Evolution Contract" and `Hestia-Metis/TODO.md`.
- No LICENSE added (owner's decision); README states that none is published yet.
