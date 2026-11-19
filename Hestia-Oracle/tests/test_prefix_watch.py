"""Prefix watch: a changed fixed part of the prompt between two turns is logged with where it changed
(dossier docs/work/2026-11-17-compact-outputs v1.2)."""
from __future__ import annotations

import pytest

from core.agent_loop import ToolDefinition, run_agent_loop
from core.services import llm_stats, prefix_watch


@pytest.fixture(autouse=True)
def _clean():
    prefix_watch.reset()
    yield
    prefix_watch.reset()


@pytest.mark.unit
class TestPrefixWatch:
    def test_first_turn_and_same_prefix_say_nothing(self):
        assert prefix_watch.check("s|chat", "RULES:\nbe brief", ("a",)) is None
        assert prefix_watch.check("s|chat", "RULES:\nbe brief", ("a",)) is None

    def test_changed_section_is_named(self):
        prefix_watch.check("s|chat", "RULES:\nbe brief\n\nNOW:\n10:00", ())
        change = prefix_watch.check("s|chat", "RULES:\nbe brief\n\nNOW:\n10:05", ())
        assert change["where"] == "NOW" and change["kept_chars"] == len("RULES:\nbe brief\n\nNOW:\n10:0")
        assert change["detail"].startswith("5")

    def test_tool_list_change_is_reported(self):
        prefix_watch.check("s|chat", "X", ("calendar_list", "memory.save"))
        change = prefix_watch.check("s|chat", "X", ("finance_add", "memory.save"))
        assert change["where"] == "tools" and "+finance_add" in change["detail"] and "-calendar_list" in change["detail"]

    def test_loops_and_conversations_are_separate(self):
        prefix_watch.check("s|chat", "A", ())
        assert prefix_watch.check("s|agent.plutus", "B", ()) is None
        assert prefix_watch.check("t|chat", "C", ()) is None

    def test_agent_loop_checks_once_per_turn_with_session(self):
        tool = ToolDefinition("t", "d", {"type": "object", "properties": {}}, handler=lambda **_: (True, "ok"))
        token = llm_stats._current_session.set("sess")
        try:
            for instructions in ("style A", "style B"):
                run_agent_loop("ciao", "", [], [tool], ask_fn=lambda p: "fine", client_instructions=instructions)
        finally:
            llm_stats._current_session.reset(token)
        key = "sess|chat"
        assert key in prefix_watch._last and "style B" in prefix_watch._last[key][0]

    def test_turn_notes_stay_out_of_the_fixed_part(self):
        """Regression 2026-11-18: time, hints and the request's lines sat in the fixed part and broke the cache at
        every message. As turn notes they go after the history and the fixed part stays the same."""
        tool = ToolDefinition("t", "d", {"type": "object", "properties": {}}, handler=lambda **_: (True, "ok"))
        prompts: list[str] = []

        def ask(p):
            prompts.append(p)
            return "fine"

        token = llm_stats._current_session.set("sess2")
        changes = []
        try:
            for minute in ("10:00", "10:05"):
                run_agent_loop("ciao", "user: hi\nassistant: hi", [], [tool], ask_fn=ask,
                               client_instructions="MODULES: x", turn_notes=f"CURRENT_DATETIME_CONTEXT:\n{minute}")
                changes.append(prefix_watch._last["sess2|chat"][0])
        finally:
            llm_stats._current_session.reset(token)
        assert changes[0] == changes[1] and "10:0" not in changes[0]
        p = prompts[-1]
        assert p.index("CONVERSATION HISTORY") < p.index("CURRENT_DATETIME_CONTEXT") < p.index("USER: ciao")
