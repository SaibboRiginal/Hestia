# PROGRESS — chat modalità / ragionamento / contesto

Spec: `SPEC.md` v1.0 · resume from the first unchecked box.

- [x] Analysis (what existed, what was lost/missing)
- [x] SPEC written
- [x] Oracle: `oracle.chat.mode` + resolution in `/api/chat`, engine modes thinking/cot
- [x] Oracle: llm_stats per session + Gemini/Anthropic/Claude CLI, `/api/chat/context` active + session_usage
- [x] Telegram: Modalità in /settings
- [x] WebUI backend: ChatHub modes, thinking display values/default, context/compact endpoints
- [x] WebUI frontend: composer mode picker, thinking display in chat popover + live/detailed, context gauge
- [x] Docs: hestia-oracle.md, hestia-webui.md, hestia-telegram.md, swagger, root CHANGELOG
- [x] Verified here: py_compile, `ng build`, Playwright screenshots with mocked API; tests added `Hestia-Oracle/tests/test_chat_modes_usage.py` (not run, user rule)
- [ ] User test on the real stack (.NET build + run) — .NET build + Angular build verified 2026-10-18 (docs/work/2026-10-18-coerenza-moduli), real run left
