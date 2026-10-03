# PROGRESS

## 1. Autonomy
- [x] Forge test env: union deps in Hephaestus + Oracle images (`requirements-forge-tests.txt`)
- [x] git `safe.directory '*'` in Hephaestus/Oracle images (Windows-mounted repo)
- [x] Built-in deploy (`forge/deployer.py`, docker socket, restart plan, rebuild notice, self-restart last)
- [x] Claude Code CLI installed by default in Oracle; wider safe tool allowlist
- [x] Work protocol in Forge prompt + `workdoc` continuation
- [x] `CLAUDE.md`, `docs/AI-GUIDE.md`, root `CHANGELOG.md`
- [ ] Hephaestus/Oracle md + readme updated for the above

## 2. WebUI
- [ ] Design tokens + themes + theme switcher
- [ ] Component library (button, input, select, modal, drawer, tabs, menu, toast, badge, card, empty state)
- [ ] DESIGN-SYSTEM.md guide
- [ ] Shell (sidebar nav, routing per module)
- [ ] Chat module rebuilt on components
- [ ] Commands/MCP module
- [ ] Calendar module (month/week/day/list, sidebar, popups, drag&drop, recurrence, skip/pause/run/cancel)
- [ ] Backend proxy for agenda API

## 3. Telegram / packets
- [ ] Root cause of double reply + "Non risulta eseguita…" message
- [ ] Packet spec (shared) + Oracle emits packets
- [ ] Telegram renderer with display-mode settings
- [ ] WebUI renderer
- [ ] Selective memory policy
- [ ] Telegram UX overhaul
