"""Generic module stores (finance-store, iris-store): LWW writes, seq cursor, tombstones — in-memory SQLite.

Postgres ``nextval`` is emulated with a SQLite function. SPEC docs/work/2026-10-19-email-push-spese §4.
"""
from __future__ import annotations

import sys
from itertools import count
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ARCHIVE_ROOT = Path(__file__).parents[1]
if str(_ARCHIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE_ROOT))
sys.modules.setdefault("pgvector", MagicMock())
sys.modules.setdefault("pgvector.sqlalchemy", MagicMock())

sqlalchemy = pytest.importorskip("sqlalchemy")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def client():
    from app import database, models
    from app.routers import module_store

    engine = sqlalchemy.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    seqs: dict = {}

    @event.listens_for(engine, "connect")
    def _nextval(conn, _rec):
        conn.create_function("nextval", 1, lambda name: next(seqs.setdefault(name, count(1))))

    models.Base.metadata.create_all(bind=engine, tables=[models.FinanceRecord.__table__, models.IrisRecord.__table__,
                                                               models.SignalRecord.__table__])
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(module_store.finance_router)
    app.include_router(module_store.iris_router)
    app.include_router(module_store.signals_router)
    app.dependency_overrides[database.get_db] = _db
    return TestClient(app)


def _row(id, ts, **data):
    return {"kind": "tx", "id": id, "updated_at": ts, "data": data}


@pytest.mark.api
def test_lww_cursor_and_tombstone(client):
    base = "/api/finance-store"
    r = client.put(f"{base}/records", json={"rows": [_row("a", "2026-10-19T10:00:00Z", amount=-5),
                                                     _row("b", "2026-10-19T10:00:00Z", amount=-7)]}).json()
    assert [a["seq"] for a in r["applied"]] == [1, 2] and r["cursor"] == 2
    old = client.put(f"{base}/records", json={"rows": [_row("a", "2026-10-19T09:00:00Z", amount=-1)]}).json()
    assert old["applied"] == [] and old["stale"][0]["data"]["amount"] == -5
    client.put(f"{base}/records", json={"rows": [{**_row("b", "2026-10-19T11:00:00Z"), "deleted": True}]})
    live = client.get(f"{base}/records").json()["rows"]
    assert [x["id"] for x in live] == ["a"]
    since = client.get(f"{base}/records", params={"since_seq": 2}).json()["rows"]
    assert since[0]["id"] == "b" and since[0]["deleted"]
    assert client.get(f"{base}/cursor").json() == {"cursor": 3}


@pytest.mark.api
def test_stores_are_separate(client):
    client.put("/api/iris-store/records", json={"rows": [{"kind": "subscription", "id": "plutus:paypal",
                                                          "updated_at": "2026-10-19T10:00:00Z", "data": {}}]})
    assert client.get("/api/finance-store/records").json()["rows"] == []
    assert client.get("/api/iris-store/records", params={"kind": "subscription"}).json()["rows"][0]["id"] == "plutus:paypal"


@pytest.mark.api
def test_signals_store_filters_by_module_and_domain(client):
    base = "/api/signals-store"
    rows = [{"kind": "signal", "id": "hercules:stall:panca", "ref_id": "hercules", "parent_id": "fitness",
             "updated_at": "2026-10-20T10:00:00Z", "data": {"text": "Panca ferma"}},
            {"kind": "metric", "id": "plutus:finance.spent:2026-W42", "ref_id": "plutus", "parent_id": "finance",
             "at": "2026-10-13T00:00:00Z", "updated_at": "2026-10-20T10:00:00Z", "data": {"value": 120}}]
    client.put(f"{base}/records", json={"rows": rows})
    assert [r["id"] for r in client.get(f"{base}/records", params={"ref_id": "hercules"}).json()["rows"]] == \
        ["hercules:stall:panca"]
    got = client.get(f"{base}/records", params={"kind": "metric", "at_from": "2026-10-01T00:00:00Z"}).json()["rows"]
    assert got[0]["data"]["value"] == 120
    assert client.get("/api/finance-store/records").json()["rows"] == []
