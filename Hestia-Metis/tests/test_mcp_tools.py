"""Tests for Metis MCP tools — tools/list and tools/call.

Markers: unit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_METIS_ROOT = Path(__file__).parents[1]
_APP_ROOT = _METIS_ROOT / "app"
_REPO_ROOT = _METIS_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_METIS_ROOT), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

EXPECTED_TOOLS = {
    "metis_dataset_build",
    "metis_dataset_export",
    "metis_dataset_status",
    "metis_benchmark_run",
    "metis_loRA_train",
}


@pytest.fixture
def client():
    """FastAPI TestClient with mocked external dependencies."""
    with patch("app.main.hub", MagicMock()):
        from app.main import app
        with TestClient(app) as c:
            yield c


@pytest.mark.unit
class TestMetisMCPToolsList:
    """MCP tools/list should expose all 5 Metis tools."""

    def test_all_five_tools_present(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        assert resp.status_code == 200
        data = resp.json()
        tools = data.get("result", {}).get("tools", [])
        names = {t["name"] for t in tools}
        missing = EXPECTED_TOOLS - names
        assert not missing, f"Missing tools: {missing}"

    def test_each_tool_has_required_fields(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tools = data.get("result", {}).get("tools", [])
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_dataset_build_requires_name(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tool = next(
            t for t in data["result"]["tools"]
            if t["name"] == "metis_dataset_build"
        )
        assert "name" in tool["inputSchema"].get("required", [])

    def test_dataset_export_requires_name(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tool = next(
            t for t in data["result"]["tools"]
            if t["name"] == "metis_dataset_export"
        )
        assert "name" in tool["inputSchema"].get("required", [])


@pytest.mark.unit
class TestMetisMCPToolsCall:
    """MCP tools/call for individual tools."""

    def test_dataset_status(self, client):
        """Status should work even with empty store."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {
                "name": "metis_dataset_status",
                "arguments": {},
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" not in data
        content = data["result"]["content"][0]
        result = json.loads(content["text"])
        assert result["status"] == "ok"

    def test_dataset_export_not_found(self, client):
        """Export of nonexistent dataset returns not_found."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {
                "name": "metis_dataset_export",
                "arguments": {"name": "nonexistent"},
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" not in data
        content = data["result"]["content"][0]
        result = json.loads(content["text"])
        assert result["status"] == "not_found"

    def test_unknown_tool_returns_error(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "4",
            "method": "tools/call",
            "params": {
                "name": "nonexistent_tool",
                "arguments": {},
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32601


@pytest.mark.unit
class TestMetisClientMetadata:
    """All tools should have Telegram client metadata."""

    def test_all_tools_have_telegram_group(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tools = data["result"]["tools"]
        for tool in tools:
            assert "telegram_group" in tool, (
                f"{tool['name']} missing telegram_group"
            )

    def test_visible_tools(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tools = data["result"]["tools"]
        for tool in tools:
            # All should be telegram_visible (no "telegram_visible": false in output)
            assert tool.get("telegram_visible") is not False, (
                f"{tool['name']} should be telegram_visible"
            )
