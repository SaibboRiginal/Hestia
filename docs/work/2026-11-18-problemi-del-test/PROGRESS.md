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
- [x] E1 — compatible models only (`llm_providers.list_models(name, use)`: Gemini methods, Ollama `/api/show`
      capabilities, else the name; `use` on `/api/ui/models/list` and `/api/llm/models`), learned limits
      (`llm_limits.py`: request limits read from the 429, counted per call, skip before the request, trusted one day,
      exhausted state + limits kept in Archive `oracle-store` kind `llm_quota`), one SDK chain editor `<hxk-chain>` used by
      Oracle «Modelli» and Echo «Motori» (chevrons, filtered picker, «available again at …»; mode/reasoning/chain name
      behind «Show the advanced settings»). Test `test_llm_limits.py`.
- [x] E2 — memory (embedding) chain with fallback models: Archive `embedding_model` on entities, user_preferences,
      document_records, document_chunks + `app/vectors.py` (one SQL `CASE`: each row against the query of its own
      model; untagged rows → the chain's first model); Oracle `ChainAgent.embed_tagged/embed_all/embed_with/primary_tag`,
      `_embed` returns a `TaggedVector`, `_query_vectors` for every search (RAG, retrieval, skills), `/api/embed` returns
      `model` (+ `all`); preference domains re-embedded with the model of the text; Athena clusters/dedups per model;
      setup «Memoria» takes several models (`embedding: {steps}`), Hephaestus pulls each Ollama one. Tests
      `test_embedding_chain.py`, Archive `test_vectors.py`. Context settings: already reduced by PR #118 (window read
      from the model); nothing else to remove.
- [ ] F — Deliveries, Development, Argus on `[🔄]`
- [ ] B — queue, steering, «/» commands
- [ ] G — mascot
