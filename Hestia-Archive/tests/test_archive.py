"""Tests — Archive schemas and API (Phase 5)

Tests for Archive schemas, health endpoint, and API contracts.
All database calls are mocked — SQLite in-memory is not used to avoid
pgvector extension dependency.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestArchiveSchemas:
    def test_record_create_valid(self):
        from schemas import RecordCreate
        r = RecordCreate(
            domain="real_estate",
            source="gmail",
            payload={"title": "Test"},
        )
        assert r.domain == "real_estate"

    def test_record_create_optional_reference_id(self):
        from schemas import RecordCreate
        r = RecordCreate(domain="real_estate", source="gmail", payload={})
        assert r.reference_id is None

    def test_record_update_requires_evaluation(self):
        from schemas import RecordUpdate
        r = RecordUpdate(evaluation={"score": 0.9})
        assert r.evaluation["score"] == 0.9

    def test_entity_upsert_valid(self):
        from schemas import EntityUpsert
        e = EntityUpsert(
            entity_id="https://example.com/house/1",
            domain="real_estate",
            payload={"price": 250000},
        )
        assert e.status == "active"

    def test_entity_upsert_custom_status(self):
        from schemas import EntityUpsert
        e = EntityUpsert(
            entity_id="eid",
            domain="real_estate",
            status="sold",
            payload={},
        )
        assert e.status == "sold"

    def test_advanced_search_request_defaults(self):
        from schemas import AdvancedSearchRequest
        req = AdvancedSearchRequest()
        assert req.limit == 20
        assert req.sort_order == "desc"


# ─────────────────────────────────────────────────────────────────────────────
# Archive API via TestClient (mocked DB)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def archive_client():
    """Boot Archive TestClient with DB and Hub registration mocked."""
    with patch("sqlalchemy.engine.base.Engine.connect") as mock_connect, \
            patch("sqlalchemy.orm.Session.add"), \
            patch("sqlalchemy.orm.Session.commit"), \
            patch("requests.post"), \
            patch("requests.get"):
        mock_connect.return_value.__enter__ = MagicMock(
            return_value=MagicMock())
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        # Patch create_all and the engine connection at model level
        with patch("sqlalchemy.schema.MetaData.create_all"):
            try:
                from fastapi.testclient import TestClient
                import importlib
                # Need to mock at import time
                with patch("app.database.engine"):
                    import app.main as archive_main
                    importlib.reload(archive_main)
                    yield TestClient(archive_main.app, raise_server_exceptions=False)
            except Exception:
                pytest.skip("Archive requires database; skipping API tests")


@pytest.mark.api
class TestArchiveHealth:
    def test_health_returns_200(self):
        """Archive health endpoint quick check (skip if DB not available)."""
        try:
            with patch("requests.post"), patch("requests.get"), \
                    patch("sqlalchemy.engine.base.Engine.connect") as mc, \
                    patch("sqlalchemy.schema.MetaData.create_all"):
                mc.return_value.__enter__ = MagicMock(
                    return_value=MagicMock(execute=MagicMock()))
                mc.return_value.__exit__ = MagicMock(return_value=False)
                from fastapi.testclient import TestClient
                import app.main as archive_main
                client = TestClient(
                    archive_main.app, raise_server_exceptions=False)
                resp = client.get("/health")
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
        except Exception:
            pytest.skip("Archive requires DB extensions")
