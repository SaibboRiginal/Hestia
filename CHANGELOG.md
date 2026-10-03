# Hestia CHANGELOG

One line per finished task (details in `docs/work/<task>/`).

## 2026-10-03
- WebUI rewritten: Claude-like themable design system + UI kit + DESIGN-SYSTEM.md, module registry, Chat, Commands & MCP, Documents, Settings, and a Google-like calendar for Hestia's agenda (month/week/day/list, drag & drop, recurrences, exceptions).
- Forge really self-develops with Claude Code: test env for all services, built-in container restart deploy, mandatory work protocol (SPEC/PROGRESS/CHANGELOG), `CLAUDE.md` + `docs/AI-GUIDE.md`.
- Mail via Gmail OAuth token only (IMAP removed); Forge `cloud` profile derived from existing Gemini vars.
- Embeddings fitted to 768 dims (semantic search was silently off).

## 2026-10-02
- Assistant agenda across all modules; WebUI review fixes (security, broken flows); Google OAuth merge (tunnel + PKCE).
