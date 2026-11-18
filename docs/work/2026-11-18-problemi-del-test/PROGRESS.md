# PROGRESS — problems found in the real test

- [x] SPEC v1.0
- [x] A — stuck replies (bus, deadline, preemption, status, stop/new chat): Hub `X-Hestia-Deadline`, `llm_bus` Expired/Preempted,
      `ollama_post`, `_in_line` requeue, `widen_threadpool` (Oracle + Hub), status «Finishing a background job», WebUI
      status line + stop/clear free the box, «Not available right now». Tests `test_llm_bus.py`, `test_ollama_preempt.py`.
      Not done: preemption for llama-server / OpenAI-compatible local servers (they finish their call).
- [ ] C — language (`alt::`, English labels)
- [ ] D — WebUI one pattern
- [ ] E — chains, compatible models, Gemini limits, context settings
- [ ] F — Deliveries, Development, Argus on `[🔄]`
- [ ] B — queue, steering, «/» commands
- [ ] G — mascot
