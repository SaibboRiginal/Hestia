# PROGRESS — problems found in the real test

- [x] SPEC v1.0
- [x] A — stuck replies (bus, deadline, preemption, status, stop/new chat): Hub `X-Hestia-Deadline`, `llm_bus` Expired/Preempted,
      `ollama_post`, `_in_line` requeue, `widen_threadpool` (Oracle + Hub), status «Finishing a background job», WebUI
      status line + stop/clear free the box, «Not available right now». Tests `test_llm_bus.py`, `test_ollama_preempt.py`.
      Not done: preemption for llama-server / OpenAI-compatible local servers (they finish their call).
- [x] C — language: `localize` walks lists/objects under KEEP_KEYS except `DATA_KEYS` (TS + Python), plugin `host.api`
      answers and site notification pushes localized, download notice title `tr`. Test in Themis `test_themis_personal.py`.
- [x] D — WebUI one pattern: `ui/tooltip.ts` (global, plugins via composedPath), pinned block, solid collapse/burger,
      breadcrumb links, composer (no hint line, Talk in the box, dictation at the cursor), `hxk-stat` `list`/`open`
      applied to Iris (subscribed modules, emails seen), Hub map (services/online/offline), Argus (unhealthy, incidents).
      Other count tiles: to apply when their page is touched (rule in DESIGN-SYSTEM §5).
- [ ] E — chains, compatible models, Gemini limits, context settings
- [ ] F — Deliveries, Development, Argus on `[🔄]`
- [ ] B — queue, steering, «/» commands
- [ ] G — mascot
