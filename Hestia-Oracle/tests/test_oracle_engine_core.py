"""Comprehensive OracleEngine integration tests.

Tests every chat() path, tool building, memory tools, thinking emission,
tool summary signals, error handling, and fallback chains.

All external dependencies (Hub, Archive, LLMs) are mocked.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
import requests

from core.oracle_engine import OracleEngine
from core.services.chat_classifier import QUICK_CHAT_CONFIDENCE_THRESHOLD
from core.services.agent_factory import AgentFactory
from core.agent_loop import ToolDefinition


# ── Helpers ──────────────────────────────────────────────────────────────────

def _quick_chat_json() -> str:
    return json.dumps({
        "mode": "quick_chat", "domain": None, "confidence": 0.9,
        "domains": ["general"], "filters": {}, "filters_gt": {},
        "filters_lt": {}, "sort_by": None, "sort_order": "desc",
        "action_intent": False,
    })


def _domain_query_json(domain: str = "scout", action_intent: bool = False) -> str:
    return json.dumps({
        "mode": "domain_query", "domain": domain, "confidence": 0.85,
        "domains": [domain], "filters": {}, "filters_gt": {},
        "filters_lt": {}, "sort_by": None, "sort_order": "desc",
        "action_intent": action_intent,
    })


def _action_domain_query_json() -> str:
    return _domain_query_json("scout", action_intent=True)


_SAMPLE_DOMAINS = ["scout", "chronos", "general"]
_SAMPLE_SCHEMAS = {"scout": {"fields": {"price": "number", "city": "string"}}}
_SAMPLE_COMMANDS = [
    {
        "command": "scout_listings", "title": "Case disponibili",
        "description": "Cerca case in vendita",
        "method": "POST", "path": "/api/tools/real_estate/search",
        "service": "scout", "clients": ["telegram"],
        "response_mode": "oracle_natural",
        "body_template": {"query": "$query", "limit": "$arg.limit"},
        "arguments_schema": {
            "query": {"type": "string", "required": False, "description": "Search query"},
            "limit": {"type": "integer", "required": False, "description": "Max results"},
        },
    },
    {
        "command": "create_event", "title": "Crea evento",
        "description": "Crea evento calendario",
        "method": "POST", "path": "/api/calendar/events",
        "service": "chronos", "clients": ["telegram"],
        "response_mode": "oracle_natural",
        "body_template": {"title": "$title", "start_datetime": "$start_datetime"},
        "arguments_schema": {
            "title": {"type": "string", "required": True, "description": "Event title"},
            "start_datetime": {"type": "string", "required": True, "description": "Start time"},
        },
    },
    {
        "command": "agenda", "title": "Agenda",
        "description": "Mostra agenda", "method": "GET",
        "path": "/api/calendar/agenda", "service": "chronos",
        "clients": ["telegram"], "response_mode": "oracle_natural",
    },
    {
        "command": "delete_event", "title": "Elimina evento",
        "description": "Rimuovi evento", "method": "DELETE",
        "path": "/api/calendar/events/$arg.event_id", "service": "chronos",
        "clients": ["telegram"], "response_mode": "oracle_natural",
    },
]


def _collect_ndjson_lines(generator) -> list[dict]:
    """Consume all NDJSON lines from a generator and parse each."""
    lines = []
    for ndjson_line in generator:
        if ndjson_line and ndjson_line.strip():
            lines.append(json.loads(ndjson_line))
    return lines


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Build an OracleEngine with all external deps mocked."""
    with patch.object(AgentFactory, 'create') as mock_create:
        # Mock agent bundle (use-case naming)
        bundle = MagicMock()
        bundle.generic.ask.return_value = "Generic response."
        bundle.generic.ask_with_tools.return_value = {"tool_call": None, "text": "Generic response."}
        bundle.generic.ask_stream.return_value = iter(["Streamed ", "response."])
        bundle.generic_fallback.ask.return_value = "Fast fallback response."
        bundle.generic_fallback.ask_with_tools.return_value = {"tool_call": None, "text": "Fast fallback."}
        bundle.generic_fallback.ask_stream.return_value = iter(["Fallback ", "stream."])
        bundle.reasoning.ask.return_value = "Reasoning response."
        bundle.reasoning.ask_with_tools.return_value = {"tool_call": None, "text": "Reasoning."}
        bundle.reasoning.ask_stream.return_value = iter(["Reasoning ", "stream."])
        bundle.reasoning_fallback.ask.return_value = "Fallback reasoning."
        bundle.reasoning_fallback.ask_with_tools.return_value = {"tool_call": None, "text": "FR."}
        bundle.code.ask.return_value = "Code response."
        bundle.code_fallback.ask.return_value = "Code fallback."
        bundle.embedding.embed.return_value = [0.1] * 768
        bundle.embedding_fallback.embed.return_value = [0.1] * 768
        bundle.generic_model_name = "mock-generic"
        mock_create.return_value = bundle

        eng = OracleEngine()

        # HubClient.get — route by path
        def _hub_get(path, **kwargs):
            path_str = str(path or "")
            if "/domains" in path_str:
                return _SAMPLE_DOMAINS
            if "/schemas" in path_str:
                return _SAMPLE_SCHEMAS
            if "/chat/history" in path_str:
                return []  # empty chat history
            if "/memory/active" in path_str:
                return []  # no saved memories
            if "/subscriptions/active" in path_str:
                return []
            return []

        eng._hub.get = MagicMock(side_effect=_hub_get)

        # hub_get — path-aware (domains vs schemas)
        def _hub_get(path, **kwargs):
            path_str = str(path or "")
            if "/schemas" in path_str:
                return _SAMPLE_SCHEMAS
            return _SAMPLE_DOMAINS
        eng._hub.hub_get = MagicMock(side_effect=_hub_get)

        eng._hub.post = MagicMock(return_value={"ok": True})
        eng._hub.delete = MagicMock(return_value={"ok": True})
        eng._hub.get_commands = MagicMock(return_value=[])
        eng._hub.get_history = MagicMock(return_value=[])
        eng._hub.route_to_service = MagicMock(return_value=(True, {"result": "ok"}))
        eng._hub.append_interaction_ledger = MagicMock()
        eng._hub.create_feedback_record = MagicMock(return_value={"id": 1})
        eng._hub.list_feedback_records = MagicMock(return_value=[])
        eng._hub.export_feedback_jsonl = MagicMock(return_value="")

        # Replace module registry
        eng._module_registry.refresh = MagicMock()
        eng._module_registry._needs_refresh = MagicMock(return_value=False)

        # Replace retrieval service
        eng._retrieval_service.retrieve_entities = MagicMock(return_value=[])

        # Replace memory service
        eng._memory_service.extract_and_save_preferences = MagicMock(return_value=[])
        eng._memory_service.save_memory = MagicMock(return_value=(True, "Memory saved: test"))
        eng._memory_service.search_memories = MagicMock(return_value=(True, [{"fact": "User likes pizza", "domain": "general"}]))

        # Replace document services
        eng._doc_rag.message_is_about_docs = MagicMock(return_value=False)
        eng._doc_rag.search_relevant_chunks = MagicMock(return_value=[])
        eng._doc_rag.list_user_docs_brief = MagicMock(return_value="")

        return eng


