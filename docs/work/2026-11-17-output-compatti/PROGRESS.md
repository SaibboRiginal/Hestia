# PROGRESS — Shaped outputs for small context windows

- [x] SPEC v1.0 (ideas 1, 2, 4 of `valutazioni/trucchi-risparmio-token.md`, approved by the owner 2026-11-17)
- [x] `hestia_common.compact_output` (JSON + text shaping)
- [x] Oracle agent loop: `tool_result_budget` (setting default 0 = automatic), `_shape_tool_result`, `result_more`, stubs point to it
- [x] Forge `t_run_tests` / `t_search` shaped
- [x] Compact JSON in `ContextBuilder` and `format_payload`
- [x] Idea 4 (agent answer contract) handed to the module-agents thread
- [x] Tests: `Hestia-Oracle/tests/test_compact_output.py`, `test_agent_loop.py`, `test_oracle_settings.py`, `Hestia-Hephaestus/tests/test_forge_context_fit.py`
- [x] Docs: hestia-shared.md, hestia-oracle.md, hestia-hephaestus.md, root CHANGELOG
- [ ] Owner's real run with the local model
