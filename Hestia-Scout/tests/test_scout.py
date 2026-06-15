"""Tests — Scout real-estate retrieval (Phase 12)

Tests for Scout geocoding utilities, schemas, and health endpoint.
No real external HTTP calls.
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# haversine_km
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHaversine:
    def test_same_point_is_zero(self):
        from tools.geocoding import haversine_km
        assert haversine_km(
            45.0, 9.0, 45.0, 9.0) == pytest.approx(0.0, abs=0.01)

    def test_milan_rome_approx_distance(self):
        from tools.geocoding import haversine_km
        # Milan (45.46, 9.19) to Rome (41.90, 12.49) ≈ 477 km
        dist = haversine_km(45.46, 9.19, 41.90, 12.49)
        assert 450 < dist < 510

    def test_symmetry(self):
        from tools.geocoding import haversine_km
        d1 = haversine_km(45.0, 9.0, 41.9, 12.5)
        d2 = haversine_km(41.9, 12.5, 45.0, 9.0)
        assert d1 == pytest.approx(d2, abs=0.001)


# ─────────────────────────────────────────────────────────────────────────────
# extract_city_from_text
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractCityFromText:
    def test_extract_after_in(self):
        from tools.geocoding import extract_city_from_text
        result = extract_city_from_text("case in Milano")
        assert result is not None
        assert "milano" in result.lower()

    def test_extract_after_a(self):
        from tools.geocoding import extract_city_from_text
        result = extract_city_from_text("appartamenti a Roma")
        assert result is not None
        assert "roma" in result.lower()

    def test_no_keyword_returns_none(self):
        from tools.geocoding import extract_city_from_text
        result = extract_city_from_text("cercasi appartamento trilocale")
        assert result is None

    def test_empty_string_returns_none(self):
        from tools.geocoding import extract_city_from_text
        assert extract_city_from_text("") is None


# ─────────────────────────────────────────────────────────────────────────────
# GeocodingService caching
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGeocodingService:
    def test_empty_query_returns_none(self):
        from tools.geocoding import GeocodingService
        svc = GeocodingService()
        assert svc.geocode("") is None

    def test_cache_hit_avoids_network(self, monkeypatch):
        monkeypatch.setattr("requests.get", lambda *a, **
                            kw: (_ for _ in ()).throw(AssertionError("network called")))
        from tools.geocoding import GeocodingService
        svc = GeocodingService()
        svc._cache["milano"] = (45.46, 9.19)
        result = svc.geocode("Milano")
        assert result == (45.46, 9.19)

    def test_network_error_returns_none(self, monkeypatch):
        monkeypatch.setattr("requests.get", lambda *a, **
                            kw: (_ for _ in ()).throw(ConnectionError("timeout")))
        from tools.geocoding import GeocodingService
        svc = GeocodingService()
        result = svc.geocode("NonexistentCityXYZ")
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Scout schemas
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestScoutSchemas:
    def test_real_estate_search_request_defaults(self):
        from tools.schemas import RealEstateSearchRequest
        req = RealEstateSearchRequest()
        assert req.limit == 12
        assert req.nearby is False
        assert req.radius_km == 20.0

    def test_module_tool_query_request_valid(self):
        from tools.schemas import ModuleToolQueryRequest
        req = ModuleToolQueryRequest(
            domain="real_estate", query="trilocale Milano")
        assert req.domain == "real_estate"
        assert req.sort_order == "desc"


# ─────────────────────────────────────────────────────────────────────────────
# Scout health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestScoutHealth:
    def test_health_returns_200(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("hestia_common.startup_utils.wait_for_http_ready"), \
                patch("hestia_common.startup_utils.wait_for_hub_services"), \
                patch("worker.runner.ScoutWorker.__init__", return_value=None), \
                patch("tools.geocoding.GeocodingService.__init__", return_value=None), \
                patch("tools.retrieval.ScoutRetrievalService.__init__", return_value=None):
            from fastapi.testclient import TestClient
            import main as scout_main
            client = TestClient(scout_main.api_app,
                                raise_server_exceptions=False)
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_service_scout(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("hestia_common.startup_utils.wait_for_http_ready"), \
                patch("hestia_common.startup_utils.wait_for_hub_services"), \
                patch("worker.runner.ScoutWorker.__init__", return_value=None), \
                patch("tools.geocoding.GeocodingService.__init__", return_value=None), \
                patch("tools.retrieval.ScoutRetrievalService.__init__", return_value=None):
            from fastapi.testclient import TestClient
            import main as scout_main
            client = TestClient(scout_main.api_app,
                                raise_server_exceptions=False)
            body = client.get("/health").json()
        assert body.get("status") == "ok"
        assert "scout" in body.get("service", "").lower()
