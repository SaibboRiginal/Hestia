"""A chat turn survives the client leaving (docs/work/2026-11-27-chat-turn-survives).

Regression: the owner wrote, left the page while the answer was thinking, came back → his message and the answer
were gone (the client dropped the connection, the turn stopped, history was saved only at the end)."""
from __future__ import annotations

import json
import threading
import time

import pytest

from core.services import live_turns


def _line(**frame) -> str:
    return json.dumps(frame) + "\n"


@pytest.fixture(autouse=True)
def _clean():
    live_turns.reset()
    yield
    live_turns.reset()


@pytest.mark.unit
def test_the_turn_ends_even_when_the_reader_leaves():
    gate = threading.Event()
    ended = threading.Event()

    def turn():
        yield _line(type="status", content="thinking")
        gate.wait(2)
        yield _line(type="token", text="Hi")
        yield _line(type="final", reply="Hi!")
        ended.set()

    t = live_turns.start("s1", turn(), user_message="hello")
    reader = live_turns.follow(t, heartbeat_s=0.05)
    assert json.loads(next(reader))["type"] == "status"
    reader.close()                       # the owner left the page
    gate.set()
    assert ended.wait(2)                 # the turn still went to its end (and its own code saved the answer)
    for _ in range(100):
        if t.done:
            break
        time.sleep(0.01)
    snap = live_turns.current("s1").snapshot()
    assert snap["running"] is False and snap["text"] == "Hi!" and snap["user_message"] == "hello"


@pytest.mark.unit
def test_coming_back_replays_the_whole_turn_and_follows_it_live():
    gate = threading.Event()

    def turn():
        yield _line(type="thinking", action="tool", content="calendar")
        yield _line(type="token", text="Tomorrow ")
        gate.wait(2)
        yield _line(type="token", text="free")
        yield _line(type="final", reply="Tomorrow free")

    t = live_turns.start("s1", turn())
    for _ in range(100):
        if len(t.events) >= 2:
            break
        time.sleep(0.01)
    assert live_turns.current("s1").snapshot()["text"] == "Tomorrow "
    gate.set()
    frames = [json.loads(x) for x in live_turns.follow(live_turns.get("s1"), 0, heartbeat_s=0.05)]
    types = [f["type"] for f in frames if f["type"] != "heartbeat"]
    assert types == ["thinking", "token", "token", "final"]
    tail = [json.loads(x)["type"] for x in live_turns.follow(t, 3)]
    assert tail == ["final"]


@pytest.mark.unit
def test_a_silent_turn_sends_heartbeats_so_no_timeout_cuts_it():
    gate = threading.Event()

    def turn():
        gate.wait(2)                     # a local model waiting in line
        yield _line(type="final", reply="ok")

    t = live_turns.start("s1", turn())
    reader = live_turns.follow(t, heartbeat_s=0.02)
    assert json.loads(next(reader))["type"] == "heartbeat"
    gate.set()
    rest = [json.loads(x)["type"] for x in reader]
    assert rest[-1] == "final"


@pytest.mark.unit
def test_only_stop_stops_a_turn():
    def turn():
        for i in range(200):
            time.sleep(0.01)
            yield _line(type="token", text=str(i))

    t = live_turns.start("s1", turn())
    time.sleep(0.05)
    assert live_turns.stop("s1") == 1
    for _ in range(100):
        if t.done:
            break
        time.sleep(0.01)
    assert t.done and t.stopped and len(t.events) < 200
    assert live_turns.stop("s1") == 0 and live_turns.stop("nobody") == 0


@pytest.mark.unit
def test_a_crash_of_the_stream_ends_the_turn_with_an_error_frame():
    def turn():
        yield _line(type="status", content="x")
        raise RuntimeError("boom")

    t = live_turns.start("s1", turn())
    frames = [json.loads(x) for x in live_turns.follow(t, heartbeat_s=0.05)]
    assert frames[-1]["type"] == "error" and t.done


@pytest.mark.api
def test_chat_endpoints_follow_and_stop_the_live_turn(monkeypatch):
    import main
    gate = threading.Event()

    def fake_chat(message, session_id, **kw):
        yield _line(type="token", text="A")
        gate.wait(2)
        yield _line(type="final", reply="A!")

    monkeypatch.setattr(main.engine, "chat", fake_chat)
    monkeypatch.setattr(main, "_no_usable_model", lambda: False)
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    threading.Timer(0.2, gate.set).start()
    res = client.post("/api/chat", json={"message": "hi", "session_id": "live-s", "client": "webui"})
    assert res.status_code == 200 and res.headers.get("X-Hestia-Turn")
    assert [json.loads(x)["type"] for x in res.text.splitlines() if x][-1] == "final"
    live = client.get("/api/chat/live", params={"session_id": "live-s"}).json()["turn"]
    assert live["user_message"] == "hi" and live["text"] == "A!" and live["running"] is False
    again = client.get("/api/chat/live/stream", params={"session_id": "live-s", "offset": 1})
    assert [json.loads(x)["type"] for x in again.text.splitlines() if x] == ["final"]
    assert client.get("/api/chat/live/stream", params={"session_id": "none"}).status_code == 404
    assert client.post("/api/chat/stop", json={"session_id": "live-s"}).json()["stopped"] == 0


@pytest.mark.unit
def test_engine_saves_his_message_before_the_answer():
    from unittest.mock import MagicMock
    from core.oracle_engine import OracleEngine
    eng = OracleEngine.__new__(OracleEngine)
    eng._hub = MagicMock()
    eng._trace_headers = lambda *a, **k: {}
    assert eng._save_user_message("s1", "hello") is True
    eng._save_history("s1", "hello", "hi", user_saved=True)
    roles = [c.args[1]["role"] for c in eng._hub.post.call_args_list]
    assert roles == ["user", "assistant"]          # once each, his first


@pytest.mark.unit
def test_the_reasoning_shown_is_saved_with_the_answer():
    seen = {}

    def turn():
        yield _line(type="thinking", action="reasoning", content="Checking the agenda")
        yield _line(type="agent", event="start", agent_id="a1", module="chronos", label="Agenda", task="tomorrow")
        yield _line(type="token", text="Free")
        seen["steps"] = live_turns.steps()       # what the engine saves with the answer, at this point
        yield _line(type="final", reply="Free")

    t = live_turns.start("s1", turn())
    list(live_turns.follow(t, heartbeat_s=0.05))
    assert [s["type"] for s in seen["steps"]] == ["thinking", "agent"]
    assert live_turns.steps() == []                # outside a live turn: nothing
