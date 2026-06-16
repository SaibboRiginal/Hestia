"""Oracle test conftest — path setup and Oracle-specific fixtures.

Adds the Oracle app/ directory and Hestia-Shared to sys.path so that all
Oracle module imports resolve correctly without Docker or a running service.

Fixtures:
    oracle_app_path: Path to the Oracle app directory.
    mock_hub_client: Pre-configured MagicMock for HubClient.
    mock_agent_bundle: Pre-configured MagicMock for AgentBundle (all agents mocked).
    make_universal_agent: Factory for a stubbed UniversalAgent.
    make_oracle_engine: Factory that creates OracleEngine with all deps mocked.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_ORACLE_ROOT = Path(__file__).parents[1]
_APP_PATH = _ORACLE_ROOT / "app"
_REPO_ROOT = _ORACLE_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"

for _p in [str(_APP_PATH), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Environment defaults (must be set before any Oracle module is imported) ───
# empty → auto-fallback to Ollama
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434/api/generate")
os.environ.setdefault("OLLAMA_TOOL_CALL_MODE", "auto")
os.environ.setdefault("HUB_API_URL", "http://fake-hub:19001/api")
os.environ.setdefault("ARCHIVE_URL", "http://fake-archive:19002/api")
os.environ.setdefault("ORACLE_MAX_AGENT_TURNS", "6")
os.environ.setdefault("ORACLE_TOOL_RESULT_MAX_CHARS", "2000")
os.environ.setdefault("LOG_LEVEL", "WARNING")     # quiet during tests


@pytest.fixture(scope="session")
def oracle_app_path() -> Path:
    return _APP_PATH


# ── Agent / LLM stubs ─────────────────────────────────────────────────────────


def _make_agent_mock(default_response: str = "ok") -> MagicMock:
    """Return a UniversalAgent mock whose ask() returns a string."""
    agent = MagicMock()
    agent.ask.return_value = default_response
    agent.ask_with_tools.return_value = {
        "tool_call": None, "text": default_response}
    agent.stream.return_value = iter([default_response])
    agent.model_name = "mock-model"
    agent.provider = "ollama"
    return agent


@pytest.fixture()
def mock_generic_agent():
    """Generic agent handles chat, classify, tools, memory — everything."""
    agent = _make_agent_mock("Mock generic answer.")
    # For classify calls, return valid JSON
    agent.ask.return_value = json.dumps({
        "mode": "quick_chat", "domain": None, "confidence": 0.9,
        "domains": ["general"], "filters": {}, "filters_gt": {},
        "filters_lt": {}, "sort_by": None, "sort_order": "desc",
        "action_intent": False,
    })
    return agent


@pytest.fixture()
def mock_agent_bundle(mock_generic_agent):
    """Full AgentBundle with use-case agents mocked."""
    bundle = MagicMock()
    bundle.generic = mock_generic_agent
    bundle.generic_fallback = _make_agent_mock("Fallback generic answer.")
    bundle.reasoning = _make_agent_mock("Mock reasoning answer.")
    bundle.reasoning_fallback = _make_agent_mock("Fallback reasoning answer.")
    bundle.code = _make_agent_mock("Mock code answer.")
    bundle.code_fallback = _make_agent_mock("Fallback code answer.")
    bundle.embedding = _make_agent_mock("")
    bundle.embedding_fallback = _make_agent_mock("")
    bundle.generic_model_name = "mock-model"
    return bundle


@pytest.fixture()
def mock_hub_client():
    """Minimal HubClient mock that returns empty defaults for all calls."""
    client = MagicMock()
    client.get.return_value = []
    client.post.return_value = {"ok": True}
    client.route_get.return_value = {}
    client.route_post.return_value = {}
    return client


# ── Helpers for building agent-loop tool-call LLM outputs ────────────────────


def xml_tool_call(name: str, params: dict) -> str:
    """Build the <tool_call> XML format the agent loop parses."""
    return f'<tool_call>{json.dumps({"name": name, "params": params})}</tool_call>'


def json_block_tool_call(name: str, params: dict) -> str:
    return f'```json\n{json.dumps({"name": name, "params": params})}\n```'


def plain_json_tool_call(name: str, params: dict) -> str:
    return json.dumps({"name": name, "params": params})


@pytest.fixture()
def xml_tool_call_factory():
    return xml_tool_call


@pytest.fixture()
def json_block_tool_call_factory():
    return json_block_tool_call


@pytest.fixture()
def plain_json_tool_call_factory():
    return plain_json_tool_call


# ── Live-LLM marker ───────────────────────────────────────────────────────────
# llm_live tests are ALWAYS skipped unless --run-live is passed explicitly.
# They require a running Ollama instance and are too heavy for regular CI/dev loops.
# Usage: python -m pytest tests/ -m llm_live --run-live


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run llm_live tests (requires Ollama)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip llm_live tests unless --run-live is passed AND Ollama is reachable."""
    run_live = config.getoption("--run-live")

    ollama_available = False
    if run_live:
        import urllib.request
        ollama_url = os.environ.get(
            "OLLAMA_URL", "http://localhost:11434/api/generate")
        ollama_base = ollama_url.rsplit("/api/", 1)[0]
        try:
            urllib.request.urlopen(f"{ollama_base}/api/tags", timeout=3)
            ollama_available = True
        except Exception:
            pass

    skip_live = pytest.mark.skip(
        reason="Ollama not reachable or --run-live not set. "
               "Use: python -m pytest tests/ -m llm_live --run-live")
    for item in items:
        if "llm_live" in item.keywords:
            if not run_live or not ollama_available:
                item.add_marker(skip_live)
