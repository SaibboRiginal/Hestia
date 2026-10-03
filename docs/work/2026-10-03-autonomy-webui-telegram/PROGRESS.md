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
- [ ] Root cause of double reply + "Non risulta eseguita…" message
- [ ] Packet spec (shared) + Oracle emits packets
- [ ] Telegram renderer with display-mode settings
- [ ] WebUI renderer
- [ ] Selective memory policy
- [ ] Telegram UX overhaul
