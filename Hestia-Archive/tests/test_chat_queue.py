"""Chat queue store (docs/work/2026-10-19-oracle-offline §3) on an in-memory SQLite."""
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
def client():
    from app import database, models
    from app.routers import chat_queue

    engine = sqlalchemy.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(bind=engine, tables=[models.ChatQueueItem.__table__])
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(chat_queue.router)
    app.dependency_overrides[database.get_db] = _db
    return TestClient(app)


BASE = "/api/chat-queue"


@pytest.mark.api
def test_enqueue_position_and_oldest_first(client):
    a = client.post(BASE, json={"client": "telegram", "session_id": "s1", "text": "ciao", "client_ref": "11"}).json()
    b = client.post(BASE, json={"client": "telegram", "session_id": "s1", "text": "ci sei?"}).json()
    client.post(BASE, json={"client": "webui", "session_id": "w1", "text": "altro"})
    assert (a["position"], b["position"]) == (1, 2)
    items = client.get(BASE, params={"client": "telegram"}).json()["items"]
    assert [i["text"] for i in items] == ["ciao", "ci sei?"]
    assert client.get(f"{BASE}/counts").json() == {"waiting": {"telegram": 2, "webui": 1}, "total": 3}


@pytest.mark.api
def test_claim_is_compare_and_set(client):
    item = client.post(BASE, json={"client": "telegram", "session_id": "s1", "text": "x"}).json()
    first = client.post(f"{BASE}/{item['id']}/claim")
    assert first.status_code == 200 and first.json()["state"] == "answering"
    assert client.post(f"{BASE}/{item['id']}/claim").status_code == 409
    done = client.post(f"{BASE}/{item['id']}/done", json={"ok": True}).json()
    assert done["state"] == "answered" and done["answered_at"]
    assert client.post(f"{BASE}/{item['id']}/claim").status_code == 409
    assert client.get(f"{BASE}/counts").json()["total"] == 0


@pytest.mark.api
def test_failed_answer_goes_back_to_queue_then_failed(client):
    item = client.post(BASE, json={"client": "webui", "session_id": "w", "text": "x"}).json()
    for _ in range(5):
        client.post(f"{BASE}/{item['id']}/claim")
        out = client.post(f"{BASE}/{item['id']}/done", json={"ok": False, "detail": "oracle down"}).json()
    assert out["state"] == "failed" and out["attempts"] == 5


@pytest.mark.api
def test_stale_claim_can_be_taken_again(client):
    item = client.post(BASE, json={"client": "webui", "session_id": "w", "text": "x"}).json()
    client.post(f"{BASE}/{item['id']}/claim")
    assert client.post(f"{BASE}/{item['id']}/claim", params={"stale_seconds": 600}).status_code == 409
    from app import database  # noqa: F401  (session override in fixture)
    # A claim older than stale_seconds is reclaimable: simulate with a negative age window.
    import datetime as _dt
    from app import models
    db = next(client.app.dependency_overrides[database.get_db]())
    row = db.query(models.ChatQueueItem).first()
    row.answered_at = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
    db.commit()
    again = client.post(f"{BASE}/{item['id']}/claim", params={"stale_seconds": 600})
    assert again.status_code == 200 and again.json()["attempts"] == 2
