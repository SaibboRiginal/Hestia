# PROGRESS — Revisione completa e test del frontend

- [x] Open PRs: none left (main = 3a1c867)
- [x] Static checks: governance scripts ok (check_telegram needs `telebot`, runs in CI), pyflakes clean on all
      services, `tsc --noEmit` ok on all 26 plugin bundles
- [x] Boundaries: no service→service URL outside the Hub, no model provider outside Oracle (Echo = speech,
      allowed), no DB outside Archive, no outbound messaging outside Hermes/Telegram, no personal data, remaining
      `*.enabled` settings are all for things that act alone (notices, monthly reviews) = allowed
- [x] Fix: Kairos «Fra 3 giorni» never reminded again (the stage stayed marked as notified) + regression test
- [x] Fix: Hestia-MCP tests were never run in CI (added to the matrix)
- [x] Fix: `tools/governance/check_test_sync.py` expected Telegram test files removed in the rewrite
- [ ] Fix PR green and merged
- [ ] Bench: `cloud_test.py all` + `flows`
- [ ] WebUI pages desktop/phone × light/dark: console, network, overflow
- [ ] UI/UX analysis + proposals (`/mnt/project-files/revisione-ui/`)
