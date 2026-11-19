"""Tests — a background Ollama call the owner's turn can stop (dossier 2026-11-18-real-test-problems A). No network."""
from __future__ import annotations

import json
import threading

import pytest

from agents import universal_agent
from core.services import llm_bus


class _Resp:
    def __init__(self, lines, on_line=None):
        self.lines, self.on_line, self.closed = lines, on_line, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for i, line in enumerate(self.lines):
            if self.on_line:
                self.on_line(i)
            yield json.dumps(line).encode()


CHUNKS = [{"message": {"role": "assistant", "content": "Hel", "thinking": "hm"}, "done": False},
          {"message": {"role": "assistant", "content": "lo", "tool_calls": [{"function": {"name": "x"}}]}, "done": False},
          {"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 7, "prompt_eval_count": 3}]


def _as_background(fn):
    """Run *fn* like a background call holding the local worker (what the bus sets on the thread)."""
    llm_bus._held.cancel = threading.Event()
    try:
        with llm_bus.priority(llm_bus.BACKGROUND):
            return fn()
    finally:
        llm_bus._held.cancel = None


@pytest.mark.unit
def test_streamed_chunks_are_merged_like_one_answer(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None, stream=False):
        sent.update(json=json, stream=stream)
        return _Resp(CHUNKS)
    monkeypatch.setattr(universal_agent.requests, "post", fake_post)
    out = _as_background(lambda: universal_agent.ollama_post("http://o/api/chat", {"model": "m", "stream": False}, 30))
    assert sent["stream"] is True and sent["json"]["stream"] is True
    assert out["message"]["content"] == "Hello"
    assert out["message"]["thinking"] == "hm"
    assert out["message"]["tool_calls"] == [{"function": {"name": "x"}}]
    assert out["eval_count"] == 7 and out["done"] is True


@pytest.mark.unit
def test_stop_request_closes_the_call(monkeypatch):
    resp = _Resp(CHUNKS, on_line=lambda i: llm_bus._held.cancel.set() if i == 1 else None)
    monkeypatch.setattr(universal_agent.requests, "post", lambda *a, **k: resp)
    with pytest.raises(llm_bus.Preempted):
        _as_background(lambda: universal_agent.ollama_post("http://o/api/generate", {"model": "m"}, 30))
    assert resp.closed


@pytest.mark.unit
def test_owner_call_is_sent_as_before(monkeypatch):
    class Plain:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "ok"}
    seen = {}
    monkeypatch.setattr(universal_agent.requests, "post",
                        lambda url, json=None, timeout=None, **k: seen.update(k) or Plain())
    assert universal_agent.ollama_post("http://o/api/generate", {"model": "m"}, 30) == {"response": "ok"}
    assert "stream" not in seen
