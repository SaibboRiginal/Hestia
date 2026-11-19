"""One memory, several embedding models (docs/work/2026-11-18-real-test-problems E2): each row is compared with the
query embedded by its own model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from types import SimpleNamespace

from sqlalchemy import column, literal

_ARCHIVE_ROOT = Path(__file__).parents[1]
if str(_ARCHIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE_ROOT))

from app import vectors  # noqa: E402


class _Embedding:
    """Stand-in for a pgvector column (other test files replace pgvector with a mock)."""
    type = SimpleNamespace(dim=768)

    def l2_distance(self, v):
        return literal(1.0) * len(v)

    def cosine_distance(self, v):
        return literal(2.0) * len(v)


EMB, MODEL = _Embedding(), column("embedding_model")


def _vec(x: float) -> list[float]:
    return [x] * 768


def _sql(expr) -> str:
    return str(expr.compile())


@pytest.mark.unit
def test_each_model_gets_its_own_query_vector_and_untagged_rows_the_first():
    expr = vectors.distance(EMB, MODEL,
                            query_vectors=[{"model": "ollama/a", "vector": _vec(0.1)},
                                           {"model": "gemini/b", "vector": _vec(0.2)}],
                            untagged_model="ollama/a")
    sql = _sql(expr)
    assert sql.startswith("CASE WHEN") and sql.count("WHEN") == 3 and "IS NULL" in sql and "ELSE" not in sql


@pytest.mark.unit
def test_untagged_rows_left_out_when_the_first_model_is_not_reached():
    expr = vectors.distance(EMB, MODEL,
                            query_vectors=[{"model": "gemini/b", "vector": _vec(0.2)}], untagged_model="ollama/a")
    assert "IS NULL" not in _sql(expr)


@pytest.mark.unit
def test_wrong_size_or_zero_vectors_are_skipped():
    assert vectors.pairs([{"model": "x", "vector": [1.0, 2.0]}, {"model": "y", "vector": _vec(0.0)}],
                         EMB) == []
    assert vectors.distance(EMB, MODEL,
                            query_vector=[0.5, 0.5]) is None


@pytest.mark.unit
def test_single_vector_keeps_the_old_behaviour():
    expr = vectors.distance(EMB, MODEL,
                            query_vector=_vec(0.3), measure="cosine")
    assert expr is not None and "CASE" not in _sql(expr)


@pytest.mark.unit
def test_tag_only_with_a_vector():
    assert vectors.tag(_vec(0.1), "ollama/a") == "ollama/a"
    assert vectors.tag(None, "ollama/a") is None and vectors.tag(_vec(0.1), "") is None
