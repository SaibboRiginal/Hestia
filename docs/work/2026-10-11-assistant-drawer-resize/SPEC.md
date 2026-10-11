# Pannelli ridimensionabili nella WebUI

| Version | Source | Status |
|---|---|---|
| 2.0 | user via external chat (Claude project thread) | done |

## Goal
Side panels of the WebUI can be resized (the owner likes resizable panels in general), starting from the
"Crea con Hestia" drawer and the main sidebar. The theme toggle leaves the sidebar (themes stay in Impostazioni).

## Scope / design
- Kit widget `<hx-resize>` (`src/app/ui/resize.ts`): drag handle on a panel edge, pointer events with capture,
  ←/→ on the focused handle (Shift = bigger step), double-click = default width, clamped to [min, max] and 90vw,
  re-clamped on window resize, width per browser in `localStorage` `hestia_w_<key>` (rendering preference, not a
  Themis setting). `inline` mode for scrolling panels (handle is a zero-width flex item next to the panel).
  Hidden on phones (≤860px).
- Applied to: shell sidebar (200–420, default 248; not when collapsed), Crea con Hestia (340+, default 440),
  Sviluppo task list (220–520, 300) and context panel (320–1000, default 34% of the window),
  Calendario filters column (200–460, 256; hidden ≤1100 where it becomes a drawer),
  Impostazioni → Sistema module column (180–420, 230).
- Shell: "Tema chiaro/scuro" button removed (theme choice is in Impostazioni).

## Acceptance
- Each listed panel resizes by dragging its edge; width survives reload; phones unchanged.
- No theme toggle in the sidebar.
- `ng build` green, no warnings.
