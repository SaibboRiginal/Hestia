"""Conversation list, tags, pinned (Cindy 26, dossier 2026-10-24-tutto-brainstorm-cindy W7) on in-memory SQLite."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
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
def ctx():
    from app import database, models
    from app.routers import chat

    engine = sqlalchemy.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(bind=engine, tables=[models.ChatHistory.__table__, models.ChatSessionMeta.__table__])
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(chat.router)
    app.dependency_overrides[database.get_db] = _db
    db = session()
    t0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    for sid, day, msgs in [("a", 0, ["parliamo della palestra", "ok"]), ("b", 3, ["spese di ottobre", "fatto"]),
                           ("c", 5, ["ciao", "ciao!"])]:
        for i, text in enumerate(msgs):
            db.add(models.ChatHistory(session_id=sid, role="user" if i % 2 == 0 else "assistant", content=text,
                                      timestamp=t0 + timedelta(days=day, minutes=i)))
    db.commit()
    db.close()
    return TestClient(app)


@pytest.mark.api
def test_list_newest_first_with_first_message_as_title(ctx):
    out = ctx.get("/api/chat/sessions/list").json()
    assert [i["session_id"] for i in out["items"]] == ["c", "b", "a"]
    assert out["items"][2]["title"] == "parliamo della palestra"
    assert out["items"][0]["messages"] == 2 and out["total"] == 3


@pytest.mark.api
def test_search_dates_tags_and_pinned_first(ctx):
    assert [i["session_id"] for i in ctx.get("/api/chat/sessions/list", params={"q": "ottobre"}).json()["items"]] == ["b"]
    got = ctx.get("/api/chat/sessions/list", params={"since": "2026-10-22T00:00:00+00:00", "until": "2026-10-24T00:00:00+00:00"}).json()
    assert [i["session_id"] for i in got["items"]] == ["b"]

    r = ctx.put("/api/chat/sessions/a/meta", json={"add_tags": [{"name": "Salute", "color": "green"}, "lavoro"], "pinned": True}).json()
    assert r["before"]["tags"] == [] and [t["name"] for t in r["tags"]] == ["salute", "lavoro"]
    assert r["tags"][0]["color"] == "green"
    items = ctx.get("/api/chat/sessions/list").json()["items"]
    assert items[0]["session_id"] == "a" and items[0]["pinned"]
    assert [i["session_id"] for i in ctx.get("/api/chat/sessions/list", params={"tag": "salute"}).json()["items"]] == ["a"]

    ctx.put("/api/chat/sessions/a/meta", json={"remove_tags": ["lavoro"], "title": "Allenamento"})
    tags = ctx.get("/api/chat/sessions/tags").json()["items"]
    assert tags == [{"name": "salute", "color": "green", "count": 1}]
    assert [i["session_id"] for i in ctx.get("/api/chat/sessions/list", params={"q": "allenam"}).json()["items"]] == ["a"]


@pytest.mark.api
def test_delete_conversation_drops_messages_and_meta(ctx):
    ctx.put("/api/chat/sessions/a/meta", json={"title": "Palestra", "pinned": True})
    out = ctx.delete("/api/chat/sessions/a").json()
    assert out["deleted_messages"] == 2
    ids = [i["session_id"] for i in ctx.get("/api/chat/sessions/list").json()["items"]]
    assert "a" not in ids and len(ids) == 2
    assert ctx.get("/api/chat/sessions/a/meta").json()["pinned"] is False


@pytest.mark.api
def test_clearing_history_keeps_title_and_pin(ctx):
    """Compaction clears the messages and writes them again: what the owner set must stay."""
    ctx.put("/api/chat/sessions/b/meta", json={"title": "Spese", "pinned": True})
    ctx.delete("/api/chat/history/b")
    assert ctx.get("/api/chat/sessions/b/meta").json()["title"] == "Spese"


@pytest.mark.api
def test_a_message_written_again_keeps_its_time(ctx):
    sent = ctx.post("/api/chat/history", json={"session_id": "z", "role": "user", "content": "di ieri",
                                               "timestamp": "2026-10-01T08:30:00+00:00"}).json()
    assert sent["timestamp"].startswith("2026-10-01T08:30")
    now = ctx.post("/api/chat/history", json={"session_id": "z", "role": "user", "content": "di adesso"}).json()
    assert now["timestamp"] and not now["timestamp"].startswith("2026-10-01")
