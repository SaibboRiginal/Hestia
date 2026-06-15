"""Tests — Hecate gateway (Phase 7)

Tests for Hecate service: provider detection, state manager, health endpoint.
No real OAuth providers are created — env vars disable them.
"""
from __future__ import annotations

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Provider detection
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestProviderDetection:
    def test_no_env_vars_no_providers(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
        from main import detect_gateway_providers
        providers = detect_gateway_providers()
        assert providers == []

    def test_google_enabled_via_force_env(self, monkeypatch):
        monkeypatch.setenv("HECATE_ENABLE_PROVIDER_GOOGLE", "1")
        from main import detect_gateway_providers
        providers = detect_gateway_providers()
        assert any(p["provider"] == "google" for p in providers)
        monkeypatch.setenv("HECATE_ENABLE_PROVIDER_GOOGLE", "0")


# ─────────────────────────────────────────────────────────────────────────────
# StateManager
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestStateManager:
    def test_initial_last_run_is_past(self):
        from datetime import datetime
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmppath = f.name
        os.unlink(tmppath)
        from core.state_manager import StateManager
        sm = StateManager(tmppath)
        date = sm.get_last_run_date("fetcher_a", default_days_back=3)
        assert date < datetime.now()

    def test_mark_as_run_stores_date(self):
        from datetime import datetime
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmppath = f.name
        os.unlink(tmppath)
        from core.state_manager import StateManager
        sm = StateManager(tmppath)
        sm.mark_as_run("fetcher_b")
        loaded = StateManager(tmppath)
        date = loaded.get_last_run_date("fetcher_b")
        # Date should be within the last minute
        diff = abs((datetime.now() - date).total_seconds())
        assert diff < 60
        if os.path.exists(tmppath):
            os.unlink(tmppath)

    def test_get_last_run_missing_fetcher_uses_default(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmppath = f.name
        os.unlink(tmppath)
        from core.state_manager import StateManager
        sm = StateManager(tmppath)
        from datetime import datetime
        date = sm.get_last_run_date("unknown_fetcher", default_days_back=7)
        diff = (datetime.now() - date).days
        assert 6 <= diff <= 8


# ─────────────────────────────────────────────────────────────────────────────
# Hecate health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestHecateHealth:
    def test_health_returns_ok(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("core.state_manager.StateManager.__init__", return_value=None), \
                patch("core.state_manager.StateManager._load_state", return_value={}), \
                patch("core.archive_client.ArchiveClient.__init__", return_value=None):
            from fastapi.testclient import TestClient
            import main as hecate_main
            client = TestClient(hecate_main.app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_service_hecate(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("core.state_manager.StateManager.__init__", return_value=None), \
                patch("core.state_manager.StateManager._load_state", return_value={}), \
                patch("core.archive_client.ArchiveClient.__init__", return_value=None):
            from fastapi.testclient import TestClient
            import main as hecate_main
            client = TestClient(hecate_main.app, raise_server_exceptions=False)
        body = client.get("/health").json()
        assert body.get("status") == "ok"
