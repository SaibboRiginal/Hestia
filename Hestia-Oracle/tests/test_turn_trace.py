"""Turn traces for the training dataset (docs/work/2026-10-30-dataset-allenamento, D1). No network, no LLM."""
from __future__ import annotations

import json
import threading

import pytest

from core.services import turn_trace
from core.services.stream_emitter import emit_final, emit_tool_summary


class FakeHub:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok
        self.done = threading.Event()

    def route_to_service(self, service, path, method, body=None, query=None, timeout=15, headers=None):
        self.calls.append((service, path, method, body, query))
        self.done.set()
        return self.ok, {}


@pytest.mark.unit
def test_build_keeps_what_the_model_saw_and_did():
    log = [{"tool": "memory_save", "params": {"fact": "x"}, "ok": True, "writes": True, "turn": 0,
            "result_preview": "short", "result_text": "full result"}]
    t = turn_trace.build(trace_id="abc", session_id="s1", client="telegram", route="agent", mode="auto",
                         use_case="oracle.generale", model="m", provider="ollama", origin={"kind": "", "level": "utente"},
                         user_message="ciao", answer="fatto", history_text="H", system="SYS",
                         tools=[{"name": "memory_save", "description": "d", "parameters": {}}, {"bad": 1}],
                         tool_log=log, domains=["memory"], total_ms=12)
    assert t["trace_id"] == "abc" and t["system"] == "SYS" and t["history"] == "H"
    assert t["steps"] == [{"turn": 0, "tool": "memory_save", "params": {"fact": "x"}, "ok": True, "writes": True,
                           "result": "full result"}]
    assert [x["name"] for x in t["tools"]] == ["memory_save"]
    json.dumps(t)


@pytest.mark.unit
def test_build_cuts_long_fields():
    t = turn_trace.build(trace_id="a", session_id="s", client="", route="quick", mode="quick", use_case="u",
                         model="m", provider="p", origin=None, user_message="u", answer="a",
                         system="x" * 100_000, tool_log=[{"tool": "t", "ok": False, "result_text": "y" * 9000}])
    assert len(t["system"]) <= turn_trace._MAX_TEXT + 1
    assert len(t["steps"][0]["result"]) <= turn_trace._MAX_RESULT + 1


@pytest.mark.unit
@pytest.mark.parametrize("origin,save,sid,expected", [
    ({"level": "utente", "kind": ""}, True, "s", True),
    ({"level": "routine", "kind": "routine"}, True, "s", False),
    ({"level": "utente", "kind": "esterno"}, True, "s", False),
    ({"level": "utente"}, False, "s", False),
    ({"level": "utente"}, True, "", False),
])
def test_only_owner_turns_in_real_chats(origin, save, sid, expected):
    assert turn_trace.wanted(origin=origin, save_history=save, session_id=sid) is expected


@pytest.mark.unit
def test_send_and_forget_go_to_metis_in_background():
    hub = FakeHub(ok=False)
    turn_trace.send(hub, {"trace_id": "a"})
    assert hub.done.wait(2)
    assert hub.calls[0][:3] == ("metis", "api/metis/traces", "POST")
    hub2 = FakeHub()
    turn_trace.forget_session(hub2, "s1")
    assert hub2.done.wait(2)
    assert hub2.calls[0][2] == "DELETE" and hub2.calls[0][4] == {"session_id": "s1"}


@pytest.mark.unit
def test_final_frame_carries_trace_id_and_summary_hides_full_results():
    assert json.loads(emit_final("ok", trace_id="abc"))["trace_id"] == "abc"
    assert "trace_id" not in json.loads(emit_final("ok"))
    data = json.loads(emit_tool_summary([{"tool": "t", "ok": True, "result_text": "long"}]))
    assert "result_text" not in data["data"]["calls"][0]
