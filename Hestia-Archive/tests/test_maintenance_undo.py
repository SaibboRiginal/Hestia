"""Maintenance reconcile keeps what it deletes, and undo puts it back (in-memory SQLite).

Backs Hephaestus «Annulla riparazione» on Archive: docs/work/2026-10-30-cose-aperte.
"""
from __future__ import annotations

import sys
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
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def client(monkeypatch):
    from app import database, models
    from app.routers import entities

    # pgvector may be a MagicMock here: give the embedding column a type SQLite can select.
    monkeypatch.setattr(models.EntityRecord.__table__.c.embedding, "type", sqlalchemy.JSON())

    engine = sqlalchemy.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    table = models.EntityRecord.__table__
    # SQLite has neither pgvector nor GIN: a plain copy of the table without those two.
    meta = sqlalchemy.MetaData()
    sqlalchemy.Table(table.name, meta, *[
        sqlalchemy.Column(c.name, sqlalchemy.JSON if c.name in ("payload", "embedding") else c.type,
                          primary_key=c.primary_key, unique=c.unique, nullable=c.nullable)
        for c in table.columns])
    meta.create_all(bind=engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(entities.router)
    app.dependency_overrides[database.get_db] = _db
    c = TestClient(app)
    c.session = session
    return c


def _seed(client, rows):
    from datetime import datetime, timezone

    from app import models
    db = client.session()
    for eid, payload in rows:
        db.add(models.EntityRecord(entity_id=eid, domain="case", status="active", payload=payload,
                                   created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    db.commit()
    db.close()


def _ids(client):
    from app import models
    db = client.session()
    try:
        return sorted(r.entity_id for r in db.query(models.EntityRecord).filter(
            models.EntityRecord.domain == "case").all())
    finally:
        db.close()


def _reconcile(client, task_id="t1"):
    return client.post("/api/module/maintenance/reconcile", json={
        "task_id": task_id, "dry_run": False, "domain": "case", "required_fields": ["title"]}).json()


@pytest.mark.api
def test_reconcile_then_undo_restores_deleted_rows(client):
    _seed(client, [("a", {"title": "Casa A"}), ("b", {"price": 1}), ("c", {"title": ""})])
    out = _reconcile(client)
    assert out["mutation_count"] == 2 and out["details"]["undo_available"] is True
    assert _ids(client) == ["a"]

    undo = client.post("/api/module/maintenance/undo", json={"task_id": "t1"}).json()
    assert undo["details"]["restored"] == 2
    assert _ids(client) == ["a", "b", "c"]
    # the trash is consumed: a second undo has nothing left
    assert client.post("/api/module/maintenance/undo", json={"task_id": "t1"}).status_code == 404


@pytest.mark.api
def test_undo_keeps_rows_recreated_meanwhile(client):
    _seed(client, [("a", {"title": "Casa A"}), ("b", {"price": 1})])
    _reconcile(client)
    _seed(client, [("b", {"title": "Casa B nuova"})])
    undo = client.post("/api/module/maintenance/undo", json={"task_id": "t1"}).json()
    assert undo["details"] == {"restored": 0, "skipped_ids": ["b"]}


@pytest.mark.api
def test_nothing_deleted_means_nothing_to_undo(client):
    _seed(client, [("a", {"title": "Casa A"})])
    out = _reconcile(client)
    assert out["mutation_count"] == 0 and out["details"]["undo_available"] is False
    assert client.post("/api/module/maintenance/undo", json={"task_id": "t1"}).status_code == 404


@pytest.mark.api
def test_cleanup_never_scans_the_trash(client):
    _seed(client, [("b", {"price": 1})])
    _reconcile(client)
    # a later reconcile over every domain must not delete the trash entity itself
    client.post("/api/module/maintenance/reconcile", json={
        "task_id": "t2", "dry_run": False, "required_fields": ["title"]})
    assert client.post("/api/module/maintenance/undo", json={"task_id": "t1"}).json()["details"]["restored"] == 1
