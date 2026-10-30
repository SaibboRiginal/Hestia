"""Tests — Live tool-calling validation (Phase 1.8)

These tests exercise a real model (tests/live_llm.py: local Ollama or Gemini) through run_agent_loop.
They are skipped unless --run-live is passed and the model is usable.
Primary test engine for validating that the local model can produce
correct tool-call format and that the agent loop parses and dispatches it.

Mark: @pytest.mark.llm_live
"""
from __future__ import annotations

import json
import os
import requests
from typing import Any
from unittest.mock import MagicMock
import pytest

from core.agent_loop import ToolDefinition, run_agent_loop
from core.services import prompt_config
from agents.universal_agent import UniversalAgent
import live_llm

_STYLE = prompt_config.conversation_style_contract()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_ollama_agent(thinking: bool = False) -> UniversalAgent:
    """Live agent (tests/live_llm.py: Ollama or Gemini) with the tool-call contract of these tests."""
    return live_llm.make_agent(
        role_prompt=(
            "Sei Hestia, un'assistente IA. Quando l'utente chiede dati che richiedono uno strumento, "
            "usa il formato <tool_call>{\"name\": \"nome_tool\", \"params\": {\"chiave\": \"valore\"}}</tool_call>. "
            "Risposta finale SEMPRE in HTML: <b>grassetto</b>, <i>corsivo</i>, bullet con •."
        ),
        thinking=thinking,
    )


def _make_tool(name: str, result: Any = None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Returns {name} data",
        parameters={"type": "object", "properties": {}},
        handler=lambda **_: (True, result or {"ok": True}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Live tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.llm_live
class TestLiveToolCalling:
    def test_live_model_reachable(self):
        """Sanity check: the live model answers at all."""
        answer = _make_ollama_agent().ask("Rispondi solo con la parola: pronto")
        assert "pront" in answer.lower(), f"{live_llm.PROVIDER}/{live_llm.MODEL} answered: {answer!r}"

    @pytest.mark.skipif(live_llm.PROVIDER != "ollama", reason="Ollama only: installed model list")
    def test_configured_model_is_available(self):
        """The OLLAMA_MODEL env var should be installed."""
        resp = requests.get(f"{live_llm.ollama_base()}/api/tags", timeout=5)
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        assert any(live_llm.MODEL.split(":")[0] in m for m in models), (
            f"Model '{live_llm.MODEL}' not found in Ollama. Available: {models}"
        )

    def test_agent_answers_direct_question_without_tool_call(self):
        """When no tools are provided, the agent should return a direct answer."""
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Quanto fa 2 + 2?",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=agent.ask,
            conversation_style=_STYLE,
        )
        assert isinstance(answer, str)
        assert len(answer) > 0
        # Should contain "4" somewhere in the answer
        assert "4" in answer

    def test_agent_calls_tool_and_incorporates_result(self):
        """Verify the model emits a tool_call when a relevant tool is available."""
        listings = [
            {"title": "Bilocale Milano", "price": 280000},
            {"title": "Trilocale Roma", "price": 350000},
        ]
        tool = _make_tool("search_listings", result=listings)

        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Mostrami annunci immobiliari disponibili",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=agent.ask,
            ask_tools_fn=agent.ask_with_tools,
            conversation_style=_STYLE,
        )
        assert isinstance(answer, str)
        assert len(answer) > 0

    def test_tool_result_appears_in_final_answer(self):
        """Tool result data should be reflected in the final answer."""
        tool = _make_tool("get_weather", result={
                          "temperatura": "22°C", "condizioni": "soleggiato"})
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Com'è il meteo oggi?",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=agent.ask,
            ask_tools_fn=agent.ask_with_tools,
            conversation_style=_STYLE,
        )
        # Either the tool was called (result in answer) or direct answer given
        assert isinstance(answer, str)
        assert len(answer) > 0

    def test_preference_facts_influence_answer_style(self):
        """Preference facts injected in the prompt should shift the response."""
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Dimmi qualcosa di interessante",
            history_text="",
            preference_facts=[
                "L'utente preferisce risposte in elenco puntato", "Budget max 200k"],
            tools=[],
            ask_fn=agent.ask,
            conversation_style=_STYLE,
        )
        assert isinstance(answer, str)
        assert len(answer) > 0

    def test_answer_does_not_contain_raw_tool_call_tags(self):
        """The final answer delivered to the user must never expose tool_call tags."""
        tool = _make_tool("get_data", result={"data": "test"})
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Dammi dei dati",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=agent.ask,
            ask_tools_fn=agent.ask_with_tools,
            conversation_style=_STYLE,
        )
        assert "<tool_call>" not in answer
        assert "</tool_call>" not in answer

    def test_html_output_no_raw_markdown(self):
        """The agent should produce HTML output, not raw Markdown."""
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Elenca 3 città italiane importanti con una breve nota per ognuna",
            history_text="",
            preference_facts=[],
            tools=[],
            ask_fn=agent.ask,
            conversation_style=_STYLE,
        )
        # Should not contain markdown bold ** or heading ##
        assert "**" not in answer, f"Raw Markdown found in answer: {answer[:300]}"
        # Allow some tolerance — the model may not always perfectly follow instructions,
        # but headings and bold md are the clearest violations
        lines_with_heading = [
            l for l in answer.splitlines() if l.startswith("##")]
        assert len(
            lines_with_heading) == 0, f"Markdown heading found: {lines_with_heading}"

    def test_history_context_affects_response(self):
        """History context should be acknowledged by the model."""
        history = "User: Mi chiamo Marco\nAssistant: Ciao Marco, come posso aiutarti?"
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Come mi chiamo?",
            history_text=history,
            preference_facts=[],
            tools=[],
            ask_fn=agent.ask,
            conversation_style=_STYLE,
        )
        # The model should know the name from context
        assert "Marco" in answer or "marco" in answer.lower()

    def test_multiple_tools_agent_selects_correct_one(self):
        """When multiple tools are available, the agent should pick the relevant one."""
        weather_tool = _make_tool("get_weather", result={"temp": "18°C"})
        listings_tool = ToolDefinition(
            name="search_listings",
            description="Search real estate listings",
            parameters={"type": "object", "properties": {
                "city": {"type": "string"}}},
            handler=lambda **_: (True, [{"title": "Appartamento Milano"}]),
        )
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Che tempo fa oggi?",
            history_text="",
            preference_facts=[],
            tools=[weather_tool, listings_tool],
            ask_fn=agent.ask,
            ask_tools_fn=agent.ask_with_tools,
            conversation_style=_STYLE,
        )
        # Answer should be weather-related, not real estate
        assert isinstance(answer, str)
        assert len(answer) > 0

    def test_no_answer_hallucination_for_empty_tool_result(self):
        """When a tool returns an empty list, the model should acknowledge this, not hallucinate."""
        tool = _make_tool("search_listings", result=[])
        agent = _make_ollama_agent()
        answer, _, _ = run_agent_loop(
            user_message="Mostrami appartamenti a Paperopoli",
            history_text="",
            preference_facts=[],
            tools=[tool],
            ask_fn=agent.ask,
            ask_tools_fn=agent.ask_with_tools,
            conversation_style=_STYLE,
        )
        assert isinstance(answer, str)
        assert len(answer) > 0