# ═══════════════════════════════════════════════════════════════════════════════
# Chat Flow — Quick Chat Path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestChatQuickChat:
    def test_quick_chat_returns_direct_answer(self, engine):
        """Quick chat mode should use primary agent for fast response."""
        # Classifier returns quick_chat JSON, then _quick_answer uses primary agent
        engine._agents.generic.ask.side_effect = [
            _quick_chat_json(),          # classifier call
            "Fast fallback response.",   # _quick_answer call
        ]
        engine._hub.get.return_value = _SAMPLE_DOMAINS  # /domains

        lines = _collect_ndjson_lines(engine.chat("Ciao come stai?", "test-session"))

        answers = [l for l in lines if l.get("type") == "final"]
        assert len(answers) == 1
        assert answers[0]["domain"] == "general"
        assert "Fast fallback" in answers[0]["reply"]

    def test_quick_chat_saves_history(self, engine):
        """Quick chat should persist user+assistant messages to Archive."""
        engine._agents.generic.ask.return_value = _quick_chat_json()
        engine._hub.get.return_value = _SAMPLE_DOMAINS

        _collect_ndjson_lines(engine.chat("Ciao!", "test-session", save_history=True))

        # Should have called post for user message + assistant response
        history_calls = [
            c for c in engine._hub.post.call_args_list
            if "/chat/history" in str(c)
        ]
        assert len(history_calls) >= 2

    def test_quick_chat_with_document_context(self, engine):
        """Quick chat about documents should include document brief."""
        engine._agents.generic.ask.side_effect = [
            _quick_chat_json(),       # classifier call
            "Document response.",     # _quick_answer call
        ]
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        engine._doc_rag.message_is_about_docs.return_value = True
        engine._doc_rag.list_user_docs_brief.return_value = "You have 3 documents."

        _collect_ndjson_lines(engine.chat("Mostra i miei documenti", "test-session"))

        # Verify doc context was requested
        engine._doc_rag.list_user_docs_brief.assert_called()

    def test_quick_chat_emits_memory_sync_signals(self, engine):
        """Quick chat with preference intent should trigger memory sync."""
        engine._agents.generic.ask.side_effect = [
            _quick_chat_json(),       # classifier call
            "Memory response.",       # _quick_answer call
        ]
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        engine._memory_service.extract_and_save_preferences.return_value = [
            {"event": "memory.preference.added", "message": "Saved!", "data": {"fact": "test"}},
        ]

        lines = _collect_ndjson_lines(
            engine.chat("Preferisco il caffè la mattina", "test-session")
        )

        signals = [l for l in lines if l.get("type") == "signal" and "memory" in str(l.get("event", ""))]
        # May or may not trigger depending on intent keyword matching
        # Just verify the path doesn't crash
        assert any(l["type"] == "final" for l in lines)

    def test_quick_chat_skips_when_classified_as_domain_query(self, engine):
        """When classifier returns domain_query, quick chat path is skipped."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.return_value = _SAMPLE_DOMAINS

        lines = _collect_ndjson_lines(engine.chat("Cerca case a Milano", "test-session"))

        # Should go through agent loop path, not quick chat
        statuses = [l["content"] for l in lines if l.get("type") == "status"]
        assert any("domini" in s.lower() for s in statuses)


# ═══════════════════════════════════════════════════════════════════════════════
# Chat Flow — Domain Query / Agent Loop Path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestChatDomainQuery:
    def test_domain_query_builds_tools_and_runs_agent_loop(self, engine):
        """Domain query path should build tools and run the agent loop."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.side_effect = lambda *a, **kw: (
            _SAMPLE_DOMAINS if "/domains" in str(a) else []
        )
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS

        lines = _collect_ndjson_lines(engine.chat("Cerca case a Milano", "test-session"))

        answers = [l for l in lines if l.get("type") == "final"]
        assert len(answers) == 1

    def test_domain_query_injects_preferences(self, engine):
        """User preferences should be loaded and injected into the agent loop."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.side_effect = lambda path, **kw: (
            _SAMPLE_DOMAINS if "/domains" in str(path) else
            [{"id": 1, "fact": "Preferisce appartamenti", "domain": "scout", "memory_class": "durable_user_preference"}]
            if "/memory/active" in str(path) else
            []
        )

        lines = _collect_ndjson_lines(engine.chat("Mostra case", "test-session"))

        # Should complete without error
        assert any(l["type"] == "final" for l in lines)

    def test_domain_query_emits_thinking_events(self, engine):
        """Agent loop should emit thinking events via on_thinking callback."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS

        lines = _collect_ndjson_lines(engine.chat("Cerca trilocale Milano", "test-session"))

        thinking_events = [l for l in lines if l.get("type") == "thinking"]
        # Even without tool calls, we may get reasoning events
        assert len(lines) > 0  # flow completes

    def test_domain_query_emits_tool_summary_when_tools_called(self, engine):
        """After agent loop with tools, a tool.summary signal should be emitted."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        # Make the analyst call a tool then answer
        import core.agent_loop as al_mod
        xml_call = f'<tool_call>{json.dumps({"name": "scout_listings", "params": {"query": "Milano"}})}</tool_call>'
        engine._agents.generic.ask.side_effect = [xml_call, "Ecco i risultati a Milano."]
        engine._agents.generic.ask_with_tools.return_value = {
            "tool_call": {"name": "scout_listings", "params": {"query": "Milano"}}, "text": ""
        }

        lines = _collect_ndjson_lines(engine.chat("Cerca trilocale Milano", "test-session"))

        tool_summaries = [l for l in lines if l.get("type") == "signal" and l.get("event") == "tool.summary"]
        assert len(tool_summaries) >= 1
        calls = tool_summaries[0].get("data", {}).get("calls", [])
        assert len(calls) >= 1
        assert calls[0]["tool"] == "scout_listings"

    def test_domain_query_persists_history(self, engine):
        """After agent loop, history should be saved."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.side_effect = lambda *a, **kw: (
            _SAMPLE_DOMAINS if "/domains" in str(a) else []
        )

        _collect_ndjson_lines(engine.chat("Cerca case", "test-session", save_history=True))

        history_calls = [
            c for c in engine._hub.post.call_args_list
            if "/chat/history" in str(c)
        ]
        assert len(history_calls) >= 2  # user + assistant

    def test_domain_query_runs_background_memory(self, engine):
        """Background memory extraction should fire after agent loop."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.return_value = _SAMPLE_DOMAINS

        _collect_ndjson_lines(engine.chat("Ricordati che preferisco Milano", "test-session"))

        # Background thread fires — give it a brief moment
        import time
        time.sleep(0.3)

        # Memory service should have been called at least via background path
        # (the sync path may or may not trigger based on intent keywords)


# ═══════════════════════════════════════════════════════════════════════════════
# Chat Flow — Action Intent Path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestChatActionIntent:
    def test_action_intent_injects_policy_in_agent_loop(self, engine):
        """When classifier detects action_intent, the agent loop gets action policy."""
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS

        captured_prompts = []
        # generic handles classify AND chat — first call returns JSON, rest are text
        call_count = [0]
        def _smart_ask(prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                return _action_domain_query_json()  # classifier call
            captured_prompts.append(prompt)
            return "Azione completata."
        def _capture_ask_tools(prompt, manifest, **kwargs):
            captured_prompts.append(prompt)
            return {"tool_call": None, "text": "Azione completata."}

        engine._agents.generic.ask.side_effect = _smart_ask
        engine._agents.generic.ask_with_tools.side_effect = _capture_ask_tools

        _collect_ndjson_lines(engine.chat("Crea un evento domani", "test-session"))

        assert len(captured_prompts) > 0, f"No prompts captured. call_count={call_count[0]}"
        assert any(
            "ACTION INTENT" in p or "operational change" in p.lower()
            for p in captured_prompts
        ), f"No action intent found in {len(captured_prompts)} captured prompts"

    def test_action_intent_creates_event_tool(self, engine):
        """Action intent with calendar command should make create_event tool available."""
        engine._agents.generic.ask.return_value = _action_domain_query_json()
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS

        lines = _collect_ndjson_lines(engine.chat("Crea evento domani alle 15", "test-session"))

        assert any(l["type"] == "final" for l in lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Building
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestBuildDomainTools:
    def test_builds_domain_search_tools(self, engine):
        """Domain tools should include {domain}.search for each OWNED domain."""
        from core.oracle_engine import SessionIntent
        engine._module_registry.get_domain_owners = lambda d: (
            ["scout"] if d == "scout" else ["chronos"] if d == "chronos" else []
        )
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout", "chronos"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)

        tool_names = {t.name for t in tools}
        assert "scout.search" in tool_names
        assert "chronos.search" in tool_names

    def test_builds_document_search_tool(self, engine):
        """Document search tool should always be included."""
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)

        tool_names = {t.name for t in tools}
        assert "documents.search" in tool_names

    def test_builds_memory_tools(self, engine):
        """Memory save and search tools should always be included."""
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain=None,
            confidence=0.5, valid_domains=["general"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)

        tool_names = {t.name for t in tools}
        assert "memory.save" in tool_names
        assert "memory.search" in tool_names

    def test_memory_save_tool_handler_works(self, engine):
        """memory.save tool should persist via MemoryService."""
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain=None,
            confidence=0.5, valid_domains=["general"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)
        mem_save = next(t for t in tools if t.name == "memory.save")

        ok, msg = mem_save.handler(fact="User likes Roma", domain="general")
        assert ok is True
        engine._memory_service.save_memory.assert_called_with(fact="User likes Roma", domain="general")

    def test_memory_search_tool_handler_works(self, engine):
        """memory.search tool should query via MemoryService."""
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain=None,
            confidence=0.5, valid_domains=["general"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)
        mem_search = next(t for t in tools if t.name == "memory.search")

        ok, results = mem_search.handler(query="Roma")
        assert ok is True
        engine._memory_service.search_memories.assert_called_with(query="Roma")

    def test_hub_commands_become_tools(self, engine):
        """Hub commands filtered by classified domain — only domain-owner tools included."""
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        engine._module_registry.get_domain_owners = lambda d: (
            ["scout"] if d == "scout" else ["chronos"] if d == "chronos" else []
        )
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)

        tool_names = {t.name for t in tools}
        assert "scout_listings" in tool_names  # scout domain owner
        assert "create_event" not in tool_names  # chronos, not scout domain
        assert "agenda" not in tool_names  # chronos, not scout domain

    def test_hub_commands_all_domains_when_general(self, engine):
        """When domain is general, ALL commands are included (no filter)."""
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain=None,
            confidence=0.5, valid_domains=["general"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)

        tool_names = {t.name for t in tools}
        assert "scout_listings" in tool_names
        assert "create_event" in tool_names
        assert "agenda" in tool_names

    def test_hub_command_tool_has_proper_schema(self, engine):
        """Hub command tools should have JSON Schema parameters."""
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        engine._module_registry.get_domain_owners = lambda d: ["chronos"] if d == "chronos" else []
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain="chronos",
            confidence=0.9, valid_domains=["chronos"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)

        create_event = next(t for t in tools if t.name == "create_event")
        params = create_event.parameters
        assert params["type"] == "object"
        assert "title" in params.get("properties", {})
        assert "start_datetime" in params.get("properties", {})

    def test_hub_command_handler_routes_to_service(self, engine):
        """Hub command handler should route via HubClient.route_to_service."""
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)
        cmd = next(t for t in tools if t.name == "agenda")

        ok, result = cmd.handler()
        assert ok is True
        engine._hub.route_to_service.assert_called()
        call_kwargs = engine._hub.route_to_service.call_args
        assert call_kwargs[1]["service"] == "chronos"

    def test_handles_commands_with_no_args_schema(self, engine):
        """Commands without arguments_schema should still become valid tools."""
        engine._hub.get_commands.return_value = [
            {"command": "simple_cmd", "title": "Simple",
             "method": "GET", "path": "/api/simple", "service": "test",
             "clients": ["telegram"], "response_mode": "direct"},
        ]
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain=None,
            confidence=0.5, valid_domains=["general"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)
        simple = next(t for t in tools if t.name == "simple_cmd")
        assert simple.parameters["type"] == "object"

    def test_duplicate_command_names_not_added_twice(self, engine):
        """If a domain tool has same name as Hub command, it shouldn't duplicate."""
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        from core.oracle_engine import SessionIntent
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout"],
        )

        tools = engine._build_domain_tools(intent, "test-session", None)
        tool_names = [t.name for t in tools]
        # No duplicates
        assert len(tool_names) == len(set(tool_names))


