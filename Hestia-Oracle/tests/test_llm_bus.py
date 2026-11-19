"""Tests — LLM bus: one queue for local model calls, owner chat first (dossier 2026-11-16-bus-llm).
No network: providers and settings are patched."""
from __future__ import annotations

import threading
import time

import pytest

from core.services import llm_bus


@pytest.fixture(autouse=True)
def _local_only(monkeypatch):
    """Providers named ``loc*`` are local, everything else cloud; one worker unless a test says otherwise."""
    monkeypatch.setattr(llm_bus, "_is_local", lambda provider: str(provider).startswith("loc"))
    monkeypatch.setattr(llm_bus, "workers", lambda: 1)
    yield
    assert llm_bus.status()["running"] == 0


def _hold(release: threading.Event, started: threading.Event, provider="loc"):
    with llm_bus.slot(provider):
        started.set()
        release.wait(5)


def _wait_queued(n: int, timeout: float = 3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = llm_bus.status()["waiting"]
        if st["chat"] + st["background"] >= n:
            return
        time.sleep(0.01)
    raise AssertionError("calls never queued")


@pytest.mark.unit
def test_owner_chat_goes_ahead_of_background():
    release, started, order = threading.Event(), threading.Event(), []
    holder = threading.Thread(target=_hold, args=(release, started))
    holder.start()
    assert started.wait(3)

    def call(level, name):
        with llm_bus.priority(level):
            with llm_bus.slot("loc"):
                order.append(name)

    bg = threading.Thread(target=call, args=(llm_bus.BACKGROUND, "recap"))
    bg.start()
    _wait_queued(1)
    chat = threading.Thread(target=call, args=(llm_bus.CHAT, "chat"))
    chat.start()
    _wait_queued(2)
    release.set()
    for t in (holder, bg, chat):
        t.join(5)
    assert order == ["chat", "recap"]


@pytest.mark.unit
def test_same_priority_keeps_arrival_order():
    release, started, order = threading.Event(), threading.Event(), []
    holder = threading.Thread(target=_hold, args=(release, started))
    holder.start()
    assert started.wait(3)
    threads = []

    def call(i):
        with llm_bus.slot("loc"):
            order.append(i)

    for i in range(3):
        t = threading.Thread(target=call, args=(i,))
        threads.append(t)
        t.start()
        _wait_queued(i + 1)
    release.set()
    for t in [holder, *threads]:
        t.join(5)
    assert order == [0, 1, 2]


@pytest.mark.unit
def test_cloud_never_waits_for_the_local_worker():
    release, started = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold, args=(release, started))
    holder.start()
    assert started.wait(3)
    t0 = time.monotonic()
    with llm_bus.slot("gemini"):
        pass
    assert time.monotonic() - t0 < 0.5
    release.set()
    holder.join(5)


@pytest.mark.unit
def test_nested_call_on_same_thread_does_not_deadlock():
    done = []

    def run():
        with llm_bus.slot("loc"):
            with llm_bus.slot("loc"):        # e.g. a provider asking another chain while it answers
                done.append(True)

    t = threading.Thread(target=run)
    t.start()
    t.join(3)
    assert done == [True]


@pytest.mark.unit
def test_two_workers_run_together(monkeypatch):
    monkeypatch.setattr(llm_bus, "workers", lambda: 2)
    release = threading.Event()
    started = [threading.Event(), threading.Event()]
    threads = [threading.Thread(target=_hold, args=(release, s)) for s in started]
    for t in threads:
        t.start()
    assert all(s.wait(3) for s in started)
    assert llm_bus.status()["running"] == 2
    release.set()
    for t in threads:
        t.join(5)


@pytest.mark.unit
def test_stream_rebinds_priority_on_every_step():
    seen = []

    def gen():
        for _ in range(3):
            seen.append(llm_bus.current())
            yield "x"

    assert list(llm_bus.bind(gen(), llm_bus.CHAT)) == ["x", "x", "x"]
    assert seen == [llm_bus.CHAT] * 3
    assert llm_bus.current() == llm_bus.BACKGROUND


