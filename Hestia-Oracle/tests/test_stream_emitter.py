"""Unit tests for stream_emitter — all NDJSON event types.

Validates JSON structure, required fields, and content correctness.
No network, no LLM.
"""
from __future__ import annotations

import json
import pytest

from core.services.stream_emitter import (
    emit_status,
    emit_token,
    emit_thinking,
    emit_final,
    emit_question,
    emit_needs_input,
    emit_signal,
    emit_tool_summary,
)


@pytest.mark.unit
class TestEmitStatus:
    def test_status_has_correct_type(self):
        line = emit_status("Testing...")
        data = json.loads(line)
        assert data["type"] == "status"
        assert data["content"] == "Testing..."

    def test_status_with_empty_message(self):
        line = emit_status("")
        data = json.loads(line)
        assert data["type"] == "status"

    def test_status_ends_with_newline(self):
        assert emit_status("test").endswith("\n")


@pytest.mark.unit
class TestEmitToken:
    def test_token_has_correct_type(self):
        line = emit_token("hello")
        data = json.loads(line)
        assert data["type"] == "token"
        assert data["text"] == "hello"

    def test_token_empty_string(self):
        data = json.loads(emit_token(""))
        assert data["text"] == ""


@pytest.mark.unit
class TestEmitThinking:
    def test_thinking_reasoning(self):
        line = emit_thinking(
            action="reasoning",
            content="The user is asking about Roma apartments.",
            turn=1,
            tool_name="scout.search",
        )
        data = json.loads(line)
        assert data["type"] == "thinking"
        assert data["action"] == "reasoning"
        assert data["turn"] == 1
        assert data["tool"] == "scout.search"
        assert "Roma" in data["content"]

    def test_thinking_tool_call(self):
        line = emit_thinking(
            action="tool_call",
            content="Calling scout.search...",
            turn=1,
            tool_name="scout.search",
            metadata={"params_keys": ["query", "city"]},
        )
        data = json.loads(line)
        assert data["type"] == "thinking"
        assert data["action"] == "tool_call"
        assert data["metadata"]["params_keys"] == ["query", "city"]

    def test_thinking_tool_result(self):
        line = emit_thinking(
            action="tool_result",
            content="Found 12 listings.",
            turn=1,
            tool_name="scout.search",
            metadata={
                "ok": True,
                "duration_ms": 350,
                "result_count": 12,
            },
        )
        data = json.loads(line)
        assert data["type"] == "thinking"
        assert data["action"] == "tool_result"
        assert data["metadata"]["ok"] is True
        assert data["metadata"]["duration_ms"] == 350
        assert data["metadata"]["result_count"] == 12

    def test_thinking_without_tool_name(self):
        line = emit_thinking(
            action="reasoning",
            content="Just thinking...",
            turn=0,
        )
        data = json.loads(line)
        assert "tool" not in data  # optional field

    def test_thinking_ends_with_newline(self):
        assert emit_thinking("reasoning", "test", 0).endswith("\n")


@pytest.mark.unit
class TestEmitFinal:
    def test_final_has_correct_type(self):
        line = emit_final("Ecco i risultati", "scout")
        data = json.loads(line)
        assert data["type"] == "final"
        assert data["reply"] == "Ecco i risultati"
        assert data["domain"] == "scout"

    def test_final_default_domain(self):
        data = json.loads(emit_final("Test"))
        assert data["domain"] == "none"


@pytest.mark.unit
class TestEmitQuestion:
    def test_question_has_required_fields(self):
        line = emit_question(
            question_id="q1",
            header="Conferma",
            prompt="Vuoi procedere?",
        )
        data = json.loads(line)
        assert data["type"] == "question"
        assert data["question_id"] == "q1"
        assert data["header"] == "Conferma"
        assert data["kind"] == "free_text"
        assert data["required"] is True

    def test_question_with_options(self):
        line = emit_question(
            question_id="q2",
            header="Scegli",
            prompt="Quale?",
            kind="confirm",
            options=["Si", "No"],
            timeout_sec=30,
            required=False,
        )
        data = json.loads(line)
        assert data["kind"] == "confirm"
        assert data["options"] == ["Si", "No"]
        assert data["timeout_sec"] == 30
        assert data["required"] is False


@pytest.mark.unit
class TestEmitNeedsInput:
    def test_needs_input_format(self):
        line = emit_needs_input(["city", "price"], "Missing required filters")
        data = json.loads(line)
        assert data["type"] == "needs_input"
        assert "city" in data["missing_fields"]
        assert "price" in data["missing_fields"]
        assert "context" in data


@pytest.mark.unit
class TestEmitSignal:
    def test_signal_correct_format(self):
        line = emit_signal(
            event="memory.preference.added",
            message="Preferenza salvata!",
            data={"fact": "User likes Roma", "domain": "scout"},
        )
        data = json.loads(line)
        assert data["type"] == "signal"
        assert data["event"] == "memory.preference.added"
        assert data["content"] == "Preferenza salvata!"
        assert data["data"]["fact"] == "User likes Roma"

    def test_signal_defaults_data_to_empty_dict(self):
        data = json.loads(emit_signal("test.event", "message"))
        assert data["data"] == {}


@pytest.mark.unit
class TestEmitToolSummary:
    def test_tool_summary_format(self):
        tool_log = [
            {
                "tool": "scout.search",
                "params": {"query": "Milano"},
                "ok": True,
                "result_count": 12,
                "result_preview": "[{...}]",
                "duration_ms": 350,
            },
            {
                "tool": "memory.save",
                "params": {"fact": "User prefers Roma"},
                "ok": True,
                "result_count": None,
                "result_preview": "Memory saved",
                "duration_ms": 120,
            },
        ]
        line = emit_tool_summary(tool_log)
        data = json.loads(line)
        assert data["type"] == "signal"
        assert data["event"] == "tool.summary"
        assert len(data["data"]["calls"]) == 2
        assert data["data"]["calls"][0]["tool"] == "scout.search"
        assert data["data"]["calls"][1]["tool"] == "memory.save"

    def test_tool_summary_empty_log(self):
        line = emit_tool_summary([])
        data = json.loads(line)
        assert data["type"] == "signal"
        assert data["data"]["calls"] == []
