"""Memory similarity search ranks inside Postgres (docs/work/2026-11-06-ricerca-memorie-in-db).

Unit tests cover the guards that answer before any query; the live test needs ``ARCHIVE_TEST_PG_URL``
(a Postgres with pgvector, e.g. the cloud bench) and is skipped otherwise.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

_ARCHIVE_ROOT = Path(__file__).parents[1]
if str(_ARCHIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE_ROOT))

from app.routers.memory import search_similar_memories  # noqa: E402

URL = os.getenv("ARCHIVE_TEST_PG_URL", "")


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (768 - len(head))


@pytest.mark.unit
def test_missing_or_bad_embedding_is_400():
    for body in ({}, {"embedding": []}, {"embedding": "x"}, {"embedding": ["a"] * 768}):
        with pytest.raises(HTTPException) as exc:
            search_similar_memories(body, db=MagicMock())
        assert exc.value.status_code == 400


@pytest.mark.unit
def test_wrong_size_or_zero_vector_returns_nothing_without_query():
    db = MagicMock()
    assert search_similar_memories({"embedding": [0.1, 0.2, 0.3]}, db=db) == []
    assert search_similar_memories({"embedding": _vec()}, db=db) == []
    db.query.assert_not_called()


@pytest.mark.integration
@pytest.mark.skipif(not URL, reason="needs ARCHIVE_TEST_PG_URL")
def test_ranking_filters_and_similarity_on_postgres():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app import models, schema

    engine = create_engine(URL)
    schema.migrate(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.execute(text("DELETE FROM user_preferences WHERE fact LIKE 'simtest:%'"))
        rows = [
            ("simtest:same", _vec(1.0, 0.0), "skill", "calendar", True),
            ("simtest:near", _vec(1.0, 1.0), "skill", "general", True),
            ("simtest:far", _vec(0.0, 1.0), "skill", "calendar", True),
            ("simtest:off", _vec(1.0, 0.0), "skill", "calendar", False),
            ("simtest:other-class", _vec(1.0, 0.0), "durable_user_preference", "calendar", True),
            ("simtest:other-domain", _vec(1.0, 0.0), "skill", "spese", True),
            ("simtest:zero", _vec(), "skill", "calendar", True),
        ]
        for fact, emb, cls, dom, active in rows:
            db.add(models.UserPreference(fact=fact, embedding=emb, memory_class=cls, domain=dom, is_active=active))
        db.commit()

        out = search_similar_memories({"embedding": _vec(2.0, 0.0), "memory_class": "skill",
                                       "domain": "calendar", "limit": 5}, db=db)
        facts = [r["fact"] for r in out if r["fact"].startswith("simtest:")]
        assert facts == ["simtest:same", "simtest:near", "simtest:far"]
        sims = {r["fact"]: r["_similarity"] for r in out}
        assert sims["simtest:same"] == 1.0
        assert sims["simtest:near"] == pytest.approx(0.7071, abs=1e-4)
        assert sims["simtest:far"] == 0.0

        top = search_similar_memories({"embedding": _vec(1.0, 0.0), "memory_class": "skill",
                                       "domain": "calendar", "limit": 1}, db=db)
        assert [r["fact"] for r in top] == ["simtest:same"]
    finally:
        db.rollback()
        db.execute(text("DELETE FROM user_preferences WHERE fact LIKE 'simtest:%'"))
        db.commit()
        db.close()
        engine.dispose()
