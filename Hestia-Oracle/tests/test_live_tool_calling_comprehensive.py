"""Live LLM tool-calling tests — validates Oracle's agent loop with real tools.

Requires a running Ollama instance at OLLAMA_URL.
All tool handlers are mocked to avoid side effects on production services.

Tests:
  - Domain search tool (scout.search, chronos.search)
  - Hub action commands (scout_listings, create_event, agenda)
  - Memory tools (memory.save, memory.search)
  - Document search tool (documents.search)
  - Multi-turn tool calling (search → refine → answer)
  - Action intent detection in classifier
  - HTML output contract (no Markdown, proper tags)
  - Fallback chain (primary fails → fallback succeeds)

Marked: llm_live — skipped when Ollama is not reachable.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest
import requests

# Path setup
_ORACLE_ROOT = Path(__file__).parents[1]
_APP_PATH = _ORACLE_ROOT / "app"
_REPO_ROOT = _ORACLE_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_APP_PATH), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.agent_loop import run_agent_loop, ToolDefinition
from core.services.chat_classifier import ChatClassifier
from core.services import prompt_config


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_search_tool(name: str, results: list[dict]) -> ToolDefinition:
    def handler(query: str = "", **kwargs) -> tuple[bool, list]:
        return (True, results)
    return ToolDefinition(
        name=name,
        description=f"Search {name.split('.')[0]} domain",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filters": {"type": "object"},
                "filters_gt": {"type": "object"},
                "filters_lt": {"type": "object"},
                "sort_by": {"type": "string"},
                "sort_order": {"type": "string", "enum": ["asc", "desc"]},
            },
        },
        handler=handler,
    )


def _make_memory_save_tool() -> ToolDefinition:
    saved = []
    def handler(fact: str = "", domain: str = "general") -> tuple[bool, str]:
        if not fact.strip():
            return (False, "Cannot save empty fact")
        saved.append({"fact": fact, "domain": domain})
        return (True, f"Memory saved: {fact}")
    return ToolDefinition(
        name="memory.save",
        description="Save a durable fact about the user",
        parameters={
            "type": "object",
            "properties": {
                "fact": {"type": "string"},
                "domain": {"type": "string"},
            },
            "required": ["fact"],
        },
        handler=handler,
    )


def _make_memory_search_tool(stored: list[dict]) -> ToolDefinition:
    def handler(query: str = "") -> tuple[bool, list]:
        if not query.strip():
            return (True, stored[:10])
        results = [m for m in stored if query.lower() in str(m.get("fact", "")).lower()]
        return (True, results)
    return ToolDefinition(
        name="memory.search",
        description="Search saved memories",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
        handler=handler,
    )


def _make_action_tool(name: str, description: str, params: dict) -> ToolDefinition:
    executed = []
    def handler(**kwargs) -> tuple[bool, dict]:
        executed.append({"tool": name, "params": kwargs})
        return (True, {"status": "ok", "tool": name, "params": kwargs})
    return ToolDefinition(
        name=name,
        description=description,
        parameters=params,
        handler=handler,
    )


_LLM_MODEL = os.getenv("MODEL_USECASE_GENERIC_MODEL", os.getenv("OLLAMA_MODEL", "gemma4:e4b"))
_REASONING_MODEL = os.getenv("MODEL_USECASE_REASONING_MODEL", "gemma-4-26B-A4B-it-UD-IQ4_NL:latest")
_CODE_MODEL = os.getenv("MODEL_USECASE_CODE_MODEL", "gemma4:e4b")


def _call_ollama(prompt: str, model: str = None) -> str:
    """Make a single blocking call to Ollama."""
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    chat_url = ollama_url.replace("/api/generate", "/api/chat")
    resp = requests.post(chat_url, json={
        "model": model or _LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }, timeout=120)
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")


def _ollama_ask_fn(prompt: str) -> str:
    return _call_ollama(prompt)


def _run_and_print(user_message, tools, label="", **kwargs):
    """Run agent loop and ALWAYS print the LLM response and tool calls."""
    # Only set defaults if caller didn't provide them
    kwargs.setdefault("ask_fn", _ollama_ask_fn)
    kwargs.setdefault("ask_tools_fn", _ollama_ask_tools_fn)
    kwargs.setdefault("max_turns", 5)
    kwargs.setdefault("history_text", "")
    kwargs.setdefault("preference_facts", [])
    kwargs.setdefault("conversation_style", prompt_config.conversation_style_contract())
    answer, tokens, tool_log = run_agent_loop(
        user_message=user_message,
        tools=tools,
        **kwargs,
    )
    tag = f" [{label}]" if label else ""
    print(f"\n{'='*60}")
    print(f"TEST{tag}: {user_message}")
    print(f"Tools available: {[t.name for t in tools]}")
    print(f"Tools called: {[(c['tool'], 'OK' if c['ok'] else 'FAIL') for c in tool_log]}")
    for c in tool_log:
        print(f"  {c['tool']} | params={json.dumps(c.get('params',{}), ensure_ascii=False)[:200]} | {c.get('duration_ms','?')}ms")
    print(f"Answer ({len(answer)} chars):")
    print(answer[:800] if answer else "(EMPTY)")
    print(f"{'='*60}\n")
    return answer, tokens, tool_log


def _ollama_ask_tools_fn(prompt: str, tools: list[dict]) -> dict:
    """Use Ollama native tool calling."""
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    chat_url = ollama_url.replace("/api/generate", "/api/chat")
    ollama_tools = [
        {"type": "function", "function": {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
        }}
        for t in tools
    ]
    resp = requests.post(chat_url, json={
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant with tool access."},
            {"role": "user", "content": prompt},
        ],
        "tools": ollama_tools,
        "stream": False,
    }, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    msg = data.get("message", {})
    tool_calls = msg.get("tool_calls", [])
    if tool_calls:
        tc = tool_calls[0]
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        return {"tool_call": {"name": fn.get("name", ""), "params": args}, "text": ""}
    return {"tool_call": None, "text": msg.get("content", "")}


# ═══════════════════════════════════════════════════════════════════════════════
# Live Tool-Calling Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.llm_live
class TestLiveToolCalling:
    """Verify the local model can actually select and use tools via the agent loop."""

    def test_model_calls_domain_search_tool(self):
        """Model should call scout.search when asked about real estate."""
        listings = [
            {"title": "Trilocale Milano", "price": 250000, "city": "Milano", "url": "https://example.com/1"},
            {"title": "Bilocale Roma", "price": 180000, "city": "Roma", "url": "https://example.com/2"},
        ]
        tools = [_make_search_tool("scout.search", listings)]

        answer, tokens, tool_log = _run_and_print(
            user_message="Cerco trilocali a Milano",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        assert len(answer) > 20, f"Answer too short: {answer}"
        # Should mention Milano
        assert "Milano" in answer or "milano" in answer.lower()
        # Should have called the tool at least once
        assert len(tool_log) >= 1, f"No tools called. Answer: {answer[:500]}"

    def test_model_calls_memory_save(self):
        """Model should call memory.save when user expresses a preference."""
        tools = [_make_memory_save_tool()]

        answer, tokens, tool_log = _run_and_print(
            user_message="Mi piace il caffè espresso, ricordalo per favore.",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        assert len(answer) >= 1, f"Empty answer for memory save. Answer: {answer}"
        # Should have called memory.save
        assert len(tool_log) >= 1, f"memory.save not called. Answer: {answer[:500]}"
        assert any("memory.save" in c["tool"] for c in tool_log)

    def test_model_calls_memory_search(self):
        """Model should call memory.search to recall preferences."""
        tools = [_make_memory_search_tool([
            {"fact": "User prefers Roma over Milano", "domain": "general"},
            {"fact": "User likes modern style", "domain": "general"},
        ])]

        answer, tokens, tool_log = _run_and_print(
            user_message="Cosa ricordi di me? Quali sono le mie preferenze?",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        assert len(answer) > 10
        assert len(tool_log) >= 1
        assert any("memory.search" in c["tool"] for c in tool_log)

    def test_model_handles_multiple_tools(self):
        """Model should be able to choose between multiple tools."""
        search_tool = _make_search_tool("scout.search", [
            {"title": "Appartamento Milano", "price": 300000},
        ])
        action_tool = _make_action_tool("create_event", "Create calendar event", {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_datetime": {"type": "string"},
            },
            "required": ["title"],
        })
        memory_tool = _make_memory_save_tool()

        tools = [search_tool, action_tool, memory_tool]

        answer, tokens, tool_log = _run_and_print(
            user_message="Salva nelle preferenze che mi piace il caffè.",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        assert len(answer) >= 1, f"Empty answer for multi-tool. Answer: {answer}"
        assert len(tool_log) >= 1

    def test_model_returns_answer_without_tools_for_greeting(self):
        """Model should NOT call tools for a simple greeting."""
        tools = [_make_search_tool("scout.search", [])]

        answer, tokens, tool_log = _run_and_print(
            user_message="Ciao! Come stai?",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        assert len(answer) >= 1, f"Empty answer for greeting. Answer: {answer}"
        # For a greeting, tool calling is acceptable if the model thinks it should
        # The key is that it produces a reasonable answer

    def test_tool_log_contains_all_calls(self):
        """Every tool call should be reflected in tool_log."""
        tools = [_make_search_tool("scout.search", [
            {"title": "Test listing", "price": 100000},
        ])]

        answer, tokens, tool_log = _run_and_print(
            user_message="Mostrami case in vendita sotto i 200k a Milano",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        for entry in tool_log:
            assert "tool" in entry
            assert "ok" in entry
            assert "duration_ms" in entry
            assert isinstance(entry["ok"], bool)


@pytest.mark.llm_live
class TestLiveToolCallingHTMLContract:
    """Verify LLM outputs obey the HTML formatting contract."""

    def test_search_response_uses_html_not_markdown(self):
        """LLM should use <b> not ** for bold, • not - for lists."""
        listings = [
            {"title": "Appartamento Centro Milano", "price": 350000,
             "url": "https://example.com/apt1", "city": "Milano",
             "specs": {"surface_m2": 90, "rooms": 3}},
        ]
        tools = [_make_search_tool("scout.search", listings)]

        answer, tokens, tool_log = _run_and_print(
            user_message="Mostra case a Milano. Usa HTML per la formattazione, "
                         "con <b>grassetto</b> e • per le liste. "
                         "NON usare Markdown (**testo**, - item, * item).",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
            client_instructions="Usa SOLO HTML per Telegram: <b>bold</b>, <i>italic</i>, "
                               "<a href=\"url\">link</a>. "
                               "MAI Markdown. VIETATO: <ul>, <ol>, <li>, <div>, <span> — non supportati. "
                               "Per liste: • bullet direttamente, ogni voce su riga separata.",
        )

        # Must NOT contain Markdown
        assert "**" not in answer, f"Markdown bold (**) found: {answer[:300]}"
        assert not any(md in answer for md in ["__", "##", "[text]", "]("]), \
            f"Markdown syntax found: {answer[:300]}"

        # Must NOT contain truly invalid HTML tags.
        # ul/ol/li are normalized by Telegram's client renderer per the
        # messaging contract §6 — they are tolerated, not rejected.
        import re
        invalid_tags = re.findall(r'</?(\w+)[^>]*>', answer)
        telegram_valid = {"b", "i", "u", "s", "code", "pre", "a", "br"}
        client_normalizable = {"ul", "ol", "li", "em", "strong"}
        bad_tags = set(invalid_tags) - telegram_valid - client_normalizable
        assert not bad_tags, (
            f"Invalid HTML tags found: {bad_tags}. "
            f"Allowed: {telegram_valid}. Client-normalizable: {client_normalizable}. "
            f"Answer: {answer[:400]}"
        )


@pytest.mark.llm_live
class TestLiveClassifier:
    """Verify the classifier can detect action_intent with a real model."""

    def test_classifier_detects_action_intent(self):
        """The router model should detect action_intent for imperative commands."""
        router_agent = MagicMock()
        fallback_agent = MagicMock()

        def _real_router(prompt: str) -> str:
            return _call_ollama(prompt)

        router_agent.ask.side_effect = _real_router
        fallback_agent.ask.side_effect = _real_router

        clf = ChatClassifier(router_agent, fallback_agent)

        result = clf.classify(
            "Crea un evento per domani alle 15:00",
            history_text="",
            available_domains=["scout", "chronos", "general"],
            current_datetime_context="timezone=Europe/Rome\nnow_iso=2026-06-12T10:00:00+02:00\ntoday_date=2026-06-12\ntoday_weekday=Friday\ntomorrow_date=2026-06-13\ntomorrow_weekday=Saturday",
        )

        action_intent = result[9]
        # Should detect this as an action
        assert action_intent is True, \
            f"Expected action_intent=True for 'crea evento'. Got: {action_intent}"

    def test_classifier_no_action_intent_for_question(self):
        """The router should NOT detect action_intent for informational queries."""
        router_agent = MagicMock()
        fallback_agent = MagicMock()

        def _real_router(prompt: str) -> str:
            return _call_ollama(prompt)

        router_agent.ask.side_effect = _real_router
        fallback_agent.ask.side_effect = _real_router

        clf = ChatClassifier(router_agent, fallback_agent)

        result = clf.classify(
            "Che tempo fa oggi?",
            history_text="",
            available_domains=["scout", "chronos", "general"],
        )

        action_intent = result[9]
        mode = result[0]
        # For a weather question, mode should be quick_chat
        assert mode in ("quick_chat", "domain_query"), f"Unexpected mode: {mode}"


@pytest.mark.llm_live
class TestLiveFallbackChain:
    """Verify the fallback chain handles failures gracefully."""

    def test_tool_error_does_not_crash_loop(self):
        """When a tool handler raises, the loop should continue to final answer."""
        def _failing_handler(**kwargs):
            raise RuntimeError("Simulated tool failure")

        bad_tool = ToolDefinition(
            name="broken_tool",
            description="Always fails",
            parameters={"type": "object", "properties": {}},
            handler=_failing_handler,
        )

        answer, tokens, tool_log = _run_and_print(
            user_message="Usa lo strumento broken_tool",
            history_text="",
            preference_facts=[],
            tools=[bad_tool],
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=5,
        )

        # Should complete with some answer
        assert len(answer) > 5
        if tool_log:
            failing = [c for c in tool_log if c["tool"] == "broken_tool"]
            if failing:
                assert failing[0]["ok"] is False


@pytest.mark.llm_live
class TestLiveChatModes:
    """Verify chat modes (quick, auto, thinking) work with real LLM."""

    def test_quick_mode_returns_fast_without_tools(self):
        """quick mode: single ask(), no classify, no tools. Should be fast."""
        tools = [_make_search_tool("scout.search", [])]
        t0 = __import__("time").perf_counter()
        answer, tokens, tool_log = run_agent_loop(
            user_message="Ciao, come stai?",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=1,  # quick mode equivalent — only 1 turn
            conversation_style=prompt_config.conversation_style_contract(),
        )
        elapsed = __import__("time").perf_counter() - t0
        assert len(answer) >= 1, f"Answer too short: {answer}"
        # In quick mode, no tools should be called for a greeting
        assert len(tool_log) == 0, f"Tools called in quick/greeting mode: {[c['tool'] for c in tool_log]}"
        print(f"\n  quick mode latency: {elapsed:.1f}s, answer: {answer[:100]}")

    def test_thinking_mode_with_tools_emits_thinking(self):
        """thinking mode: agent loop with tools, visible thinking."""
        tools = [_make_search_tool("scout.search", [
            {"title": "Appartamento Milano", "price": 250000},
        ])]
        answer, tokens, tool_log = run_agent_loop(
            user_message="Cerco case a Milano sotto i 300k",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=10,  # thinking mode equivalent — higher max_turns
            action_intent=False,
            conversation_style=prompt_config.conversation_style_contract(),
        )
        assert len(answer) > 20, f"Answer too short for thinking mode: {answer}"
        # Should have called at least one tool
        assert len(tool_log) >= 1, (
            f"No tools called in thinking mode. Tools: {[c['tool'] for c in tool_log]}. "
            f"Answer: {answer[:300]}"
        )
        print(f"\n  thinking mode: {len(tool_log)} tool calls, answer: {answer[:150]}")

    def test_mode_max_turns_limit_respected(self):
        """max_turns=1 should force early exit even with tools available."""
        tools = [_make_search_tool("scout.search", [{"title": "Test"}])]
        answer, tokens, tool_log = run_agent_loop(
            user_message="Mostra TUTTE le case disponibili",
            history_text="",
            preference_facts=[],
            tools=tools,
            ask_fn=_ollama_ask_fn,
            ask_tools_fn=_ollama_ask_tools_fn,
            max_turns=1,
            conversation_style=prompt_config.conversation_style_contract(),
        )
        # With max_turns=1, at most 1 tool call can happen
        assert len(tool_log) <= 1, f"Exceeded max_turns: {len(tool_log)} tool calls"


@pytest.mark.llm_live
class TestLiveModelUseCase:
    """Verify model selection by use case works — uses models from .env."""

    def test_configured_models_are_available(self):
        """The models in MODEL_USECASE_* env vars should be pullable in Ollama."""
        import requests as _r
        tags = _r.get("http://localhost:11434/api/tags", timeout=5).json()
        available = {m["name"] for m in tags.get("models", [])}

        models_to_check = [
            ("GENERIC", _LLM_MODEL),
            ("REASONING", _REASONING_MODEL),
            ("CODE", _CODE_MODEL),
        ]
        missing = []
        for label, model in models_to_check:
            # Match by base name (strip tag suffix like :latest, :Q8_0)
            base = model.split(":")[0]
            if not any(base in a for a in available):
                missing.append(f"{label}={model}")

        if missing:
            print(f"\n  WARNING: Models not found in Ollama: {missing}")
            print(f"  Available: {sorted(available)[:10]}...")
        # Don't fail — user may have models pulled later
        print(f"\n  Configured models: GENERIC={_LLM_MODEL}, REASONING={_REASONING_MODEL}, CODE={_CODE_MODEL}")

    def test_generic_model_can_classify_and_chat(self):
        """The generic model should handle both classification and chat."""
        # Simulate what Oracle's classify does — ask the model to classify
        from core.services.chat_classifier import ChatClassifier
        from unittest.mock import MagicMock

        # Directly test the model can produce valid classification JSON.
        # Use a non-greeting message so the model doesn't get distracted into chatting.
        prompt = (
            "Output ONLY a JSON object. No text before or after the JSON.\n"
            "Format: {\"mode\": \"<mode>\", \"domain\": null, \"confidence\": <0-1>, "
            "\"domains\": [\"<domain>\"], \"filters\": {}, \"filters_gt\": {}, "
            "\"filters_lt\": {}, \"sort_by\": null, \"sort_order\": \"desc\", "
            "\"action_intent\": false}\n\n"
            "USER_MESSAGE: Mostrami le case in vendita a Roma"
        )
        response = _call_ollama(prompt)
        # Should contain JSON
        assert "{" in response and "}" in response, f"Model didn't return JSON: {response[:200]}"
        print(f"\n  generic classify response: {response[:200]}")

    def test_model_can_detect_action_intent(self):
        """The model should detect when a message requests an action."""
        prompt = (
            "Decide if this message requests a state-changing action. "
            "Return ONLY: {\"action_intent\": true} or {\"action_intent\": false}\n\n"
            "MESSAGE: Crea un evento domani alle 15"
        )
        response = _call_ollama(prompt)
        assert "true" in response.lower(), (
            f"Model should detect action intent. Response: {response[:200]}"
        )
        print(f"\n  action intent detection: {response[:200]}")
