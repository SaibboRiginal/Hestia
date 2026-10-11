# Drawer "Crea con Hestia" ridimensionabile

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (Claude project thread) | done |

## Goal
The "Crea con Hestia" side drawer (WebUI) can be resized instead of being fixed at 440px.

## Scope / design
- Handle on the drawer's left edge (`role="separator"`, cursor ew-resize, accent line on hover/drag).
- Drag with pointer events (pointer capture, works with touch pen/mouse); ←/→ on the focused handle (Shift = bigger step);
  double-click = default width (440px).
- Width clamped to [340px, 90% of the viewport], re-clamped on window resize.
- Width kept per browser in `localStorage` (`hestia_assistant_width`): pure rendering preference, not a Themis setting.
- Phones (≤720px): drawer stays full screen, handle hidden.

## Acceptance
- Dragging the left edge changes the width live; the width survives closing/reopening and page reload.
- `ng build` green.
