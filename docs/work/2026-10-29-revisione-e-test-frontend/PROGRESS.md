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
- [x] Fix PR #49 green and merged (e721201)
- [x] Bench: `cloud_test.py all` 31 containers healthy, `flows` 65/65 green
- [x] WebUI: 70 pages × desktop light/dark, tablet, phone light/dark (Playwright, script in the thread scratchpad):
      0 console errors, 0 failed or 4xx/5xx requests, 0 horizontal overflow. Only benign Chrome warnings
      («cross-world service worker» preload).
- [x] Visual fixes found by looking at the screenshots (second PR):
  - phone: the menu button covered the title of «Scopri» and «Sistema» (header without the 56 px gap)
  - phone: «Comandi & MCP» title wrapped one word per line, description squeezed beside the search
  - Home widget «Prossimo allenamento»: the workout name was invisible (flex column squashed the truncated line)
  - Home widgets Alimentazione, Prossime date, Scadenze, Self care repeated their own title under the frame title
  - `<hxk-quicklog>` chips: label and hint ran together («…183940da fare oggi») — `.col` missing in its shadow styles
  - Self care: «1 passi» → «1 passo»
- [x] Fix PR #51 (visual fixes)
- [x] UI/UX analysis: 10 proposals for Marko in a Claude Doc «Hestia: test del frontend e proposte UI/UX», screenshots in the project files `revisione-ui/` (texts for the user instead of module names/prompt text, 44 px touch targets, phone page header, seasonal effect only on Home, phone agenda in list view, one «Sistema», empty widgets, one status line, plurals, outfit chip)
- [x] Marko approved all 10 proposals (2026-10-29 20:11) → SPEC v2.0

## v2.0
- [x] 1 user texts (hestia_common.areas, tool summaries, plugin/agenda titles, offline texts)
- [x] 2 touch 44 px (--tap) · [x] 3 phone header (--head-inset) · [x] 4 seasonal effect only on Home, fades out
- [x] 5 phone agenda list view · [x] 6 one «Stato del sistema» · [x] 7 empty widgets (markEmpty)
- [x] 8 one status line · [x] 9 plurals (SDK plural) · [x] 10 quick chip on one line, detail in ⋯
- [x] scrollbars (scrollbar-color/width, webkit fallback, SDK) 
- [x] colour themes (11 new, makeTheme)
- [x] styles Classico / Vetro / Netto + knobs (looks.ts, ThemeService, Impostazioni → Aspetto)
- [x] docs: DESIGN-SYSTEM, hestia-webui, hestia-shared, SDK README, ARCHITECTURE
- [ ] bench check (desktop/phone, light/dark, the 3 styles), PR, merge
