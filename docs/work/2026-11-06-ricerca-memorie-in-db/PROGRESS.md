# PROGRESS — Ricerca memorie dentro il database

- [x] Evaluate LEANN against Hestia's memory/RAG (thread answer: not adopted, see SPEC §3)
- [x] SPEC v1.0
- [x] `POST /api/memory/search/similar` ranks in Postgres (`cosine_distance`, `ORDER BY … LIMIT`)
- [x] Guards: non-numeric → 400, wrong size / zero vector → `[]`, stored zero vectors skipped
- [x] Tests `Hestia-Archive/tests/test_memory_similar.py` (2 unit + 1 live on pgvector, passed locally against `ankane/pgvector`)
- [x] Docs: hestia-archive.md, swagger.yml, root CHANGELOG
