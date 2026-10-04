# Hestia CHANGELOG

One line per finished task (details in `docs/work/<task>/`).

## 2026-10-04
- GitHub "Hestia Tests" workflow green again: CI installs the real test deps (httpx, pinned <0.28 for old-Starlette services), no fail-fast, test-less Swagger job dropped; stale tests fixed (Athena hardcoded date, Oracle two-line signal/notice output and ask(thinking=) mocks, Hecate OAuth wording and token-call lookup). [ext-chat]
- "Crea con Hestia": assistant drawer from every page (Ctrl+J, calendar, Sviluppo, Comandi) with page context; more agenda tools, live refresh on agenda/Forge notices, generic agenda links with cascade cancel/error (used by Forge), Hestia proposes a Forge task when no tool can do it. Calendar extras: quick add in natural language, module logs per occurrence, ICS feed for phones, working-hours shading. [ext-chat]
- WebUI "Sviluppo" page (Codex/Claude Code style): Forge tasks with the full engine conversation (live for Claude Code), files, diff, dossier, tests, logs, follow-up and retry; read-only repository browser (commit graph, commits, files, branches, compare, tags, dossiers). New Hephaestus `/forge/tasks/{id}/*` and `/repo/*` endpoints. [ext-chat]
- Calendar "Da un modulo…" wizard: modules declare creatable items (templates) via the agenda client; Scout, Athena, Argus, Forge ship the first ones. [ext-chat]
- Calendar: month-view navigation fix, 24h-only date/time fields, window lanes with visible time range, compact frequent rules, focused view (horizon/past rules), Vista popover; Chronos per-occurrence run log. [ext-chat]
- Work protocol: dossiers carry Version + Source; changelog lines tagged with their source. Spec v1.0 for calendar fixes/views, module wizards, prompt-generated Skills, Sviluppo (Forge/repo) page → `docs/work/2026-10-04-calendar-skills-forge-ui/` [ext-chat]
- WebUI Docker build fixed: Google Fonts no longer inlined at build time (failed without internet). [ext-chat]

## 2026-10-03
- Standard response packets: Oracle `notice` (system messages) rendered distinctly by Telegram and WebUI with many display settings; Telegram replies rebuilt Claude-like (one message, expandable reasoning, streaming, in-place `/settings` panel); selective Claude-like memory; fixed double "ciao" and spurious "Non risulta eseguita alcuna azione".
- WebUI rewritten: Claude-like themable design system + UI kit + DESIGN-SYSTEM.md, module registry, Chat, Commands & MCP, Documents, Settings, and a Google-like calendar for Hestia's agenda (month/week/day/list, drag & drop, recurrences, exceptions).
- Forge really self-develops with Claude Code: test env for all services, built-in container restart deploy, mandatory work protocol (SPEC/PROGRESS/CHANGELOG), `CLAUDE.md` + `docs/AI-GUIDE.md`.
- Mail via Gmail OAuth token only (IMAP removed); Forge `cloud` profile derived from existing Gemini vars.
- Embeddings fitted to 768 dims (semantic search was silently off).

## 2026-10-02
- Assistant agenda across all modules; WebUI review fixes (security, broken flows); Google OAuth merge (tunnel + PKCE).
