"""Tests — Hub service registry (Phase 4.1)

Tests for ServiceRegistry CRUD operations (pure unit tests — no HTTP).
"""
from __future__ import annotations

import time
import pytest

from modules.registry import ServiceRegistry


@pytest.fixture
def reg():
    return ServiceRegistry()


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestServiceRegistryRegister:
    def test_register_new_service_returns_created(self, reg):
        status = reg.register({"name": "svc_a", "base_url": "http://a:1234"})
        assert status == "created"

    def test_second_identical_returns_refreshed(self, reg):
        reg.register(
            {"name": "svc_a", "base_url": "http://a:1234", "commands": []})
        status = reg.register(
            {"name": "svc_a", "base_url": "http://a:1234", "commands": []})
        assert status == "refreshed"

    def test_changed_commands_returns_updated(self, reg):
        reg.register(
            {"name": "svc_b", "base_url": "http://b:1234", "commands": []})
        status = reg.register(
            {"name": "svc_b", "base_url": "http://b:1234", "commands": ["cmd1"]})
        assert status == "updated"

    def test_name_normalized_to_lowercase(self, reg):
        reg.register({"name": "SVC_C", "base_url": "http://c:1234"})
        services = reg.all_services()
        assert any(s["name"] == "svc_c" for s in services)

    def test_multiple_instances_same_service(self, reg):
        reg.register({"name": "svc_d", "base_url": "http://d1:1234"})
        reg.register({"name": "svc_d", "base_url": "http://d2:1234"})
        entries = reg.get("svc_d")
        assert len(entries) == 2

    def test_updated_at_is_recent(self, reg):
        before = time.time()
        reg.register({"name": "svc_e", "base_url": "http://e:1234"})
        after = time.time()
        entry = reg.get("svc_e")[0]
        assert before <= entry["updated_at"] <= after


# ─────────────────────────────────────────────────────────────────────────────
# Deregistration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestServiceRegistryDeregister:
    def test_deregister_removes_service(self, reg):
        reg.register({"name": "svc_f", "base_url": "http://f:1234"})
        reg.deregister("svc_f")
        assert reg.get("svc_f") == []

    def test_deregister_by_url_removes_only_instance(self, reg):
        reg.register({"name": "svc_g", "base_url": "http://g1:1234"})
        reg.register({"name": "svc_g", "base_url": "http://g2:1234"})
        reg.deregister("svc_g", base_url="http://g1:1234")
        entries = reg.get("svc_g")
        assert len(entries) == 1
        assert entries[0]["base_url"] == "http://g2:1234"

    def test_deregister_nonexistent_is_noop(self, reg):
        reg.deregister("nonexistent_service")
        assert reg.all_services() == []


# ─────────────────────────────────────────────────────────────────────────────
# Hub FastAPI endpoints
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def hub_client():
    from unittest.mock import patch, MagicMock
    with patch("requests.post"), patch("requests.get"):
        from fastapi.testclient import TestClient
        import src.main as hub_main
        client = TestClient(hub_main.app, raise_server_exceptions=False)
        yield client


@pytest.mark.api
class TestHubApiHealth:
    def test_health_returns_200(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        with patch("requests.post"), patch("requests.get"):
            import src.main as hub_main
            client = TestClient(hub_main.app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_has_status_ok(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        with patch("requests.post"), patch("requests.get"):
            import src.main as hub_main
            client = TestClient(hub_main.app, raise_server_exceptions=False)
        body = client.get("/health").json()
        assert body.get("status") == "ok"


@pytest.mark.api
class TestHubRegistryEndpoints:
    @pytest.fixture(autouse=True)
    def _client(self, monkeypatch):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        with patch("requests.post"), patch("requests.get"):
            import src.main as hub_main
            self.client = TestClient(
                hub_main.app, raise_server_exceptions=False)
        monkeypatch.setattr("requests.post", lambda *a, **kw: __import__(
            'unittest.mock', fromlist=['MagicMock']).MagicMock(status_code=200))
        monkeypatch.setattr("requests.get", lambda *a, **kw: __import__(
            'unittest.mock', fromlist=['MagicMock']).MagicMock(status_code=200))

    def test_register_endpoint_returns_ok(self):
        resp = self.client.post("/api/registry/register", json={
            "name": "test_svc",
            "base_url": "http://test:9999",
            "tags": ["core"],
        })
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"

    def test_list_endpoint_returns_services(self):
        self.client.post("/api/registry/register", json={
            "name": "list_svc",
            "base_url": "http://list:9999",
            "tags": ["core"],
        })
        resp = self.client.get("/api/registry/services")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list) or isinstance(body.get("services"), list)

    def test_deregister_endpoint_returns_ok(self):
        self.client.post("/api/registry/register", json={
            "name": "dereg_svc",
            "base_url": "http://dereg:9999",
            "tags": ["core"],
        })
        resp = self.client.post("/api/registry/deregister", json={
            "name": "dereg_svc",
            "base_url": "http://dereg:9999",
        })
        assert resp.status_code == 200
