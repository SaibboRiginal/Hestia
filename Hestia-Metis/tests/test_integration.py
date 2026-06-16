"""Integration tests for Metis — full flow with mocked Hub/Archive/Oracle HTTP.

These test the real handler logic end-to-end by mocking the HTTP layer
(requests.Session.post). No live services needed.

Markers: integration
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_METIS_ROOT = Path(__file__).parents[1]
_REPO_ROOT = _METIS_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_METIS_ROOT), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Mock Hub/Archive responses ───────────────────────────────────────────────

_MOCK_FEEDBACK_RECORDS = [
    {
        "feedback_id": "fbk-001",
        "session_id": "test_session",
        "quality_label": "excellent",
        "quality_score": 5,
        "tags": ["style_ok", "domain=real_estate"],
        "payload": {
            "instruction": "Cerco trilocali a Milano sotto 300k",
            "output": "Trovato trilocale a Milano Centro, 280k, 85m².",
        },
    },
    {
        "feedback_id": "fbk-002",
        "session_id": "test_session",
        "quality_label": "good",
        "quality_score": 4,
        "tags": ["concise", "domain=calendar"],
        "payload": {
            "instruction": "Cosa ho in agenda oggi?",
            "output": "Oggi hai: Call con cliente alle 15:00.",
        },
    },
    {
        # Duplicate of fbk-001 (same user+assistant content)
        "feedback_id": "fbk-003",
        "session_id": "test_session2",
        "quality_label": "good",
        "quality_score": 4,
        "tags": ["domain=real_estate"],
        "payload": {
            "instruction": "Cerco trilocali a Milano sotto 300k",
            "output": "Trovato trilocale a Milano Centro, 280k, 85m².",
        },
    },
    {
        # No payload — should be skipped
        "feedback_id": "fbk-004",
        "session_id": "test_session",
        "quality_label": "poor",
        "quality_score": 2,
        "tags": [],
        "payload": {},
    },
]


def _mock_hub_response(payload: dict | list | str, status_code: int = 200):
    """Build a Hub routing envelope response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "status_code": status_code,
        "payload": payload,
    }
    mock_resp.content = json.dumps({
        "status_code": status_code,
        "payload": payload,
    }).encode()
    return mock_resp


@pytest.fixture
def client():
    """FastAPI TestClient with mocked Hub HTTP layer."""
    def _route_response(self, url, *args, **kwargs):
        """Mock for requests.Session.post — intercept Hub routing calls."""
        if "archive/api/feedback" in str(url):
            return _mock_hub_response(_MOCK_FEEDBACK_RECORDS)
        if "archive/api/chat/history" in str(url):
            return _mock_hub_response([
                {"role": "user", "content": "Ciao"},
                {"role": "assistant", "content": "Ciao. Dimmi."},
            ])
        if "route/oracle" in str(url):
            return _mock_hub_response(
                {"response": json.dumps([
                    {"turn": 1, "style": 5, "accuracy": 5,
                     "usefulness": 5, "overall": "excellent",
                     "notes": "ok"},
                ])}
            )
        # Hub registration / other fallback
        return _mock_hub_response({"status": "ok"})

    with patch("requests.sessions.Session.post", _route_response):
        from app.main import app
        with TestClient(app) as c:
            yield c


