# SPEC — autonomy (Claude Code), WebUI rewrite + AI calendar, Telegram/client packets

Requested by the user on 2026-10-03. Order: 1 → 2 → 3.

## 1. Hestia programs itself with Claude Code
- Forge + Claude Code (in Oracle) must really work end to end: worktree, tests runnable for any
  service, commit, approval, merge, restart, health check, rollback.
- Knowledge for future runs: `CLAUDE.md` (auto-read by Claude Code), `docs/AI-GUIDE.md`.
- Mandatory work protocol for every task: `docs/work/<name>/SPEC.md`, `PROGRESS.md` (checklist),
  `CHANGELOG.md` (spec changes) + root `CHANGELOG.md`. Forge prompt enforces it; tasks can be continued
  (`workdoc`).
- Acceptance: a Telegram request "sviluppa …" with engine claude produces a reviewed diff with tests
  and docs, merge restarts the touched containers.

## 2. WebUI (Angular) rewrite
- Claude-like style; whole theme in CSS tokens; switchable themes update the entire UI.
- Reusable standard components + `DESIGN-SYSTEM.md` guide for AI models adding modules.
- Modules: chat (working), MCP/commands manager, **AI calendar** (assistant agenda only for now;
  later Google/Microsoft as separate, highlighted layers): month / week / day / list views, sidebar
  with mini-calendar and filters (owner/type), popups for details/create/edit, drag & drop move,
  recurrences, skip occurrence, pause, run now, cancel.

## 3. Telegram + uniform client packets
- Standard response packets for all clients (chat, system notices: memory saved/forgotten, action
  done, error, warning, info, question), each with kind, icon, severity; clients render them.
- System messages visually distinct from chat; **every display mode available as a setting**
  (compact line under answer, separate styled message, only important, hidden).
- Selective memory like Claude: only durable, useful facts or explicit "ricorda".
- Fix: "test" → double "ciao" + "Non risulta eseguita alcuna azione di modifica".
- Telegram should feel like a Claude/Codex chat (one streamed answer, optional reasoning, reliable
  commands, clear confirmations). Keep structure where sensible.
