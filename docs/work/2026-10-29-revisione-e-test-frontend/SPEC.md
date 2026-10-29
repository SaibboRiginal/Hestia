# SPEC — Revisione completa e test del frontend

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (Marko, 2026-10-29: «review completa di tutto … test sul frontend … analisi ui/ux») |
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
