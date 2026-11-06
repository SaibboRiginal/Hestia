# SPEC — Ricerca memorie dentro il database

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Valutare LEANN per Hestia», 2026-11-06: «voglio le migliori performance e risparmio di token») |
| **Status** | Done |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code)
- Archive stores vectors in Postgres + pgvector, `Vector(768)` (Ollama embeddings): `user_preferences`, `entities`,
  `document_records`, `document_chunks`.
- Documents (`POST /api/documents/search`) and entities (`POST /api/entities/search`) already rank inside Postgres
  (`l2_distance`).
- Memories (`POST /api/memory/search/similar`, used by Oracle skill discovery and Athena's skill curator) loaded
  **every** active candidate with its 768 floats into Python and computed cosine one row at a time. A vector of a
  different size was compared truncated (`zip`) instead of refused.

## 2. Goal
Same answers, faster and with constant cost: Postgres ranks and only the top rows leave the DB.

## 3. Scope and design
- Memory search uses pgvector `cosine_distance` (`<=>`) with `ORDER BY … LIMIT`; `_similarity = 1 - distance`
  (same value and response shape as before, callers unchanged).
- Guards before any query: non-numeric embedding → 400; size ≠ column size → `[]` with
  `[🔄] event=memory_search_dim_mismatch`; zero vector → `[]`. Stored zero vectors (NaN distance) are skipped.
- **Not done, on purpose:**
  - LEANN (evaluated in the same thread). It saves disk only at millions of chunks, it recomputes embeddings on the
    GPU at every search, it would be a second store outside Archive and outside the Drive backup, and it does not
    support Raspberry/ARM.
  - An HNSW index. At Hestia's size (thousands of rows) exact search is already a few ms. With the filters Hestia
    uses (domain, class, session), an approximate index can drop matches unless pgvector ≥ 0.8 iterative scans are
    enabled, and the `ankane/pgvector` image is not pinned.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: the assistant finds the right skills faster and with less CPU.
2. Owner module (R1): Archive (only DB owner).
3. Configuration: none.
4. Push or poll: n/a (request/response).
5. Who confirms: n/a, no behaviour change for the owner.
6. WebUI / Telegram: no change.
7. Stop, correct, undo: n/a.
8. Docs that change: `Hestia-Archive/hestia-archive.md`, `Hestia-Swagger/swagger.yml`.

## 5. Acceptance criteria
1. Same ranking and `_similarity` values as the Python loop, with the class and domain filters and `limit` (live
   test on Postgres: `tests/test_memory_similar.py`).
2. Bad, wrong-size or zero embeddings answer before any query.
3. Archive unit suite green.