@pytest.mark.unit
def test_origin_and_module_promotion():
    assert llm_bus.for_origin({"level": "utente"}) == llm_bus.CHAT
    assert llm_bus.for_origin({"level": "routine"}) == llm_bus.BACKGROUND
    assert llm_bus.module_priority({"level": "autonomo"}) == llm_bus.BACKGROUND
    with llm_bus.priority(llm_bus.CHAT):
        with llm_bus.owner_waiting():
            # a module call arriving while the owner's turn waits for a tool is that tool's work
            assert llm_bus.module_priority({"level": "autonomo"}) == llm_bus.CHAT
    assert llm_bus.module_priority({"level": "autonomo"}) == llm_bus.BACKGROUND
    with llm_bus.owner_waiting():                 # a background turn waiting for tools promotes nothing
        assert llm_bus.module_priority({"level": "autonomo"}) == llm_bus.BACKGROUND


@pytest.mark.unit
def test_chain_agent_takes_a_slot_for_local_steps_but_not_for_embeddings(monkeypatch):
    from core.services import llm_chains
    taken = []

    class _Slot:
        def __init__(self, provider, use_case="", mark=True):
            taken.append(provider)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Agent:
        provider_name, model_name, thinking = "loc", "m", False

        def ask(self, *a, **k):
            return "ok"

        def embed(self, *a, **k):
            return [0.1]

    from core.services import llm_usage
    monkeypatch.setattr(llm_bus, "slot", _Slot)
    monkeypatch.setattr(llm_usage, "finish", lambda *a, **k: {})
    agent = llm_chains.ChainAgent("oracle.general")
    monkeypatch.setattr(agent, "steps", lambda: [(0, {"provider": "loc", "model": "m"}, _Agent())])
    monkeypatch.setattr(agent, "_answered", lambda *a: None)
    monkeypatch.setattr(agent, "_usage", lambda *a: _Slot("usage"))
    taken.clear()
    assert agent.ask("hi") == "ok"
    assert taken == ["usage", "loc"]
    taken.clear()
    assert agent.embed("hi") == [0.1]
    assert taken == ["usage"]


# ── dossier 2026-11-18-real-test-problems A: deadline and the owner's turn over a running call ──────────────

@pytest.mark.unit
def test_call_whose_caller_gave_up_never_runs():
    release, started = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold, args=(release, started))
    holder.start()
    assert started.wait(3)
    ran = []
    try:
        with llm_bus.deadline(time.time() + 1.3):    # 1 s margin: gives up after ~0.3 s
            with pytest.raises(llm_bus.Expired):
                with llm_bus.slot("loc"):
                    ran.append(1)
    finally:
        release.set()
        holder.join(5)
    assert ran == []
    assert llm_bus.status()["waiting"] == {"chat": 0, "background": 0}


@pytest.mark.unit
def test_deadline_header_read_case_insensitive():
    assert llm_bus.deadline_from_headers({"X-Hestia-Deadline": "123.5"}) == 123.5
    assert llm_bus.deadline_from_headers({"x-hestia-deadline": "bad"}) == 0.0
    assert llm_bus.deadline_from_headers({}) == 0.0


@pytest.mark.unit
def test_owner_turn_asks_the_running_background_call_to_stop():
    started, stopped, order = threading.Event(), threading.Event(), []

    def background():
        with llm_bus.priority(llm_bus.BACKGROUND):
            with llm_bus.slot("loc"):
                started.set()
                end = time.monotonic() + 5
                while time.monotonic() < end and not llm_bus.cancel_requested():
                    time.sleep(0.01)
                if llm_bus.cancel_requested():
                    stopped.set()

    def chat():
        with llm_bus.priority(llm_bus.CHAT):
            with llm_bus.slot("loc"):
                order.append("chat")

    bg = threading.Thread(target=background)
    bg.start()
    assert started.wait(3)
    ch = threading.Thread(target=chat)
    ch.start()
    for t in (bg, ch):
        t.join(5)
    assert stopped.is_set() and order == ["chat"]


@pytest.mark.unit
def test_chain_puts_a_stopped_call_back_in_line(monkeypatch):
    from core.services import llm_chains
    calls = []

    def run():
        calls.append(1)
        if len(calls) == 1:
            raise llm_bus.Preempted("owner")
        return "done"

    assert llm_chains._in_line("loc", "test", run) == "done"
    assert len(calls) == 2


@pytest.mark.unit
def test_busy_with_background():
    release, started = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold, args=(release, started))
    holder.start()
    assert started.wait(3)
    try:
        assert llm_bus.busy_with_background()
    finally:
        release.set()
        holder.join(5)
    assert not llm_bus.busy_with_background()
