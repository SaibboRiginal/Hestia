"""Gemini native tool calling: every Hestia tool schema must reach the API (bench with a real model, 2026-10-30).

The OpenAPI-subset ``parameters`` field broke the whole call: the SDK refused ``contentMediaType`` (voice tools)
and the API refused an array without ``items``. The schemas now go as ``parameters_json_schema``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.universal_agent import UniversalAgent

pytestmark = pytest.mark.unit

_TOOLS = [
    {"name": "voce_impronta_registra", "description": "Registra la voce",
     "parameters": {"type": "object", "properties": {
         "audio": {"type": "string", "contentMediaType": "audio/*"}}}},
    {"name": "calendar_list_events", "description": "Eventi",
     "parameters": {"type": "object", "properties": {"target_providers": {"type": "array"},
                                                     "filters": {"type": "object"}}}},
    {"name": "no_params", "description": "Senza parametri", "parameters": None},
]


class _Models:
    def __init__(self):
        self.config = None

    def generate_content(self, model, contents, config):
        self.config = config
        call = SimpleNamespace(name="calendar_list_events", args={"target_providers": ["google"]})
        return SimpleNamespace(function_calls=[call], candidates=[], text="", usage_metadata=None)


def test_every_schema_is_sent_as_json_schema():
    agent = UniversalAgent(provider="gemini", model_name="gemini-flash-latest")
    models = _Models()
    agent.client = SimpleNamespace(models=models)
    out = agent._ask_with_tools_gemini("Che impegni ho domani?", _TOOLS)
    assert out["tool_call"] == {"name": "calendar_list_events", "params": {"target_providers": ["google"]}}
    decls = models.config.tools[0].function_declarations
    assert [d.name for d in decls] == ["voce_impronta_registra", "calendar_list_events", "no_params"]
    assert all(d.parameters is None for d in decls)
    assert decls[0].parameters_json_schema["properties"]["audio"]["contentMediaType"] == "audio/*"
    assert decls[2].parameters_json_schema == {"type": "object", "properties": {}}


def test_error_payload_is_not_a_success():
    """«{'error': 'niente da spostare'}» with HTTP 200 is not «Fatto» (bench 2026-10-30)."""
    from core.oracle_engine import _error_payload_fails
    assert _error_payload_fails((True, {"error": "niente da spostare"})) == (False, {"error": "niente da spostare"})
    assert _error_payload_fails((True, {"saved": True, "error": ""})) == (True, {"saved": True, "error": ""})
    assert _error_payload_fails((True, {"ok": True, "error": "parziale"}))[0] is True
    assert _error_payload_fails((True, ["a"])) == (True, ["a"])
    assert _error_payload_fails((False, "timeout")) == (False, "timeout")
