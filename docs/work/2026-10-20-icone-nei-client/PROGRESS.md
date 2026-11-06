# Progress

- [x] Count emoji in WebUI and plugins (16 in WebUI, ~124 in 27 plugin files)
- [x] SPEC v1.0
- [x] Shared icon names: add missing icons to WebUI and SDK sets
- [x] WebUI app: emoji → icons (presence badge, chat, notices, quick strip, settings)
- [x] Presence states: `icon` + `tone` fields (Chronos built-ins), WebUI draws them
- [x] Hermes notices in WebUI: icon from level, leading emoji hidden
- [x] Plugins: Hygieia, Hercules, Wardrobe, Argus, Hephaestus, Scout, Plutus, Oracle, Hermes, SDK quicklog
- [x] Check script (no emoji in client code) + DESIGN-SYSTEM rule + module docs + root CHANGELOG
- [x] Builds: Angular app, every plugin bundle + tsc, SDK tsc; Chronos tests
- [x] PR, merge — on main (checked 2026-10-30, docs/work/2026-10-30-cose-aperte)
- [ ] Bench screenshots (WebUI + a plugin page)

## Notes
- One icon set (106 names) in `icon.component.ts` and SDK `kit/basics.ts`; `tone` input on both icons.
- Presence states: `icon` + `tone` next to `emoji`; WebUI popover draws the icon of the top overlay, else the base.
- Chat: `ChatMessage.icon` (paperclip, zap) and `error` (alert icon) instead of emoji in the text.
- Hermes texts keep emoji for Telegram; WebUI toasts and the Hermes inbox strip them and show the level icon.
- Favicon = `/icon.svg` (the ◈ logo).
