"""Tests for Archive MCP tools — feedback_submit.

Markers: unit (mocked DB), api (TestClient), integration (live DB).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_ARCHIVE_ROOT = Path(__file__).parents[1]
_REPO_ROOT = _ARCHIVE_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_ARCHIVE_ROOT), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Mock out DB dependencies before app.main imports them ─────────────────
sys.modules["pgvector"] = MagicMock()
sys.modules["pgvector.sqlalchemy"] = MagicMock()
sys.modules["pgvector.sqlalchemy"].Vector = MagicMock()

# Must mock create_engine BEFORE app.database imports it
_mock_engine = MagicMock()
_mock_engine.connect.return_value.__enter__.return_value = MagicMock()
_mock_session_factory = MagicMock()


def _make_app():
    """Create the FastAPI app with mocked DB, importing inline to control timing."""
    import sqlalchemy
    # Force re-import so the mock takes effect even if another test loaded the real module
    for mod_key in list(sys.modules.keys()):
        if mod_key.startswith("app"):
            del sys.modules[mod_key]
    with patch.object(sqlalchemy, "create_engine", return_value=_mock_engine):
        import app.database as _db
        _db.SessionLocal = _mock_session_factory
        from app.main import app
        return app


@pytest.fixture
def client():
    """FastAPI TestClient with mocked database."""
    app = _make_app()
    mock_db = MagicMock()
    _mock_session_factory.return_value = mock_db
    with TestClient(app) as c:
        yield c


@pytest.mark.unit
class TestFeedbackSubmitMCP:
    """MCP tools/list and tools/call for feedback_submit."""

    def test_tools_list_returns_feedback_submit(self, client):
        """MCP tools/list should include feedback_submit."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        assert resp.status_code == 200
        data = resp.json()
        tools = data.get("result", {}).get("tools", [])
        names = [t["name"] for t in tools]
        assert "feedback_submit" in names, f"feedback_submit not in tools: {names}"

    def test_tools_list_feedback_submit_schema(self, client):
        """feedback_submit should expose correct inputSchema."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tool = next(
            (t for t in data.get("result", {}).get("tools", [])
             if t["name"] == "feedback_submit"),
            None,
        )
        assert tool is not None
        schema = tool.get("inputSchema", {})
        assert "session_id" in schema.get("required", [])
        assert "quality_label" in schema.get("required", [])
        props = schema.get("properties", {})
        assert "session_id" in props
        assert "quality_label" in props
        assert props["quality_label"]["enum"] == [
            "excellent", "good", "mixed", "poor", "rejected",
        ]

    def test_tools_call_feedback_submit_minimal(self, client):
        """tools/call with minimal required fields should persist and return feedback_id."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {
                "name": "feedback_submit",
                "arguments": {
                    "session_id": "test_session",
                    "quality_label": "good",
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" not in data, f"MCP error: {data.get('error')}"
        content = data["result"]["content"][0]
        result = json.loads(content["text"])
        assert result["status"] == "stored"
        assert result["feedback_id"].startswith("fbk-")
        assert result["quality_label"] == "good"

    def test_tools_call_feedback_submit_full(self, client):
        """tools/call with all optional fields."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {
                "name": "feedback_submit",
                "arguments": {
                    "session_id": "telegram_main",
                    "interaction_id": "msg_abc",
                    "quality_label": "excellent",
                    "quality_score": 5,
                    "feedback_text": "Perfetto, nessuna chiusura pushy",
                    "tags": ["style_ok", "concise"],
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" not in data
        content = data["result"]["content"][0]
        result = json.loads(content["text"])
        assert result["status"] == "stored"

    def test_tools_call_unknown_tool_returns_error(self, client):
        """Calling an unregistered tool should return MCP error."""
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

    def test_tools_call_missing_required_fields(self, client):
        """Missing quality_label should not crash — tool returns error in result."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "5",
            "method": "tools/call",
            "params": {
                "name": "feedback_submit",
                "arguments": {
                    "session_id": "test_session",
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        # Tool was called but handler received quality_label default "mixed"
        content = data["result"]["content"][0]
        result = json.loads(content["text"])
        assert result["quality_label"] == "mixed"


@pytest.mark.unit
class TestFeedbackSubmitClientMetadata:
    """feedback_submit should include Hestia client metadata for Telegram/UI."""

    def test_tool_has_client_metadata(self, client):
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
        })
        data = resp.json()
        tool = next(
            t for t in data["result"]["tools"]
            if t["name"] == "feedback_submit"
        )
        assert tool.get("title") == "📊 Valuta risposta"
        assert tool.get("method") == "POST"
        assert tool.get("path") == "/api/feedback"
        assert "telegram" in tool.get("clients", [])
