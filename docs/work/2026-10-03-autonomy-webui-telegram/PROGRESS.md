# PROGRESS

## 1. Autonomy
- [x] Forge test env: union deps in Hephaestus + Oracle images (`requirements-forge-tests.txt`)
- [x] git `safe.directory '*'` in Hephaestus/Oracle images (Windows-mounted repo)
- [x] Built-in deploy (`forge/deployer.py`, docker socket, restart plan, rebuild notice, self-restart last)
- [x] Claude Code CLI installed by default in Oracle; wider safe tool allowlist
- [x] Work protocol in Forge prompt + `workdoc` continuation
- [x] `CLAUDE.md`, `docs/AI-GUIDE.md`, root `CHANGELOG.md`
- [x] Hephaestus/Oracle md + readme updated for the above

## 2. WebUI
- [x] Design tokens + themes + theme switcher
- [x] Component library (button, input, select, modal, drawer, tabs, menu, toast, badge, card, empty state)
- [x] DESIGN-SYSTEM.md guide
- [x] Shell (sidebar nav, routing per module)
- [x] Chat module rebuilt on components
- [x] Commands/MCP module
- [x] Calendar module (month/week/day/list, sidebar, popups, drag&drop, recurrence, skip/pause/run/cancel)
- [x] Backend proxy for agenda API

- [x] Chronos: per-occurrence move (overrides), range query start/end, include_done
- [x] Verified with `ng build` + Playwright screenshots (mocked API): week/month/list/details/editor/chat/settings, light/dark, mobile
- [ ] .NET backend not compiled here (no dotnet in the sandbox): build locally

## 3. Telegram / packets
- [x] Root cause of double reply (status edited with the answer + answer re-sent) and "Non risulta eseguita…" (no-action contract always injected in quick answers)
- [x] Packet spec (`Hestia-Shared/hestia-shared.md` § Response packets) + Oracle `notice` packets (signals, write tools, background memory after `final`)
- [x] Telegram `ReplyRenderer` (one message, expandable reasoning, streaming, notices inline/separate/important/hidden, compact/rich)
- [x] Telegram settings schema (`chat_settings.py`) + generic in-place `/settings` panel
- [x] WebUI notice rendering (`.hx-notice`, toasts) + Settings → Messaggi di sistema
- [x] Selective memory policy (gate + Claude-like extractor prompt)
- [x] Checks: py_compile + ruff (no new findings), `ng build` clean. Tests NOT run (user: no tests without permission)
- [ ] .NET `OracleEvent` notice fields not compiled here: build locally
- [ ] Next ideas: per-chat memory review command (`/memoria` list/forget), notice action buttons (e.g. "Annulla" on memory.saved)
