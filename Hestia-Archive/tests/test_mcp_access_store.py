"""MCP access store — tokens and OAuth (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B6).

Runs the real router on an in-memory SQLite (JSONB rendered as JSON): only the mcp_* tables are created.
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
    from app.routers import mcp_access_store

    engine = sqlalchemy.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [models.MCPAccess.__table__, models.MCPOAuthClient.__table__, models.MCPOAuthCode.__table__]
    models.Base.metadata.create_all(bind=engine, tables=tables)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(mcp_access_store.router)
    app.dependency_overrides[database.get_db] = _db
    return TestClient(app)


BASE = "/api/mcp-access-store"


def _later(**kw) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


@pytest.mark.api
class TestTokens:
    def test_create_lookup_by_hash_and_no_hash_in_answers(self, client):
        out = client.post(f"{BASE}/accesses", json={"access_id": "a1b2c3", "name": "Claude Code PC",
                                                    "token_hash": "h" * 64}).json()
        assert out["kind"] == "token" and "token_hash" not in out
        assert client.get(f"{BASE}/accesses/by-hash/{'h' * 64}").json()["access_id"] == "a1b2c3"
        assert client.get(f"{BASE}/accesses/by-hash/nope").status_code == 404
        assert "h" * 64 not in client.get(f"{BASE}/accesses").text

    def test_revoke_and_used_counter(self, client):
        client.post(f"{BASE}/accesses", json={"access_id": "a1b2c3", "name": "x", "token_hash": "t1"})
        assert client.patch(f"{BASE}/accesses/a1b2c3", json={"revoked": True}).json()["revoked_at"]
        assert client.post(f"{BASE}/accesses/a1b2c3/used").json()["calls_today"] == 1


@pytest.mark.api
class TestOAuth:
    def test_oauth_access_rotation_and_replay(self, client):
        out = client.post(f"{BASE}/accesses", json={
            "access_id": "o1o1o1", "name": "claude.ai", "kind": "oauth", "scope": "read", "client_id": "hmc_client1",
            "token_hash": "a1", "refresh_hash": "r1", "token_expires_at": _later(hours=1)}).json()
        assert out["kind"] == "oauth" and out["client_id"] == "hmc_client1" and out["token_expires_at"]
        assert "r1" not in str(out)
        found = client.get(f"{BASE}/accesses/by-refresh/r1").json()
        assert found["access_id"] == "o1o1o1" and found["reused"] is False
        body = {"old_refresh_hash": "r1", "token_hash": "a2", "refresh_hash": "r2", "token_expires_at": _later(hours=1)}
        assert client.post(f"{BASE}/accesses/o1o1o1/rotate", json=body).status_code == 200
        assert client.post(f"{BASE}/accesses/o1o1o1/rotate", json=body).status_code == 409   # r1 no longer current
        assert client.get(f"{BASE}/accesses/by-refresh/r1").json()["reused"] is True        # replay is visible
        assert client.get(f"{BASE}/accesses/by-refresh/r2").json()["reused"] is False
        assert client.get(f"{BASE}/accesses/by-hash/a2").json()["access_id"] == "o1o1o1"
        assert client.get(f"{BASE}/accesses/by-hash/a1").status_code == 404
        assert client.get(f"{BASE}/accesses/by-refresh/zz").status_code == 404

    def test_clients_secret_check_never_returns_the_hash(self, client):
        out = client.post(f"{BASE}/oauth/clients", json={
            "client_id": "hmc_abcdefgh", "client_name": "ChatGPT", "redirect_uris": ["https://chatgpt.com/cb"],
            "auth_method": "client_secret_post", "secret_hash": "s" * 64}).json()
        assert out["has_secret"] is True and "s" * 64 not in str(out)
        assert client.post(f"{BASE}/oauth/clients", json={
            "client_id": "hmc_abcdefgh", "client_name": "x", "redirect_uris": ["https://x/cb"]}).status_code == 409
        check = f"{BASE}/oauth/clients/hmc_abcdefgh/check-secret"
        assert client.post(check, json={"secret_hash": "s" * 64}).json() == {"ok": True}
        assert client.post(check, json={"secret_hash": "x" * 64}).json() == {"ok": False}
        assert client.get(f"{BASE}/oauth/clients/hmc_abcdefgh").json()["redirect_uris"] == ["https://chatgpt.com/cb"]
        assert len(client.get(f"{BASE}/oauth/clients").json()["clients"]) == 1
        assert client.delete(f"{BASE}/oauth/clients/hmc_abcdefgh").json()["status"] == "deleted"
        assert client.get(f"{BASE}/oauth/clients/hmc_abcdefgh").status_code == 404

    def test_code_is_used_once(self, client):
        code = {"code_hash": "c" * 64, "client_id": "hmc_abcdefgh", "redirect_uri": "https://claude.ai/cb",
                "code_challenge": "ch", "scope": "write", "tools": ["forge_tasks"], "name": "claude.ai",
                "expires_days": 90, "expires_at": _later(minutes=5)}
        assert client.post(f"{BASE}/oauth/codes", json=code).status_code == 200
        first = client.post(f"{BASE}/oauth/codes/consume", json={"code_hash": "c" * 64, "access_id": "acc1"}).json()
        assert first["reused"] is False and first["scope"] == "write" and first["tools"] == ["forge_tasks"]
        again = client.post(f"{BASE}/oauth/codes/consume", json={"code_hash": "c" * 64, "access_id": "acc2"}).json()
        assert again["reused"] is True and again["access_id"] == "acc1"
        assert client.post(f"{BASE}/oauth/codes/consume",
                           json={"code_hash": "nope", "access_id": "a"}).status_code == 404
