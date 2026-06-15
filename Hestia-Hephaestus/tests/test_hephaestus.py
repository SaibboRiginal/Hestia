"""Tests — Hephaestus remediation service (Phase 11)

Tests for Hephaestus runbook definitions, consent tiers, models,
and the health endpoint.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Models and enums
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestConsentTierEnum:
    def test_all_tiers_present(self):
        from core.models import ConsentTier
        assert ConsentTier.none == "none"
        assert ConsentTier.low == "low"
        assert ConsentTier.medium == "medium"
        assert ConsentTier.high == "high"

    def test_remediation_request_defaults(self):
        from core.models import RemediationRequest
        req = RemediationRequest()
        assert req.dry_run is True
        assert req.environment == "dev"
        assert req.severity == "warning"


# ─────────────────────────────────────────────────────────────────────────────
# Runbook definitions
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunbooks:
    def test_runbooks_dict_not_empty(self):
        from core.runbooks import RUNBOOKS
        assert len(RUNBOOKS) > 0

    def test_each_runbook_has_required_fields(self):
        from core.runbooks import RUNBOOKS
        for rbk_id, rbk in RUNBOOKS.items():
            assert rbk.runbook_id == rbk_id
            assert rbk.title
            assert rbk.summary
            assert len(rbk.steps) > 0

    def test_steps_have_ids_and_titles(self):
        from core.runbooks import RUNBOOKS
        for rbk in RUNBOOKS.values():
            for step in rbk.steps:
                assert step.id
                assert step.title
                assert step.kind

    def test_health_triage_is_readonly(self):
        from core.runbooks import RUNBOOKS
        triage = RUNBOOKS.get("rbk_service_health_triage")
        assert triage is not None
        assert all(step.read_only for step in triage.steps)

    def test_high_consent_tier_not_production_allowed(self):
        from core.runbooks import RUNBOOKS
        for rbk in RUNBOOKS.values():
            # Production allowed should default to False for safety
            if rbk.consent_tier == "high":
                assert rbk.production_allowed is False


# ─────────────────────────────────────────────────────────────────────────────
# Hephaestus health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestHephaestusHealth:
    def test_health_returns_200(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("hestia_common.startup_utils.wait_for_http_ready"):
            from fastapi.testclient import TestClient
            import app.main as heph_main
            client = TestClient(heph_main.app, raise_server_exceptions=False)
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_service_hephaestus(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("hestia_common.startup_utils.wait_for_http_ready"):
            from fastapi.testclient import TestClient
            import app.main as heph_main
            client = TestClient(heph_main.app, raise_server_exceptions=False)
            body = client.get("/health").json()
        assert body.get("status") == "ok"
        assert "hephaestus" in body.get("service", "").lower()
