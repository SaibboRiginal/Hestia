"""Shaped outputs for small context windows: hestia_common.compact_output, the tool-result budget that follows the
window, and result_more (the rest of a shortened result on request). Dossier docs/work/2026-11-17-output-compatti."""
from __future__ import annotations

import json

import pytest

from core.agent_loop import (
    RESULT_MORE_TOOL,
    ScratchMessage,
    _result_more_tool,
    _stub_old_tool_results,
    tool_result_budget,
)
from hestia_common.compact_output import prune, shape, shape_text, tabulate


@pytest.mark.unit
class TestJsonShaping:
    def test_prune_keeps_false_and_zero(self):
        assert prune({"a": None, "b": "", "c": [], "d": {}, "e": False, "f": 0, "g": [None, 1]}) == \
            {"e": False, "f": 0, "g": [1]}

    def test_same_shaped_list_becomes_table(self):
        out = tabulate([{"id": i, "t": "x"} for i in range(3)])
        assert out == {"columns": ["id", "t"], "rows": [[0, "x"], [1, "x"], [2, "x"]]}

    def test_short_or_different_lists_stay_lists(self):
        assert tabulate([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}]
        mixed = [{"a": 1}, {"b": 2}, {"c": 3}, {"d": 4}]
        assert tabulate(mixed) == mixed

    def test_lossless_shaping_is_much_shorter(self):
        items = [{"id": i, "title": f"Event {i}", "start": "2026-11-17T10:00", "location": None, "notes": ""}
                 for i in range(40)]
        raw = json.dumps(items, indent=2)
        out = shape(raw, 0)
        assert not out.cut and len(out.text) < len(raw) * 0.4
        assert json.loads(out.text)["rows"][39][0] == 39

    def test_over_budget_keeps_errors_and_says_how_many(self):
        items = [{"id": i, "title": f"Event {i}"} for i in range(40)]
        items[30]["error"] = "conflict"
        out = shape({"ok": True, "events": items}, 400)
        assert out.cut and out.total_items == 40 and len(out.text) <= 400
        data = json.loads(out.text)
        assert data["events"]["more"].endswith("of 40")
        assert any(r[0] == 30 for r in data["events"]["rows"])   # the error item survived
        assert json.loads(out.full)["events"]["rows"][39][0] == 39   # full copy is whole

    def test_top_level_list_of_scalars_notes_the_count(self):
        out = shape(list(range(1000)), 200)
        assert out.cut and "of 1000]" in out.text

    def test_invalid_json_is_text(self):
        assert shape("{not json", 100).text == "{not json"


@pytest.mark.unit
class TestTextShaping:
    def test_repeated_lines_squeezed(self):
        assert shape_text("a\nb\nb\nb\nc", 0).text == "a\nb  [×3]\nc"

    def test_log_keeps_head_errors_and_tail(self):
        log = "\n".join(["start"] + [f"PASSED test_{i}" for i in range(300)]
                        + ["E   AssertionError: 1 != 2"] + [f"PASSED t2_{i}" for i in range(300)]
                        + ["=== 1 failed, 600 passed ==="])
        out = shape_text(log, 800)
        assert out.cut and len(out.text) <= 800
        assert out.text.startswith("start") and out.text.endswith("=== 1 failed, 600 passed ===")
        assert "AssertionError" in out.text and "lines omitted" in out.text

    def test_one_huge_line_is_cut_with_note(self):
        out = shape_text("x" * 5000, 300)
        assert out.cut and "of 5000 chars shown" in out.text


@pytest.mark.unit
class TestBudgetFollowsWindow:
    def _budget(self, window):
        return tool_result_budget(window, 3.0)

    def test_automatic_scales_with_window(self):
        small, mid, big = self._budget(16384), self._budget(32768), self._budget(262144)
        assert 1800 <= small <= 2100 and mid > small and big == 24000

    def test_unknown_window_uses_fallback_and_floor(self):
        assert self._budget(0) == self._budget(8192) >= 800


@pytest.mark.unit
class TestResultMore:
    def test_parts_and_unknown_ref(self):
        tool = _result_more_tool({"r1": "a" * 450}, 200)
        assert tool.name == RESULT_MORE_TOOL
        ok, first = tool.handler(ref="r1")
        assert ok and first.startswith("a" * 200) and "part 1 of 3" in first and "part=2" in first
        ok, last = tool.handler(ref="r1", part=9)
        assert ok and "part 3 of 3; last" in last
        ok, msg = tool.handler(ref="r7")
        assert not ok and "r1" in msg

    def test_stub_points_to_kept_copy(self):
        pad = [ScratchMessage("tool", "[a] → ✅ first\nrows", 0, ref="r1"),
               ScratchMessage("tool", "[b] → ✅ first\nrows", 0)]
        assert _stub_old_tool_results(pad, 4, 2, 60.0) == 2
        assert 'result_more(ref="r1")' in pad[0].content and pad[0].ref == "r1"
        assert "call the tool again" in pad[1].content