@pytest.mark.integration
class TestMetisDatasetFlow:
    """Build → export → status — full pipeline."""

    def test_build_dataset_from_mocked_feedback(self, client):
        """metis_dataset_build should pull feedback via Hub, deduplicate, store."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": "metis_dataset_build",
                "arguments": {
                    "name": "test-v1",
                    "quality_labels": ["excellent", "good"],
                    "deduplicate": True,
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" not in data, f"MCP error: {data.get('error')}"
        result = json.loads(data["result"]["content"][0]["text"])
        # Success returns metadata with name/total_kept; empty returns status=empty
        assert result.get("name") == "test-v1"
        assert result["total_kept"] >= 1  # at least one valid example
        assert result["skipped_no_payload"] >= 1  # the empty-payload record skipped

    def test_dataset_status_after_build(self, client):
        """metis_dataset_status should show the built dataset."""
        # Build first
        client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {"name": "metis_dataset_build", "arguments": {"name": "test-v1"}},
        })
        # Then check status
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "2", "method": "tools/call",
            "params": {"name": "metis_dataset_status", "arguments": {}},
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        datasets = result.get("datasets", [])
        assert len(datasets) >= 1

    def test_export_chatml_format(self, client):
        """metis_dataset_export should return valid ChatML JSONL."""
        # Build
        client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {"name": "metis_dataset_build", "arguments": {"name": "test-v1"}},
        })
        # Export
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "2", "method": "tools/call",
            "params": {"name": "metis_dataset_export", "arguments": {"name": "test-v1", "format": "chatml"}},
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert result["format"] == "chatml"
        assert result["examples"] >= 1
        # Parse first line as JSON
        lines = result["jsonl"].strip().split("\n")
        first = json.loads(lines[0])
        assert "messages" in first
        assert len(first["messages"]) == 3  # system, user, assistant
        assert first["messages"][0]["role"] == "system"
        assert first["messages"][1]["role"] == "user"
        assert first["messages"][2]["role"] == "assistant"

    def test_export_alpaca_format(self, client):
        """metis_dataset_export in Alpaca format."""
        client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {"name": "metis_dataset_build", "arguments": {"name": "test-v1"}},
        })
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "2", "method": "tools/call",
            "params": {"name": "metis_dataset_export", "arguments": {"name": "test-v1", "format": "alpaca"}},
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        lines = result["jsonl"].strip().split("\n")
        first = json.loads(lines[0])
        assert "instruction" in first
        assert "output" in first

    def test_benchmark_without_dataset(self, client):
        """metis_benchmark_run without dataset returns no_dataset."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {
                "name": "metis_benchmark_run",
                "arguments": {
                    "candidate_model": "gemma4:e4b",
                    "dataset_name": "nonexistent",
                },
            },
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["status"] == "no_dataset"

    def test_lora_train_without_dataset(self, client):
        """metis_loRA_train without dataset returns no_dataset."""
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {
                "name": "metis_loRA_train",
                "arguments": {
                    "dataset_name": "nonexistent",
                    "adapter_name": "test-adapter",
                },
            },
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["status"] == "no_dataset"
        assert "job_id" in result

    def test_lora_train_with_dataset(self, client):
        """metis_loRA_train with a built dataset returns triggered status."""
        client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {"name": "metis_dataset_build", "arguments": {"name": "test-v1"}},
        })
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "2", "method": "tools/call",
            "params": {
                "name": "metis_loRA_train",
                "arguments": {
                    "dataset_name": "test-v1",
                    "adapter_name": "test-adapter",
                },
            },
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["status"] in ("triggered", "no_training_script")
        assert result["examples"] >= 1
        assert result["adapter_name"] == "test-adapter"


@pytest.mark.integration
class TestMetisEmptyDataset:
    """Edge cases with no feedback data."""

    @pytest.fixture
    def empty_client(self):
        """Client with empty Archive feedback."""
        with patch("requests.post") as mock_post:
            def _empty_route(url, *args, **kwargs):
                if "archive/api/feedback" in url:
                    return _mock_hub_response([])
                return _mock_hub_response({"status": "ok"})
            mock_post.side_effect = _empty_route
            from app.main import app
            with TestClient(app) as c:
                yield c

    def test_build_empty_dataset(self, empty_client):
        """Building with no feedback returns empty status."""
        resp = empty_client.post("/mcp", json={
            "jsonrpc": "2.0", "id": "1", "method": "tools/call",
            "params": {"name": "metis_dataset_build", "arguments": {"name": "empty-ds"}},
        })
        data = resp.json()
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["status"] == "empty"
