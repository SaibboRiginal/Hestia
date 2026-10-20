"""LLM usage store — rows written by Oracle and summed (docs/work/2026-10-19-oracle-a-blocchi §E).

Runs the real router on an in-memory SQLite: only the llm_usage table is created.
"""
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
def client():
    from app import database, models
    from app.routers import llm_usage_store

    engine = sqlalchemy.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(bind=engine, tables=[models.LLMUsage.__table__])
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(llm_usage_store.router)
    app.dependency_overrides[database.get_db] = _db
    return TestClient(app)


BASE = "/api/llm-usage-store"


def _row(**kw) -> dict:
    row = {"at": datetime.now(timezone.utc).isoformat(), "module": "oracle", "use_case": "oracle.generale",
           "chain": "veloce", "step": 0, "provider": "ollama", "model": "gemma4:e4b", "session_id": "s1",
           "client": "telegram", "input_tokens": 100, "cached_tokens": 40, "output_tokens": 20, "duration_ms": 500,
           "outcome": "ok"}
    row.update(kw)
    return row


@pytest.mark.api
class TestUsageStore:
    def test_write_and_group_by_module(self, client):
        rows = [_row(), _row(step=1, provider="gemini", model="flash", cost_usd=0.01, duration_ms=1500),
                _row(module="scout", use_case="scout.annunci", session_id=None, outcome="quota")]
        assert client.post(f"{BASE}/rows", json={"rows": rows}).json()["written"] == 3
        out = {r["module"]: r for r in client.get(f"{BASE}/summary", params={"group": "module"}).json()["rows"]}
        assert out["oracle"]["calls"] == 2 and out["oracle"]["fallbacks"] == 1
        assert out["oracle"]["input_tokens"] == 200 and out["oracle"]["cost_usd"] == 0.01
        assert out["oracle"]["avg_duration_ms"] == 1000
        assert out["scout"]["quota"] == 1 and out["scout"]["errors"] == 1

    def test_group_by_session_day_and_rows_detail(self, client):
        client.post(f"{BASE}/rows", json={"rows": [_row(), _row(session_id="s2")]})
        sessions = client.get(f"{BASE}/summary", params={"group": "session"}).json()["rows"]
        assert {r["session_id"] for r in sessions} == {"s1", "s2"}
        days = client.get(f"{BASE}/summary", params={"group": "day"}).json()["rows"]
        assert len(days) == 1 and days[0]["calls"] == 2
        detail = client.get(f"{BASE}/rows", params={"session_id": "s2"}).json()["rows"]
        assert len(detail) == 1 and detail[0]["model"] == "gemma4:e4b"

    def test_retention_removes_old_rows_on_write(self, client):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        client.post(f"{BASE}/rows", json={"rows": [_row(at=old)], "retention_days": 90})
        out = client.post(f"{BASE}/rows", json={"rows": [_row()], "retention_days": 30}).json()
        assert out["removed"] == 1
        assert client.get(f"{BASE}/summary", params={"days": 365}).json()["rows"][0]["calls"] == 1

    def test_bad_group(self, client):
        assert client.get(f"{BASE}/summary", params={"group": "nope"}).status_code == 400
