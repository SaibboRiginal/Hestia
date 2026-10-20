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
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call
import pytest

# ── Register TRACE log level (hestia_common.logging_utils does this at runtime) ─
if not hasattr(logging, 'TRACE'):
    logging.TRACE = 5
    logging.addLevelName(logging.TRACE, 'TRACE')
    def _trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(logging.TRACE):
            self._log(logging.TRACE, msg, args, **kwargs)
    logging.Logger.trace = _trace

# ── Path setup ────────────────────────────────────────────────────────────────
_ORACLE_ROOT = Path(__file__).parents[1]
_APP_PATH = _ORACLE_ROOT / "app"
_REPO_ROOT = _ORACLE_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"

for _p in [str(_APP_PATH), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Environment defaults (must be set before any Oracle module is imported) ───
# No provider keys (ORACLE_KEY_*): cloud steps of every chain are skipped as "not available".
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434/api/generate")
os.environ.setdefault("HUB_API_URL", "http://fake-hub:19001/api")
os.environ.setdefault("ARCHIVE_URL", "http://fake-archive:19002/api")
os.environ.setdefault("LOG_LEVEL", "WARNING")     # quiet during tests
# Models and every tunable come from central settings (oracle_settings defaults; no Themis in tests).
# A test changes one with monkeypatch.setitem(oracle_settings.settings._effective, KEY, value).


@pytest.fixture(autouse=True)
def _llm_chains_isolated(monkeypatch):
    """No Hub in tests: no module use cases from the registry, usage rows kept in ``llm_usage.captured``
    instead of pushed to Archive; quota state and caches start empty."""
    from core.services import llm_chains, llm_usage
    captured: list = []
    monkeypatch.setattr(llm_usage, "captured", captured, raising=False)
    monkeypatch.setattr(llm_usage, "push", captured.append)
    monkeypatch.setattr(llm_chains, "_registry_services", lambda: [])
    monkeypatch.setattr(llm_chains, "_registry_cache", (0.0, []))
    llm_chains.clear_exhausted()
    llm_chains._seen_usecases.clear()
    llm_chains._chain_agents.clear()
    yield
    llm_chains.clear_exhausted()


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
    bundle.reasoning = _make_agent_mock("Mock reasoning answer.")
    bundle.code = _make_agent_mock("Mock code answer.")
    bundle.documents = _make_agent_mock("Mock documents answer.")
    bundle.embedding = _make_agent_mock("")
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


class HubBackedMCP:
    """Test double of ``hestia_common.mcp_client.MCPClient`` that keeps the old test hooks working:
    tools come from ``hub.get_commands()`` (as Hestia-MCP would list them) and calls go to
    ``hub.route_to_service`` after the same template rules Hestia-MCP applies (``hestia_common.tool_call``)."""

    def __init__(self, hub):
        self._hub = hub
        self.calls: list[tuple[str, dict, dict]] = []

    def list_tools(self, **_kw) -> list[dict]:
        from hestia_common.tool_call import is_write, template_vars
        tools = []
        for cmd in self._hub.get_commands() or []:
            args = cmd.get("arguments_schema") or {}
            if args:
                props = {k: {"type": v.get("type", "string"), "description": v.get("description", k)} for k, v in args.items()}
                required = [k for k, v in args.items() if v.get("required")]
            else:
                names = template_vars(cmd.get("body_template") or {}) | template_vars(cmd.get("query_template") or {}) \
                    | template_vars(str(cmd.get("path") or ""))
                props = {n: {"type": "string", "description": n} for n in sorted(names)}
                required = sorted(names)
            meta = {k: cmd[k] for k in ("service", "method", "path", "response_mode", "clients", "query_template",
                                        "body_template") if k in cmd}
            tools.append({"name": cmd.get("command"), "title": cmd.get("title") or cmd.get("command"),
                          "description": cmd.get("description", ""),
                          "inputSchema": {"type": "object", "properties": props, "required": required},
                          "annotations": {"readOnlyHint": not is_write(cmd)}, "_meta": {"hestia": meta}})
        return tools

    def call(self, name, arguments=None, *, session_id="", notify_target="", trace_id="", service="",
             origin_client="", timeout=None):
        from hestia_common.tool_call import build_request
        cmd = next((c for c in self._hub.get_commands() or []
                    if c.get("command") == name and (not service or c.get("service") == service)), None)
        if cmd is None:
            return False, f"Unknown tool: {name}"
        ctx = {"session_id": session_id, "notify_target": notify_target, "trace_id": trace_id, "client": origin_client}
        self.calls.append((name, dict(arguments or {}), ctx))
        req = build_request(cmd, arguments or {}, ctx)
        return self._hub.route_to_service(service=req["service"], path=req["path"], method=req["method"],
                                          body=req["body"], query=req["query"], timeout=timeout or 15,
                                          headers=req["headers"])
