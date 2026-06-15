"""Tests — ModuleToolRegistry (Phase 1.5)

Unit tests for TTL-based cache, domain URL resolution, Hub discovery,
and query routing. All HTTP calls mocked.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
import pytest

from core.services.module_registry import ModuleToolRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fake_domains_response(domains: list[str]):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"domains": domains}
    return resp


def _fake_hub_module_tools(mapping: dict):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"mapping": mapping}
    return resp


def _fake_hub_services(services: list[dict]):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"services": services}
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestModuleToolRegistryInit:
    def test_empty_urls_registry_is_empty(self):
        reg = ModuleToolRegistry(module_tool_urls=[])
        # No URLs → _needs_refresh() is True but refresh() finds nothing
        with patch("requests.get", return_value=MagicMock(status_code=500)):
            urls = reg.get_urls_for_domain("scout")
        assert urls == []

    def test_trailing_slashes_stripped(self):
        reg = ModuleToolRegistry(
            module_tool_urls=["http://tool-service:8080/"])
        assert reg.module_tool_urls == ["http://tool-service:8080"]


@pytest.mark.unit
class TestModuleToolRegistryRefresh:
    def test_refresh_populates_domain_urls(self):
        reg = ModuleToolRegistry(
            module_tool_urls=["http://scout:8080"],
        )
        with patch("requests.get", return_value=_fake_domains_response(["scout", "real_estate"])):
            reg.refresh()
        assert "scout" in reg._domain_to_urls
        assert "http://scout:8080" in reg._domain_to_urls["scout"]

    def test_hub_mapping_overrides_direct_urls(self):
        reg = ModuleToolRegistry(
            module_tool_urls=[],
            hub_api_url="http://hub:19001/api",
        )

        def _fake_get(url, **kwargs):
            if "module-tools" in url:
                return _fake_hub_module_tools({"scout": ["http://hub-routed-scout:8080"]})
            if "registry/services" in url:
                return _fake_hub_services([])
            return MagicMock(status_code=404)

        with patch("requests.get", side_effect=_fake_get):
            reg.refresh()
        assert "scout" in reg._domain_to_urls

    def test_failed_endpoint_skipped_silently(self):
        reg = ModuleToolRegistry(
            module_tool_urls=["http://bad-service:9999"],
        )
        with patch("requests.get", side_effect=ConnectionError("unreachable")):
            # Should not raise
            reg.refresh()
        assert reg._domain_to_urls == {}

    def test_refresh_deduplicates_urls(self):
        reg = ModuleToolRegistry(
            module_tool_urls=["http://tool:8080", "http://tool:8080"],
        )
        with patch("requests.get", return_value=_fake_domains_response(["search"])):
            reg.refresh()
        urls = reg._domain_to_urls.get("search", [])
        assert len(urls) == len(set(urls))


@pytest.mark.unit
class TestModuleToolRegistryTTL:
    def test_registry_needs_refresh_when_empty(self):
        reg = ModuleToolRegistry(module_tool_urls=[], ttl_seconds=60)
        assert reg._needs_refresh() is True

    def test_registry_does_not_need_refresh_after_recent_refresh(self):
        reg = ModuleToolRegistry(module_tool_urls=[], ttl_seconds=120)
        reg._last_refresh = time.time()
        reg._domain_to_urls = {"scout": ["http://x"]}
        assert reg._needs_refresh() is False

    def test_registry_needs_refresh_after_ttl_expired(self):
        reg = ModuleToolRegistry(module_tool_urls=[], ttl_seconds=1)
        reg._last_refresh = time.time() - 2  # 2 seconds ago
        reg._domain_to_urls = {"scout": ["http://x"]}
        assert reg._needs_refresh() is True


@pytest.mark.unit
class TestModuleToolRegistryGetUrls:
    def test_unknown_domain_returns_empty_list(self):
        reg = ModuleToolRegistry(module_tool_urls=[])
        reg._domain_to_urls = {"scout": ["http://x"]}
        reg._last_refresh = time.time()
        result = reg.get_urls_for_domain("nonexistent")
        assert result == []

    def test_known_domain_returns_urls(self):
        reg = ModuleToolRegistry(module_tool_urls=[])
        reg._domain_to_urls = {"chronos": ["http://chronos:8080"]}
        reg._last_refresh = time.time()
        result = reg.get_urls_for_domain("chronos")
        assert "http://chronos:8080" in result

    def test_domain_lookup_case_insensitive(self):
        reg = ModuleToolRegistry(module_tool_urls=[])
        reg._domain_to_urls = {"scout": ["http://x"]}
        reg._last_refresh = time.time()
        # Both lowercase and uppercase should resolve
        assert reg.get_urls_for_domain(
            "SCOUT") == reg.get_urls_for_domain("scout")
