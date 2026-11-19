"""«Add now» while the assistant works (dossier docs/work/2026-11-18-problemi-del-test, B)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.agent_loop import ToolDefinition, run_agent_loop
from core.services import llm_stats, steering


@pytest.fixture(autouse=True)
def _clean():
    steering._running.clear()
    steering._pending.clear()
    yield
    steering._running.clear()
    steering._pending.clear()


@pytest.mark.unit
def test_refused_when_no_turn_runs():
    assert steering.add("s1", "also tomorrow") is False
    steering.begin("s1")
    assert steering.add("s1", "also tomorrow", "m1") is True
    assert steering.take("s1") == [{"id": "m1", "text": "also tomorrow"}]
    assert steering.take("s1") == []


@pytest.mark.unit
def test_end_drops_what_was_not_taken():
    steering.begin("s1")
    steering.add("s1", "late text", "m2")
    assert steering.end("s1") == [{"id": "m2", "text": "late text"}]
    assert steering.add("s1", "after the end") is False      # the client sends it as the next message


@pytest.mark.unit
def test_chat_loop_reads_the_steer_at_its_next_step():
    prompts: list[str] = []
    answers = iter([f'<tool_call>{json.dumps({"name": "calendar_list", "params": {}})}</tool_call>',
                    "Done, both days."])

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers, "Done, both days.")

    def handler(**_):        # the user writes «Add now» while the tool runs
        assert steering.add("s9", "and tomorrow too", "m7") is True
        return True, {"events": []}

    tool = ToolDefinition(name="calendar_list", description="list events",
                          parameters={"type": "object", "properties": {}}, handler=MagicMock(side_effect=handler))
    frames: list[str] = []
    token = llm_stats._current_session.set("s9")
    try:
        run_agent_loop(user_message="What's on today?", history_text="", preference_facts=[], tools=[tool],
                       ask_fn=ask, max_turns=3, on_thinking=frames.append)
    finally:
        llm_stats._current_session.reset(token)
    assert "and tomorrow too" not in prompts[0]
    assert any("USER ADDED WHILE YOU WORKED" in p and "and tomorrow too" in p for p in prompts[1:])
    assert any('"chat.steer_taken"' in f and "m7" in f for f in frames)
    assert steering._running == {}                             # the loop ended: nothing left for a later turn
