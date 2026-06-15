"""Root conftest — shared fixtures available to all test suites.

Provides:
- mock_hub_requests: patches requests.get/post to simulate Hub responses
- mock_archive_requests: patches Archive HTTP calls
- mock_ollama: patches Ollama HTTP to return configurable LLM responses
- FakeOllamaServer: context-manager class for fine-grained per-test Ollama stubs
- make_requests_mock: factory for building Request-level mocks
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# ── Ensure the Shared package is importable from any test ─────────────────
_REPO_ROOT = Path(__file__).parent
_SHARED = _REPO_ROOT / "Hestia-Shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


# ── Fake HTTP response helper ─────────────────────────────────────────────


class FakeResponse:
    """Minimal requests.Response stand-in for mocking."""

    def __init__(
        self,
        json_data: Any = None,
        status_code: int = 200,
        text: str = "",
        content: bytes = b"",
    ) -> None:
        self._json_data = json_data
        self.status_code = status_code
        self.text = text or (json.dumps(json_data)
                             if json_data is not None else "")
        self.content = content or self.text.encode()
        self.ok = 200 <= status_code < 300

    def json(self) -> Any:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if not self.ok:
            from requests import HTTPError
            raise HTTPError(f"HTTP {self.status_code}", response=self)


# ── Reusable fixture factories ────────────────────────────────────────────


def make_hub_response(commands: list[dict] | None = None, services: list[dict] | None = None) -> dict[str, Any]:
    """Minimal Hub discovery response payload."""
    return {
        "commands": commands or [],
        "services": services or [],
        "mapping": {},
    }


def make_memory_response(facts: list[dict] | None = None) -> list[dict]:
    """Minimal Archive memory response."""
    return facts or []


def make_ollama_text_response(text: str) -> dict:
    """Minimal Ollama /api/generate response."""
    return {"response": text, "done": True}


def make_ollama_tool_response(tool_name: str, params: dict) -> dict:
    """Minimal Ollama /api/chat response with a tool call."""
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(params),
                    }
                }
            ],
        },
        "done": True,
    }


def make_ollama_chat_text_response(text: str) -> dict:
    """Minimal Ollama /api/chat text-only response."""
    return {
        "message": {
            "role": "assistant",
            "content": text,
            "tool_calls": [],
        },
        "done": True,
    }


# ── Pytest fixtures ───────────────────────────────────────────────────────


@pytest.fixture()
def fake_response():
    """Factory fixture — returns a FakeResponse constructor."""
    return FakeResponse


@pytest.fixture()
def mock_requests_get(monkeypatch):
    """Patch requests.get globally. Caller sets mock_requests_get.return_value."""
    m = MagicMock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("requests.get", m)
    return m


@pytest.fixture()
def mock_requests_post(monkeypatch):
    """Patch requests.post globally. Caller sets mock_requests_post.return_value."""
    m = MagicMock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("requests.post", m)
    return m


@pytest.fixture()
def mock_requests_session(monkeypatch):
    """Patch requests.Session so no real network calls happen."""
    session = MagicMock()
    session.get.return_value = FakeResponse({"status": "ok"})
    session.post.return_value = FakeResponse({"status": "ok"})
    monkeypatch.setattr("requests.Session", lambda: session)
    return session


@pytest.fixture()
def ollama_text_stub(monkeypatch):
    """Stub Ollama to return a single fixed text response.

    Usage::
        def test_something(ollama_text_stub):
            ollama_text_stub("Hello world")
            # now any requests.post to Ollama returns {"response": "Hello world"}
    """
    state: dict = {"text": ""}

    def _configure(text: str) -> None:
        state["text"] = text

    def _fake_post(url, **kwargs):
        resp_json = make_ollama_text_response(state["text"])
        if "/api/chat" in str(url):
            resp_json = make_ollama_chat_text_response(state["text"])
        return FakeResponse(resp_json)

    monkeypatch.setattr("requests.post", _fake_post)
    return _configure


@pytest.fixture()
def ollama_tool_stub(monkeypatch):
    """Stub Ollama /api/chat to return a tool call, then text on second call.

    Usage::
        def test_something(ollama_tool_stub):
            ollama_tool_stub("calendar_list", {"domain": "chronos"}, final_answer="Done!")
    """
    state: dict = {"tool_name": "", "params": {}, "final_answer": ""}

    def _configure(tool_name: str, params: dict, final_answer: str = "Done!") -> None:
        state["tool_name"] = tool_name
        state["params"] = params
        state["final_answer"] = final_answer

    call_count = {"n": 0}

    def _fake_post(url, **kwargs):
        call_count["n"] += 1
        if "/api/chat" in str(url):
            if call_count["n"] == 1:
                return FakeResponse(make_ollama_tool_response(state["tool_name"], state["params"]))
            return FakeResponse(make_ollama_chat_text_response(state["final_answer"]))
        # /api/generate path
        return FakeResponse(make_ollama_text_response(state["final_answer"]))

    monkeypatch.setattr("requests.post", _fake_post)
    return _configure
