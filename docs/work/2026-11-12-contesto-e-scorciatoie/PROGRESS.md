# PROGRESS

- [x] Oracle: `local_window.py`, setting default 0 = automatic, options without `num_ctx`, floor 8192 without ping-pong
- [x] Oracle: window of the answering model in the agent loop; Forge use-case status and usage rows from the same source
- [x] Oracle: prompt breakdown + usage per model in `/api/chat/context`
- [x] Tests: `test_local_window.py` (19), `test_local_context.py` updated; Oracle unit/api/format suite green (735)
- [x] WebUI: `<hx-setting-link>`, deep link `?key=` / `?section=&row=` with highlight
- [x] WebUI: context popover (bar, legend, source, warning, per model)
- [x] WebUI: shortcuts in chat mode, chat quick settings; gear on module pages; SDK `openSetting`
- [x] WebUI: palette finds settings
- [x] Angular build; browser check with mocked API (Playwright): settings highlight, popover desktop/phone, over
      window, palette, popover → setting
- [x] Docs: module docs, DESIGN-SYSTEM, SDK README, swagger, ARCHITECTURE, TESTING, root CHANGELOG

Not verified here: a real Ollama (the `/api/ps` read and the reload behaviour are covered by mocked tests only);
the gear on a real module page (the mocked check had no module bundle); the .NET build (no backend change).
Left in the thread's plan (next PR): sidebar, notifications bell, chat delete, voice bubble, dividers, Ascolta errors.
