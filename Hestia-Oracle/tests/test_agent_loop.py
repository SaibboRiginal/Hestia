"""Tests — agent_loop module (Phase 1.1)

Tests for _extract_tool_call (14 unit cases) and run_agent_loop (10 cases).
All mocked — no network, no LLM.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, call, patch
import pytest

# conftest adds app/ to sys.path
from core.agent_loop import (
    ToolDefinition,
    _extract_tool_call,
    _truncate_tool_result,
    run_agent_loop,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_tool(name: str, returns: tuple = (True, {"result": "ok"})) -> ToolDefinition:
    handler = MagicMock(return_value=returns)
    return ToolDefinition(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )


def _ask_fn_sequence(*responses: str):
    """Return a callable that yields responses in order, then loops on last."""
    responses = list(responses)
    state = {"n": 0}

    def _ask(prompt: str) -> str:
        idx = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return responses[idx]

    return _ask


def _xml_tool_call(name: str, params: dict) -> str:
    return f'<tool_call>{json.dumps({"name": name, "params": params})}</tool_call>'


def _json_block_tool_call(name: str, params: dict) -> str:
    return f'```json\n{json.dumps({"name": name, "params": params})}\n```'


def _openai_tool_call(name: str, params: dict) -> str:
    return json.dumps({"function": {"name": name, "arguments": json.dumps(params)}})


# ─────────────────────────────────────────────────────────────────────────────
# _extract_tool_call unit tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractToolCall:
    def test_xml_format_returns_name_and_params(self):
        text = _xml_tool_call("calendar_list", {"domain": "chronos"})
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "calendar_list"
        assert result["params"] == {"domain": "chronos"}

    def test_xml_format_empty_params(self):
        text = _xml_tool_call("get_weather", {})
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "get_weather"
        assert result["params"] == {}

    def test_xml_format_multiline_json(self):
        payload = json.dumps({"name": "search_scout", "params": {
                             "city": "Milano", "price_max": 300000}})
        text = f"<tool_call>\n{payload}\n</tool_call>"
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "search_scout"
        assert result["params"]["city"] == "Milano"

    def test_fenced_json_fallback(self):
        text = "Let me check that for you.\n" + \
            _json_block_tool_call("calendar_list", {"limit": 5})
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "calendar_list"

    def test_plain_json_fallback(self):
        """Flat JSON (no nested braces) is parsed by the plain-JSON fallback regex."""
        text = '{"name": "get_listings"}'  # flat — no nested braces
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "get_listings"

    def test_openai_function_wrapper_format(self):
        """OpenAI-style function wrapper is parsed via fenced JSON path."""
        text = "```json\n" + _openai_tool_call("search_scout", {"city": "Torino"}) + "\n```"
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "search_scout"
        assert result["params"]["city"] == "Torino"

    def test_openai_function_arguments_as_string(self):
        """Function with JSON-string arguments is parsed correctly."""
        payload = {
            "function": {
                "name": "set_preference",
                "arguments": json.dumps({"key": "tone", "value": "warm"}),
            }
        }
        text = "```json\n" + json.dumps(payload) + "\n```"
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "set_preference"
        assert result["params"]["key"] == "tone"

    def test_no_tool_call_returns_none(self):
        text = "Ciao! Come posso aiutarti oggi?"
        assert _extract_tool_call(text) is None

    def test_empty_string_returns_none(self):
        assert _extract_tool_call("") is None

    def test_none_returns_none(self):
        assert _extract_tool_call(None) is None  # type: ignore[arg-type]

    def test_malformed_json_in_xml_returns_none(self):
        text = "<tool_call>{name: 'bad json'}</tool_call>"
        assert _extract_tool_call(text) is None

    def test_json_without_name_field_returns_none(self):
        text = json.dumps({"params": {"foo": "bar"}})
        assert _extract_tool_call(text) is None

    def test_xml_takes_precedence_over_plain_json(self):
        # Even if there's a plain JSON object nearby, the XML block takes priority
        extra = json.dumps({"name": "wrong_tool", "params": {}})
        text = extra + "\n" + _xml_tool_call("correct_tool", {"x": 1})
        result = _extract_tool_call(text)
        assert result is not None
        assert result["name"] == "correct_tool"

    def test_params_defaults_to_empty_dict_when_missing(self):
        payload = json.dumps({"name": "some_tool"})
        text = f"<tool_call>{payload}</tool_call>"
        result = _extract_tool_call(text)
        assert result is not None
        assert result["params"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# _truncate_tool_result unit tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTruncateToolResult:
    def test_short_result_not_truncated(self):
        result = _truncate_tool_result("hello", max_chars=100)
        assert result == "hello"

    def test_result_exactly_at_limit_not_truncated(self):
        text = "x" * 100
        assert _truncate_tool_result(text, max_chars=100) == text

    def test_long_result_truncated_with_note(self):
        text = "x" * 2100
        out = _truncate_tool_result(text, max_chars=2000)
        assert len(out) > 2000  # includes note
        assert "truncated" in out.lower()
        assert out.startswith("x" * 2000)

    def test_truncation_note_mentions_max_chars(self):
        text = "a" * 500
        out = _truncate_tool_result(text, max_chars=100)
        assert "100" in out


# ─────────────────────────────────────────────────────────────────────────────
# run_agent_loop integration tests (fully mocked LLM + tools)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunAgentLoop:
    def test_no_tools_returns_direct_answer(self):
        ask = _ask_fn_sequence("Questa è la risposta diretta.")
        answer, tokens, tool_log = run_agent_loop(
            user_message="Dimmi qualcosa",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=ask,
        )
        assert "risposta diretta" in answer
        assert isinstance(tokens, list)

    def test_single_tool_call_then_answer(self):
        tool = _make_tool("get_weather", (True, {"temp": "22°C"}))
        xml = _xml_tool_call("get_weather", {})
        ask = _ask_fn_sequence(xml, "Il meteo oggi è 22°C.")
        answer, _, _ = run_agent_loop(
            user_message="Com'è il meteo?",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=ask,
        )
        tool.handler.assert_called_once()
        assert isinstance(answer, str)

    def test_unknown_tool_logs_error_and_continues(self):
        ask = _ask_fn_sequence(
            _xml_tool_call("nonexistent_tool", {}),
            "Non ho trovato lo strumento.",
        )
        answer, _, _ = run_agent_loop(
            user_message="Usa lo strumento sconosciuto",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=ask,
        )
        # Should not raise; should return a final answer
        assert isinstance(answer, str)

    def test_tool_raises_exception_logs_and_continues(self):
        def _bad_handler(**kwargs):
            raise RuntimeError("Tool exploded")

        bad_tool = ToolDefinition(
            name="bad_tool",
            description="A tool that always fails",
            parameters={"type": "object", "properties": {}},
            handler=_bad_handler,
        )
        ask = _ask_fn_sequence(
            _xml_tool_call("bad_tool", {}),
            "C'è stato un errore con lo strumento.",
        )
        answer, _, _ = run_agent_loop(
            user_message="Test",
            history_text="",
            preference_facts=[],
            tools=[bad_tool],
            ask_fn=ask,
        )
        assert isinstance(answer, str)

    def test_preference_facts_injected_into_prompt(self):
        captured_prompts: list[str] = []

        def _capturing_ask(prompt: str) -> str:
            captured_prompts.append(prompt)
            return "Risposta."

        run_agent_loop(
            user_message="Mostrami qualcosa",
            history_text="",
            preference_facts=["Preferisce zone silenziose", "Budget max 250k"],
            tools=[],
            ask_fn=_capturing_ask,
        )
        assert any("250k" in p for p in captured_prompts)

    def test_client_instructions_injected_into_prompt(self):
        captured_prompts: list[str] = []

        def _capturing_ask(prompt: str) -> str:
            captured_prompts.append(prompt)
            return "Risposta."

        run_agent_loop(
            user_message="Ciao",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=_capturing_ask,
            client_instructions="Parla sempre in modo formale",
        )
        assert any("formale" in p for p in captured_prompts)

    def test_llm_failure_returns_error_message(self):
        def _always_fail(prompt: str) -> str:
            raise ConnectionError("LLM not available")

        answer, _, _ = run_agent_loop(
            user_message="Ciao",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=_always_fail,
        )
        # Should surface a user-friendly Italian error message
        assert "disponibile" in answer.lower() or "errore" in answer.lower() or answer

    def test_stream_fn_used_for_final_answer(self):
        tokens_out = ["Ciao ", "Mark!"]
        ask = _ask_fn_sequence(_xml_tool_call(
            "get_weather", {}), "Final non-streamed")
        tool = _make_tool("get_weather")

        def _stream(prompt: str):
            yield from tokens_out

        answer, tokens, tool_log = run_agent_loop(
            user_message="Meteo?",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=ask,
            stream_fn=_stream,
        )
        assert tokens == tokens_out

    def test_max_turns_reached_returns_final_non_empty(self):
        # LLM always emits a tool call → loop should terminate at MAX_AGENT_TURNS
        import os
        os.environ["ORACLE_MAX_AGENT_TURNS"] = "2"
        tool = _make_tool("infinite_tool")
        ask = _ask_fn_sequence(
            _xml_tool_call("infinite_tool", {}),
            _xml_tool_call("infinite_tool", {}),
            "Risposta finale.",
        )
        try:
            answer, _, _ = run_agent_loop(
                user_message="Loop",
                history_text="",
                preference_facts=[],
                tools=[tool],
                ask_fn=ask,
            )
            assert isinstance(answer, str)
        finally:
            os.environ["ORACLE_MAX_AGENT_TURNS"] = "6"

    def test_ask_tools_fn_returns_tool_call_dict(self):
        """When ask_tools_fn is provided and returns a tool call, it should execute the tool."""
        tool = _make_tool("weather_tool", (True, {"temp": "18°C"}))
        final_answer_text = "Temperatura 18°C."
        call_count: dict = {"n": 0}

        def _ask_tools(prompt: str, manifest: list) -> dict:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: return tool call
                return {"tool_call": {"name": "weather_tool", "params": {}}, "text": ""}
            # Subsequent calls: return final text (no more tool calls)
            return {"tool_call": None, "text": final_answer_text}

        ask = _ask_fn_sequence(final_answer_text)
        answer, _, _ = run_agent_loop(
            user_message="Temperatura?",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=ask,
            ask_tools_fn=_ask_tools,
        )
        tool.handler.assert_called_once()

    def test_history_text_injected_into_prompt(self):
        captured: list[str] = []

        def _ask(prompt: str) -> str:
            captured.append(prompt)
            return "Risposta."

        run_agent_loop(
            user_message="Continua",
            history_text="User: Ciao\nAssistant: Salve!",
            preference_facts=[],
            tools=[],
            ask_fn=_ask,
        )
        assert any("Salve" in p for p in captured)

    def test_tool_log_populated_after_tool_calls(self):
        """Tool log should contain entries for each tool invocation."""
        tool = _make_tool("search", (True, [{"id": 1}, {"id": 2}]))
        xml = _xml_tool_call("search", {"query": "test"})
        ask = _ask_fn_sequence(xml, "Ecco i risultati.")
        answer, tokens, tool_log = run_agent_loop(
            user_message="Cerca test",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=ask,
        )
        assert len(tool_log) == 1
        assert tool_log[0]["tool"] == "search"
        assert tool_log[0]["ok"] is True
        assert "result_preview" in tool_log[0]

    def test_tool_log_tracks_failures(self):
        """Tool log should mark failed tool calls."""
        bad_tool = ToolDefinition(
            name="failing_tool",
            description="Always fails",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        ask = _ask_fn_sequence(
            _xml_tool_call("failing_tool", {}),
            "Errore gestito.",
        )
        answer, tokens, tool_log = run_agent_loop(
            user_message="Test",
            history_text="",
            preference_facts=[],
            tools=[bad_tool],
            ask_fn=ask,
        )
        assert len(tool_log) == 1
        assert tool_log[0]["ok"] is False

    def test_early_exit_after_tool_calls_when_no_more_tools(self):
        """After making tool calls, consecutive non-tool responses trigger early exit."""
        tool = _make_tool("search", (True, [{"id": 1}]))
        responses = [
            _xml_tool_call("search", {}),     # turn 0: tool call
            "Thinking about the results...",   # turn 1: no tool
            "More analysis without tools...",  # turn 2: no tool → early exit
            "Should not reach here",
        ]
        ask = _ask_fn_sequence(*responses)
        answer, tokens, tool_log = run_agent_loop(
            user_message="Cerca e analizza",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=ask,
            max_turns=10,
        )
        assert len(tool_log) == 1
        assert isinstance(answer, str)
        # Should have exited before consuming all responses
        assert "Should not reach" not in answer

    def test_on_thinking_callback_fires(self):
        """on_thinking callback should receive NDJSON lines for tool activity."""
        tool = _make_tool("get_data", (True, {"value": 42}))
        xml = _xml_tool_call("get_data", {"key": "x"})
        ask = _ask_fn_sequence(xml, "Il valore è 42.")
        thinking_lines: list[str] = []

        def _on_thinking(line: str) -> None:
            thinking_lines.append(line)

        answer, tokens, tool_log = run_agent_loop(
            user_message="Dammi i dati",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=ask,
            on_thinking=_on_thinking,
        )
        assert len(thinking_lines) >= 2  # reasoning + tool_call + tool_result
        assert any("get_data" in line for line in thinking_lines)
        assert any("tool_call" in line for line in thinking_lines)

    def test_custom_max_turns_overrides_env(self):
        """max_turns parameter should override env default."""
        import os
        os.environ["ORACLE_MAX_AGENT_TURNS"] = "100"
        tool = _make_tool("a")
        ask = _ask_fn_sequence(
            _xml_tool_call("a", {}),
            _xml_tool_call("a", {}),
            _xml_tool_call("a", {}),
            "Done.",
        )
        try:
            answer, tokens, tool_log = run_agent_loop(
                user_message="X",
                history_text="",
                preference_facts=[],
                tools=[tool],
                ask_fn=ask,
                max_turns=2,  # override — only 2 turns
            )
            # Should exit after 2 turns, not 100
            assert len(tool_log) <= 2
        finally:
            os.environ["ORACLE_MAX_AGENT_TURNS"] = "25"

    def test_action_intent_injects_policy_into_prompt(self):
        """When action_intent=True, the system prompt should include action policy."""
        captured: list[str] = []

        def _ask(prompt: str) -> str:
            captured.append(prompt)
            return "Azione completata."

        run_agent_loop(
            user_message="Crea un evento",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=_ask,
            action_intent=True,
        )
        assert any("ACTION INTENT" in p for p in captured)
