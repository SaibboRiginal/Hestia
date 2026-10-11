"""Forge output that must fit a model window: the chat task list and the local engine prompt."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.forge.engines import BuiltinEngine
from app.forge.router import BRIEF_CHARS, brief


def _task(i: int, state: str = "awaiting_review", request: str = "Re-attivazione ciclo Athena " * 6) -> dict:
    return {"id": f"{i:06d}abcdef", "state": state, "services": ["athena"], "request": request}


@pytest.mark.unit
class TestBrief:
    def test_every_task_listed_with_its_request(self):
        out = brief([_task(i) for i in range(8)])
        assert out["total"] == 8 and len(out["tasks"]) == 8
        assert all("Re-attivazione" in line for line in out["tasks"])
        assert out["tasks"][0].startswith("000000 · awaiting_review · athena · ")
        assert "omitted" not in out

    def test_fits_oracle_tool_result_cap(self):
        """Regression: 8 full task records were cut by Oracle at 2000 chars after 2 tasks."""
        out = brief([_task(i) for i in range(8)])
        assert len(str(out)) < 2000

    def test_too_many_drops_oldest_closed_first(self):
        rows = [_task(0, "proposed")] + [_task(i, "deployed") for i in range(1, 60)]
        out = brief(rows)
        assert len(str(out)) < 2000
        assert out["tasks"][0].startswith("000000 · proposed")
        assert out["by_state"] == {"proposed": 1, "deployed": 59}
        assert "omitted" in out
        assert sum(len(line) for line in out["tasks"]) <= BRIEF_CHARS


def _engine(window: int) -> BuiltinEngine:
    eng = BuiltinEngine(MagicMock(), "local")
    eng.context_window = window
    return eng


@pytest.mark.unit
class TestEngineWindow:
    def test_budget_follows_window(self):
        assert _engine(0)._budget() == BuiltinEngine._CONTEXT_CHAR_BUDGET
        assert _engine(8192)._budget() == int(8192 * 3 * 0.7)

    def test_trim_shrinks_old_then_clips_latest(self):
        eng = _engine(8192)
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}]
        for _ in range(4):
            msgs += [{"role": "assistant", "content": ""}, {"role": "tool", "content": "x" * 20000}]
        eng._trim(msgs)
        assert sum(len(m["content"]) for m in msgs) <= eng._budget() + 100
        assert msgs[3]["content"] == "[old output trimmed]"
        assert "cut to fit the context window" in msgs[-1]["content"]

    def test_stop_reason(self):
        eng = _engine(8192)
        assert "context full (8192 token)" in eng._stop_reason(3, 40, "length")
        assert eng._stop_reason(40, 40, "stop").startswith("turn limit reached (40)")
        assert eng._stop_reason(5, 40, "stop") == "model stopped calling tools without finish"
