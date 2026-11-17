# PROGRESS — LLM bus

- [x] Read the call path (ChainAgent, endpoints, agent loop, providers)
- [x] SPEC v1.0
- [x] `core/services/llm_bus.py` (queue, priority, workers, re-entrancy, promotion)
- [x] ChainAgent: worker around local steps (`_call`, attachments, streams), embeddings skip
- [x] Endpoints: `/api/chat`, `/api/chat/document`, `/api/llm/generate`; agent loop `owner_waiting` + context copy
- [x] Setting `oracle.bus.local_workers`
- [x] Tests `Hestia-Oracle/tests/test_llm_bus.py`; Oracle unit/api/format suite green (754)
- [x] Docs: hestia-oracle.md, ARCHITECTURE.md 3b, AI-GUIDE.md §3, root CHANGELOG
- [x] precheck, PR
- [ ] CI green and merged
- [ ] Message the multi-agent thread (merge `agenti`/`agenti_in_serie`, bacheca del turno)
