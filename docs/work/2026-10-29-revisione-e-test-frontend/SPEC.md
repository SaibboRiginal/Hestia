# SPEC — Revisione completa e test del frontend

| | |
|---|---|
| **Version** | 2.1 |
| **Source** | user via external chat (Marko, 2026-10-29: «review completa di tutto … test sul frontend … analisi ui/ux»; 20:11 «vanno tutte bene … scrollbar e usabilità … altri temi colorati … bordi, animazioni, blur/opacità/trasparenze … altre 2 stilizzazioni») |
| **Status** | In progress |

## 1. Today (verified in code)
Everything of brainstorm + Cindy (8 waves, PR #34–#48) and the README (PR #46) is on main; no open PRs.

## 2. Goal
1. Review the whole of main: bugs, coherence between modules, module boundaries (Oracle only brain, Hermes only
   outbound messenger, Archive only DB, Hub only door), no personal data in tracked files, no feature on/off
   switches, no emoji in web clients. Fix real bugs (one PR, merged when CI is green).
2. Run the stack on the cloud bench (`python tools/cloud_test.py all`, fake LLM) and test the WebUI on desktop and
   phone sizes, light and dark: responsive layout, console and network errors.
3. UI/UX usability analysis with concrete proposals for Marko to choose (not implemented unasked).

## 3. Scope and design
- Fixes only for real defects; proposals go to a report in the project files, not into code.
- Static checks: governance scripts, pyflakes on every service, `tsc --noEmit` on every plugin bundle.
- Frontend check: Playwright on the bench WebUI, every page at 1440×900 and 390×844, light and dark, collecting
  console errors, failed requests and horizontal overflow.

## 4. New feature checklist
Not a feature: review and fixes only.

## 5. Acceptance criteria
- Review findings listed in PROGRESS.md with what was fixed and what was left.
- Fix PR green and merged; docs updated with every behaviour change.
- Frontend report with screenshots and the list of errors found (and fixed when they are bugs).
- UI/UX proposals delivered to Marko.

## 6. v2.0 — implement the proposals, themes and styles (Marko 2026-10-29 20:11)

All ten proposals of the UI/UX analysis are approved:
1. user-facing texts: tools get a short summary for people and are grouped by area, never by module name; agenda
   items and errors are written for people (no «Hecate: …», no «Connection refused»);
2. touch targets ≥ 44 px on touch screens (`pointer: coarse`), desktop stays compact;
3. phone page header: menu button on the title line in plugin pages, subtitle hidden on phone;
4. seasonal effect only on Home, stops after a few seconds, never with reduced motion;
5. phone agenda: list view by default (v2.1: the agenda *is* the assistant's, so nothing to hide there; its job titles
   are now written for people);
6. one «Sistema» entry;
7. empty widgets take less room;
8. one status line at the bottom of the sidebar;
9. plurals through one helper;
10. outfit suggestion chip on one line.

Plus:
- **Scrollbars and basics**: thin themed scrollbars everywhere, also inside plugin shadow roots and in Firefox;
  no double scrollbars; focus visible; check on the bench.
- **Colour themes**: more coloured themes, light and dark, same token set (`themes.ts`).
- **Styles** (second axis, independent of the colour theme): «Classico» (today, Claude-like) + two new ones,
  «Vetro» (translucent surfaces with blur, soft borders, rounder) and «Netto» (sharp corners, crisp borders, no
  shadows, sans everywhere; v2.1: no density knob, spacing stays the same). Each style sets defaults for four knobs the user can change one by one:
  corners, borders, animations, transparency/blur. Saved per device like the theme (localStorage); applied as
  tokens on `<html>` so plugins (shadow DOM) follow.

### Design decisions (v2.1)
- Themes from 4 seeds (`makeTheme`: bg, surface, text, accent), same derivation steps as the Claude pair; semantic
  colours shared, so success/warning/danger read the same in every theme. 11 new: Oceano/Oceano notte,
  Foresta/Bosco, Lavanda/Ametista, Cipria/Vino, Sabbia/Brace, Mezzanotte. `pair` keeps the family on light↔dark.
- Style knobs: corners squadrati/normali/arrotondati; borders leggeri/normali/marcati; transparency nessuna/leggera/
  vetro; animations nessuna/ridotte/normali/vivaci. Style = preset; a changed knob is stored as an override
  (`hestia_look`), «Torna allo stile» clears them.
- Blur only on floating panels (sidebar, dialogs, popovers, menus, drawer, composer, palette, chat history): cards
  are translucent over a smooth shaded backdrop, where blur would change nothing and costs GPU.
- Blur on `::before` (`hx-glass`) for panels that hold `position: fixed` popovers: `backdrop-filter` on the panel
  itself would make it their containing block.
- Status line: the assistant's state is the line; the connection replaces it (pulsing) only when not connected,
  and is listed inside the state popover.