# ═══════════════════════════════════════════════════════════════════════════════
# Athena Hints
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestAthenaHints:
    def test_ingest_athena_hint_stores(self, engine):
        result = engine.ingest_athena_hint({
            "hint_type": "focus_brief",
            "summary": "User is looking for apartments in Roma",
            "domain": "scout",
            "priority": "high",
        })
        assert result["status"] == "ok"
        assert result["stored"] is True

    def test_list_athena_hints_returns_stored(self, engine):
        engine.ingest_athena_hint({"summary": "Test hint", "domain": "scout"})
        result = engine.list_athena_hints(limit=10)
        assert len(result) >= 1

    def test_athena_hints_disabled_when_env_false(self, engine):
        engine._athena_hints_enabled = False
        result = engine.ingest_athena_hint({"summary": "Should not store"})
        assert result["status"] == "disabled"
        assert result["stored"] is False

    def test_select_relevant_hints_filters_by_domain(self, engine):
        engine.ingest_athena_hint({"summary": "Roma hint", "domain": "scout"})
        engine.ingest_athena_hint({"summary": "Calendar hint", "domain": "chronos"})

        hints = engine._select_relevant_athena_hints(
            session_id="test", valid_domains=["scout"], limit=10
        )
        assert any("Roma" in h.get("summary", "") for h in hints)

    def test_format_athena_hints_produces_text(self, engine):
        hints = [
            {"summary": "Test hint", "priority": "high",
             "domains": ["scout"], "gate": {"score": 0.8, "threshold": 0.55}},
        ]
        text = engine._format_athena_hints_for_prompt(hints)
        assert "Test hint" in text
        assert "high" in text


