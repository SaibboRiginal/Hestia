---
name: hestia-ui
description: Use for Hestia WebUI or module plugin UI work (Angular frontend, Lit plugins, icons, texts).
---

- Read `Hestia-WebUI/frontend/DESIGN-SYSTEM.md` first.
- Stroke icons with a tone colour (`<hx-icon>` / `<hxk-icon>`, set in `icon.component.ts`, checked by
  `tools/governance/check_icons.py`); never emoji in web clients.
- User texts never name modules or internal parts («Non disponibile», never «Oracle è giù»); no cute names.
- Pages and widgets of a module are its own WebUI plugin (`Hestia-<Name>/ui/`), not new built-in pages.