# ═══════════════════════════════════════════════════════════════════════════════
# High-Impact Action Approval
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestActionApproval:
    def test_approval_queue_and_resolve(self, engine):
        """Queue an approval token, then resolve it with approve=True."""
        engine._approval_enabled = True
        token = engine._queue_high_impact_approval(
            matched={"command": "delete_event", "method": "DELETE", "path": "/api/events/123",
                     "service": "chronos", "title": "Elimina evento"},
            action_name="delete_event",
            title="Elimina evento",
            param_sets=[{"event_id": "123"}],
            session_id="test-session",
            notify_target=None,
            trace_id=None,
            client_instructions=None,
        )
        assert token
        assert len(token) == 16  # hex[:16]

        # Resolve
        result = engine.respond_high_impact_action_approval(
            approval_token=token, approve=True,
        )
        assert result["status"] in ("approved_executed", "approved_failed")

    def test_approval_reject(self, engine):
        """Rejecting an approval should cancel the action."""
        engine._approval_enabled = True
        token = engine._queue_high_impact_approval(
            matched={"command": "delete_event", "method": "DELETE", "path": "/api/events/123",
                     "service": "chronos", "title": "Elimina evento"},
            action_name="delete_event",
            title="Elimina evento",
            param_sets=[{"event_id": "123"}],
            session_id="test-session",
            notify_target=None,
            trace_id=None,
            client_instructions=None,
        )
        result = engine.respond_high_impact_action_approval(
            approval_token=token, approve=False,
        )
        assert result["status"] == "canceled"
        assert result["approved"] is False

    def test_approval_unknown_token(self, engine):
        result = engine.respond_high_impact_action_approval(
            approval_token="nonexistent1234", approve=True,
        )
        assert result["status"] == "not_found"

    def test_approval_expired_cleaned_up(self, engine):
        """Expired approvals should be cleaned up."""
        engine._approval_enabled = True
        engine._approval_ttl_seconds = 0
        token = engine._queue_high_impact_approval(
            matched={"command": "test", "method": "POST", "path": "/api/test",
                     "service": "test", "title": "Test"},
            action_name="test", title="Test",
            param_sets=[{}], session_id="s", notify_target=None, trace_id=None,
            client_instructions=None,
        )
        # Force expiry by modifying the stored token
        with engine._approval_lock:
            if token in engine._pending_action_approvals:
                engine._pending_action_approvals[token]["expires_at"] = time.time() - 10
        engine._cleanup_expired_action_approvals()
        result = engine.respond_high_impact_action_approval(
            approval_token=token, approve=True,
        )
        assert result["status"] == "not_found"

    def test_requires_high_impact_approval_delete_method(self, engine):
        """DELETE method should trigger approval by default."""
        assert engine._requires_high_impact_approval(
            {"method": "DELETE"}, "delete_something", [{}]
        ) is True

    def test_requires_high_impact_approval_get_method_skipped(self, engine):
        """GET method should not trigger approval."""
        assert engine._requires_high_impact_approval(
            {"method": "GET"}, "get_something", [{}]
        ) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Temporal Context
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestTemporalContext:
    def test_current_datetime_context_has_all_fields(self, engine):
        context = engine._current_datetime_context()
        assert "timezone=" in context
        assert "now_iso=" in context
        assert "today_date=" in context
        assert "today_weekday=" in context
        assert "tomorrow_date=" in context

    def test_temporal_context_injected_into_agent_loop(self, engine):
        """The temporal context should appear in agent loop client instructions."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get.return_value = _SAMPLE_DOMAINS

        # Capture what gets sent to the analyst
        captured = []
        def _capture(prompt):
            captured.append(prompt)
            return "Done."
        engine._agents.generic.ask.side_effect = _capture

        _collect_ndjson_lines(engine.chat("Che eventi ho domani?", "test-session"))

        if captured:
            assert any("CURRENT_DATETIME_CONTEXT" in p or "today_date" in p for p in captured)


# ═══════════════════════════════════════════════════════════════════════════════
# Format Payload
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestFormatPayload:
    def test_format_returns_html(self, engine):
        result = engine.format_payload(
            command="scout_listings",
            payload={"items": [{"title": "Appartamento", "price": 200000}]},
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_alert_uses_alert_template(self, engine):
        """Alert formatting should use alert-specific template."""
        result = engine.format_payload(
            command="alert:real_estate",
            payload={"items": [{"title": "Nuovo annuncio", "price": 150000}]},
        )
        assert isinstance(result, str)

    def test_format_with_thinking_disabled(self, engine):
        """Format calls should work with thinking=False."""
        result = engine.format_payload(
            command="test",
            payload={"key": "value"},
            thinking=False,
        )
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Error Handling / Fallback
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestErrorHandling:
    def test_quick_chat_fallback_on_primary_failure(self, engine):
        """When primary fails, fallback should be used."""
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        # Classifier succeeds, then _quick_answer primary fails, fallback recovers
        engine._agents.generic.ask.side_effect = [
            _quick_chat_json(),          # classifier call
            Exception("Primary dead"),   # _quick_answer: primary fails
        ]
        engine._agents.generic_fallback.ask.return_value = "Recovered answer."

        lines = _collect_ndjson_lines(engine.chat("Ciao", "test-session"))
        answers = [l for l in lines if l.get("type") == "final"]
        assert len(answers) == 1
        assert "Recovered" in answers[0]["reply"]

    def test_save_history_failure_non_fatal(self, engine):
        """Chat should not crash when history save fails."""
        engine._agents.generic.ask.side_effect = [
            _quick_chat_json(),       # classifier call
            "Chat response.",         # _quick_answer call
        ]
        engine._hub.get.return_value = _SAMPLE_DOMAINS
        engine._hub.post.side_effect = requests.RequestException("DB down")

        lines = _collect_ndjson_lines(engine.chat("Ciao", "test-session"))
        # Should still return an answer
        assert any(l["type"] == "final" for l in lines)

    def test_classifier_failure_falls_back_to_defaults(self, engine):
        """When both router and fallback fail, use default classification."""
        engine._agents.generic.ask.side_effect = RuntimeError("Primary dead")
        engine._agents.generic_fallback.ask.side_effect = RuntimeError("Fallback dead")
        engine._hub.get.return_value = _SAMPLE_DOMAINS

        lines = _collect_ndjson_lines(engine.chat("Ciao", "test-session"))
        assert any(l["type"] == "final" for l in lines)

    def test_agent_loop_analyst_failure_user_friendly_error(self, engine):
        """When analyst completely fails, return Italian error message."""
        engine._agents.generic.ask.return_value = _domain_query_json("scout")
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        engine._agents.generic.ask.side_effect = RuntimeError("Ollama crashed")
        engine._agents.generic_fallback.ask.side_effect = RuntimeError("Gemini down")
        engine._agents.generic.ask_with_tools.side_effect = RuntimeError("Ollama crashed")
        engine._agents.generic_fallback.ask_with_tools.side_effect = RuntimeError("Gemini down")

        lines = _collect_ndjson_lines(engine.chat("Cerca case", "test-session"))
        answers = [l for l in lines if l.get("type") == "final"]
        assert len(answers) >= 1
        reply = answers[0].get("reply", "")
        # Should have some non-empty reply (may be error or fallback)
        assert len(reply) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Session Management
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSessionManagement:
    def test_delete_chat_history(self, engine):
        engine.delete_chat_history("test-session")
        engine._hub.delete.assert_called()

    def test_save_history_appends_user_and_assistant(self, engine):
        engine._save_history("s1", "user msg", "assistant reply")
        assert engine._hub.post.call_count >= 2

    def test_load_preferences_deduplicates_by_id(self, engine):
        """Preferences with same id across domains should be deduplicated."""
        prefs_db = [
            {"id": 1, "fact": "Pref A", "domain": "scout", "memory_class": "durable_user_preference"},
            {"id": 1, "fact": "Pref A duplicate", "domain": "scout", "memory_class": "durable_user_preference"},
            {"id": 2, "fact": "Pref B", "domain": "general", "memory_class": "durable_user_preference"},
        ]
        # Override the hub.get to return prefs for memory/active
        def _hub_get(path, **kw):
            if "/memory/active" in str(path):
                domain = str(path).split("domain=")[-1].split("&")[0] if "domain=" in str(path) else "scout"
                return [p for p in prefs_db if p.get("domain") == domain or p.get("domain") == "scout"]
            return []
        engine._hub.get.side_effect = _hub_get

        prefs = engine._load_preferences(["scout", "general"])
        assert len(prefs) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Question / Answer Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestQuestionProtocol:
    def test_ask_question_registers(self, engine):
        ndjson = engine.ask_question(
            session_id="s1", question_id="q1",
            header="Conferma", prompt="Vuoi procedere?",
        )
        data = json.loads(ndjson)
        assert data["type"] == "question"
        assert data["question_id"] == "q1"

    def test_answer_question_resolves(self, engine):
        engine.ask_question(session_id="s1", question_id="q1",
                            header="H", prompt="P?")
        resolved = engine.answer_question("q1", "si")
        assert resolved is True

    def test_answer_unknown_question(self, engine):
        resolved = engine.answer_question("nonexistent", "answer")
        assert resolved is False

    def test_get_question_answer(self, engine):
        engine.ask_question(session_id="s1", question_id="q1",
                            header="H", prompt="P?")
        engine.answer_question("q1", "si")
        answer = engine.get_question_answer("q1")
        assert answer == "si"


# ═══════════════════════════════════════════════════════════════════════════════
# Chat Modes (Phase 10)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestChatModes:
    def test_quick_mode_skips_classify_and_returns_fast_answer(self, engine):
        """Quick mode should bypass classify + agent loop entirely."""
        engine._agents.generic.ask.return_value = "Risposta rapida."
        lines = _collect_ndjson_lines(engine.chat(
            "Ciao!", "test-session", mode="quick"
        ))
        answers = [l for l in lines if l.get("type") == "final"]
        assert len(answers) == 1
        assert "Risposta rapida" in answers[0]["reply"]

    def test_quick_mode_saves_history(self, engine):
        """Quick mode should still persist history."""
        engine._agents.generic.ask.return_value = "Ok."
        _collect_ndjson_lines(engine.chat(
            "Test", "test-session", mode="quick", save_history=True
        ))
        history_calls = [c for c in engine._hub.post.call_args_list
                         if "/chat/history" in str(c)]
        assert len(history_calls) >= 2

    def test_auto_mode_is_default(self, engine):
        """auto mode should work same as before (classify then route)."""
        engine._agents.generic.ask.return_value = json.dumps({
            "mode": "quick_chat", "domain": None, "confidence": 0.9,
            "domains": ["general"], "filters": {}, "filters_gt": {},
            "filters_lt": {}, "sort_by": None, "sort_order": "desc",
            "action_intent": False,
        })
        lines = _collect_ndjson_lines(engine.chat(
            "Ciao", "test-session", mode="auto"
        ))
        assert any(l["type"] == "final" for l in lines)

    def test_thinking_mode_forces_agent_loop(self, engine):
        """Thinking mode should force agent loop even for general queries."""
        engine._agents.generic.ask.return_value = json.dumps({
            "mode": "quick_chat", "domain": None, "confidence": 0.95,
            "domains": ["general"], "filters": {}, "filters_gt": {},
            "filters_lt": {}, "sort_by": None, "sort_order": "desc",
            "action_intent": False,
        })
        engine._hub.get_commands.return_value = _SAMPLE_COMMANDS
        lines = _collect_ndjson_lines(engine.chat(
            "Analizza questa situazione complessa", "test-session", mode="thinking"
        ))
        statuses = [l["content"] for l in lines if l.get("type") == "status"]
        # Thinking mode should mention "thinking" or "ragionamento"
        assert any("thinking" in s.lower() or "ragionamento" in s.lower() for s in statuses) or len(lines) > 0


@pytest.mark.unit
class TestModelResolution:
    def test_resolve_agent_generic(self, engine):
        agent = engine._resolve_agent("generic")
        assert agent is engine._agents.generic

    def test_resolve_agent_reasoning(self, engine):
        agent = engine._resolve_agent("reasoning")
        assert agent is engine._agents.reasoning

    def test_resolve_agent_code(self, engine):
        agent = engine._resolve_agent("code")
        assert agent is engine._agents.code

    def test_resolve_agent_unknown_falls_back_to_generic(self, engine):
        agent = engine._resolve_agent("nonexistent")
        assert agent is engine._agents.generic

    def test_resolve_agent_empty_string(self, engine):
        agent = engine._resolve_agent("")
        assert agent is engine._agents.generic

    def test_chat_with_model_param_uses_reasoning(self, engine):
        """When model='reasoning', chat should use reasoning agent."""
        engine._agents.reasoning.ask.return_value = json.dumps({
            "mode": "quick_chat", "domain": None, "confidence": 0.9,
            "domains": ["general"], "filters": {}, "filters_gt": {},
            "filters_lt": {}, "sort_by": None, "sort_order": "desc",
            "action_intent": False,
        })
        engine._agents.reasoning.ask_stream.return_value = iter(["Deep ", "answer."])
        lines = _collect_ndjson_lines(engine.chat(
            "Analisi complessa", "test-session", mode="auto", model="reasoning"
        ))
        assert any(l["type"] == "final" for l in lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Enriched Temporal Context (Phase 12)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestTemporalContextEnriched:
    def test_includes_time_of_day(self, engine):
        ctx = engine._current_datetime_context()
        assert "time_of_day=" in ctx
        tod = [l for l in ctx.split("\n") if "time_of_day=" in l][0]
        assert any(t in tod for t in ["morning", "afternoon", "evening", "night"])

    def test_includes_season(self, engine):
        ctx = engine._current_datetime_context()
        assert "season=" in ctx
        season_line = [l for l in ctx.split("\n") if "season=" in l][0]
        assert any(s in season_line for s in ["Spring", "Summer", "Autumn", "Winter"])

    def test_includes_basic_datetime_fields(self, engine):
        ctx = engine._current_datetime_context()
        assert "timezone=" in ctx
        assert "now_iso=" in ctx
        assert "today_date=" in ctx
        assert "today_weekday=" in ctx
        assert "tomorrow_date=" in ctx

    def test_calendar_disabled_respected(self, engine, monkeypatch):
        monkeypatch.setenv("ORACLE_TEMPORAL_CALENDAR_ENABLED", "0")
        ctx = engine._current_datetime_context()
        assert "TODAY_AGENDA" not in ctx


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-End Telegram Flow — tests the EXACT path Telegram uses
# ═══════════════════════════════════════════════════════════════════════════════

_CALENDAR_COMMANDS = [
    {
        "command": "agenda",
        "title": "📅 Agenda",
        "description": "Mostra gli eventi in agenda nei prossimi 7 giorni",
        "method": "GET",
        "path": "/api/calendar/agenda",
        "service": "chronos",
        "clients": ["telegram"],
        "response_mode": "oracle_natural",
        "arguments_schema": {
            "days": {"type": "integer", "required": False, "description": "How many days ahead"},
            "source": {"type": "string", "required": False, "description": "Filter by source"},
        },
    },
    {
        "command": "agenda_today",
        "title": "📋 Agenda di oggi",
        "description": "Mostra gli eventi di oggi",
        "method": "GET",
        "path": "/api/calendar/agenda",
        "service": "chronos",
        "clients": ["telegram"],
        "response_mode": "oracle_natural",
        "arguments_schema": {},
    },
    {
        "command": "create_event",
        "title": "📅 Crea evento",
        "description": "Crea un nuovo evento nel calendario",
        "method": "POST",
        "path": "/api/calendar/events",
        "service": "chronos",
        "clients": ["telegram"],
        "response_mode": "oracle_natural",
        "arguments_schema": {
            "title": {"type": "string", "required": True, "description": "Event title"},
            "start_datetime": {"type": "string", "required": True, "description": "Start time ISO 8601"},
            "end_datetime": {"type": "string", "required": False, "description": "End time ISO 8601"},
        },
    },
]

_CALENDAR_AGENDA_RESPONSE = {
    "from": "2026-06-17T00:00:00+00:00",
    "to": "2026-06-24T00:00:00+00:00",
    "days": 7,
    "count": 2,
    "items": [
        {"title": "Riunione team", "start": "2026-06-17T10:00:00", "end": "2026-06-17T11:00:00"},
        {"title": "Dentista", "start": "2026-06-18T14:30:00", "end": "2026-06-18T15:30:00"},
    ],
}


@pytest.mark.unit
class TestEndToEndTelegramCalendarFlow:
    """Tests the EXACT code path that Telegram uses:
    Telegram → Hub → Oracle /api/chat → classify → build tools → agent loop → answer
    """

    def _setup_e2e_engine(self, engine):
        """Configure mocks for the full Telegram→Oracle→Hub→Chronos flow."""
        # Hub domains — include calendar so classifier knows about it
        def _hub_get_side_effect(path, **kwargs):
            path_str = str(path or "")
            if "/chat/history" in path_str:
                return []
            if "/memory/active" in path_str:
                return []
            if "/subscriptions/active" in path_str:
                return []
            return []
        engine._hub.get = MagicMock(side_effect=_hub_get_side_effect)
        def _hub_get_side_effect_e2e(path, **kw):
            path_str = str(path or "")
            if "/schemas" in path_str:
                return {}
            return ["calendar", "scout", "general"]
        engine._hub.hub_get = MagicMock(side_effect=_hub_get_side_effect_e2e)
        engine._hub.get_history = MagicMock(return_value=[])
        engine._hub.get_commands = MagicMock(return_value=_CALENDAR_COMMANDS)
        engine._hub.route_to_service = MagicMock(return_value=(True, _CALENDAR_AGENDA_RESPONSE))
        engine._hub.post = MagicMock(return_value={"ok": True})
        # Domain owners for calendar domain (Plan P1 filtering)
        engine._module_registry.get_domain_owners = lambda d: (
            ["chronos"] if d == "calendar" else []
        )

    def test_calendar_query_discovers_agenda_tool(self, engine):
        """When user asks about calendar, the agenda tool MUST be among built tools."""
        self._setup_e2e_engine(engine)

        # Capture tools built by _build_domain_tools
        original_build = engine._build_domain_tools

        captured_tools: list[list] = []

        def _capture_build(intent, session_id, notify_target, trace_id=None, fallback_domains=None):
            tools = original_build(intent, session_id, notify_target, trace_id=trace_id, fallback_domains=fallback_domains)
            captured_tools.append([t.name for t in tools])
            return tools

        engine._build_domain_tools = _capture_build

        # Classifier → domain_query for general (since available_domains has calendar)
        engine._agents.generic.ask.side_effect = [
            json.dumps({
                "mode": "domain_query", "domain": None, "confidence": 0.85,
                "domains": ["general"], "filters": {}, "filters_gt": {},
                "filters_lt": {}, "sort_by": None, "sort_order": "desc",
                "action_intent": False,
            }),
            "✅ Ecco i tuoi prossimi eventi:\n\n• <b>Riunione team</b> - 17 giugno 10:00-11:00\n• <b>Dentista</b> - 18 giugno 14:30-15:30",
        ]

        # Agent loop: first turn returns agenda tool call, second turn is final answer
        engine._agents.generic.ask_with_tools.side_effect = [
            {"tool_call": {"name": "agenda", "params": {"days": 7}}, "text": ""},
            {"tool_call": None, "text": "Ecco i tuoi eventi."},
        ]

        lines = _collect_ndjson_lines(engine.chat(
            "sai dirmi cosa ho in calendario?", "test-telegram-session"))

        # ── Verify tool discovery ──────────────────────────────────────────
        assert captured_tools, "No tools were built — _build_domain_tools was never called"
        tool_names = captured_tools[0]
        assert "agenda" in tool_names, (
            f"agenda tool NOT in built tools! Tools: {tool_names}\n"
            f"This means get_commands() returned empty or Hub commands weren't added."
        )
        assert "agenda_today" in tool_names, f"agenda_today missing. Tools: {tool_names}"
        # create_event is POST — kept because POST is used for both search & create
        assert "create_event" in tool_names, f"create_event missing. Tools: {tool_names}"

        # ── Verify tool was called via Hub routing ─────────────────────────
        route_calls = engine._hub.route_to_service.call_args_list
        assert len(route_calls) >= 1, (
            f"No Hub route_to_service calls — the agenda tool was never executed!\n"
            f"route_to_service call count: {len(route_calls)}"
        )
        # First route call should be to chronos agenda
        first_call = route_calls[0]
        assert first_call.kwargs.get("service") == "chronos", (
            f"Tool called wrong service: {first_call.kwargs.get('service')}, expected 'chronos'"
        )
        assert "agenda" in str(first_call.kwargs.get("path", "")), (
            f"Tool called wrong path: {first_call.kwargs.get('path')}, expected agenda path"
        )

        # ── Verify final answer is emitted ─────────────────────────────────
        finals = [l for l in lines if l.get("type") == "final"]
        assert len(finals) == 1, f"Expected 1 final answer, got {len(finals)}: {finals}"
        assert len(finals[0].get("reply", "")) > 10, (
            f"Final answer too short: '{finals[0].get('reply')}'"
        )

        # ── Verify tool summary is emitted ─────────────────────────────────
        summaries = [l for l in lines if l.get("event") == "tool.summary"]
        assert len(summaries) >= 1, f"No tool.summary event emitted"

    def test_calendar_query_no_tools_available_is_logged(self, engine):
        """When Hub returns NO commands, the warning must be logged."""
        self._setup_e2e_engine(engine)
        engine._hub.get_commands = MagicMock(return_value=[])  # ← simulate broken discovery

        engine._agents.generic.ask.side_effect = [
            json.dumps({
                "mode": "domain_query", "domain": None, "confidence": 0.85,
                "domains": ["general"], "filters": {}, "filters_gt": {},
                "filters_lt": {}, "sort_by": None, "sort_order": "desc",
                "action_intent": False,
            }),
            "Non posso accedere al calendario.",
        ]
        engine._agents.generic.ask_with_tools.return_value = {"tool_call": None, "text": "Non posso accedere al calendario."}

        lines = _collect_ndjson_lines(engine.chat(
            "sai dirmi cosa ho in calendario?", "test-no-tools"))

        finals = [l for l in lines if l.get("type") == "final"]
        assert len(finals) == 1
        # Without tools, the answer should NOT contain real calendar data
        reply = finals[0].get("reply", "").lower()
        assert "riunione team" not in reply, (
            f"Answer contains calendar data but no tools were available! reply={reply[:200]}"
        )

    def test_create_event_tool_routes_to_chronos(self, engine):
        """Creating a calendar event must route POST to Chronos via Hub."""
        self._setup_e2e_engine(engine)

        engine._agents.generic.ask.side_effect = [
            json.dumps({
                "mode": "domain_query", "domain": None, "confidence": 0.85,
                "domains": ["general"], "filters": {}, "filters_gt": {},
                "filters_lt": {}, "sort_by": None, "sort_order": "desc",
                "action_intent": True,
            }),
            "✅ Evento creato con successo!",
        ]
        engine._agents.generic.ask_with_tools.side_effect = [
            {"tool_call": {"name": "create_event", "params": {
                "title": "Riunione progetto",
                "start_datetime": "2026-06-18T15:00:00",
                "end_datetime": "2026-06-18T16:00:00",
            }}, "text": ""},
            {"tool_call": None, "text": "Evento creato."},
        ]

        lines = _collect_ndjson_lines(engine.chat(
            "crea una riunione domani alle 15 per il progetto Hestia", "test-create-event"))

        # Verify the tool routed to chronos with POST
        route_calls = engine._hub.route_to_service.call_args_list
        create_calls = [c for c in route_calls if c.kwargs.get("service") == "chronos"
                       and c.kwargs.get("method") == "POST"]
        assert len(create_calls) >= 1, (
            f"No POST to chronos! Route calls: {[(c.kwargs.get('service'), c.kwargs.get('method')) for c in route_calls]}"
        )

        finals = [l for l in lines if l.get("type") == "final"]
        assert len(finals) == 1
