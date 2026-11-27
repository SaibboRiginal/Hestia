"""A broken Telegram answer still arrives (docs/work/2026-11-27-chat-turn-survives): Oracle keeps running the turn,
the bot follows it again into the same message, or takes the saved answer from the conversation."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests


class _Renderer:
    def __init__(self):
        self.tokens, self.final = [], None
        self.finalized = False

    def on_token(self, t):
        self.tokens.append(t)

    def on_final(self, reply, origin=None, model=""):
        self.final, self.finalized = reply, True

    def on_status(self, *a):
        pass


class _Res:
    def __init__(self, status=200, lines=()):
        self.status_code, self._lines = status, lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_lines(self, **kw):
        for line in self._lines:
            if isinstance(line, Exception):
                raise line
            yield line


@pytest.fixture
def svc(monkeypatch):
    from telegram_bot import core
    from telegram_bot.services import chat_service
    monkeypatch.setattr(core, "resolve_oracle_chat_url", lambda: "http://oracle/api/chat")
    monkeypatch.setattr(core, "settings", SimpleNamespace(get=lambda *a, **k: 30))
    monkeypatch.setattr(chat_service.time, "sleep", lambda s: None)
    return chat_service


@pytest.mark.unit
def test_a_broken_stream_is_followed_again_from_where_it_stopped(svc, monkeypatch):
    calls = []

    def get(url, params=None, **kw):
        calls.append(params)
        if len(calls) == 1:
            raise requests.ConnectionError("hub restarting")
        return _Res(lines=[json.dumps({"type": "heartbeat"}).encode(),
                           json.dumps({"type": "final", "reply": "Done"}).encode()])

    monkeypatch.setattr(svc.requests, "get", get)
    r, progress = _Renderer(), {"lines": 3}
    svc.follow_live_turn("s1", "t1", r, [], [], progress, requests.ConnectionError("cut"))
    assert r.final == "Done" and calls[-1] == {"session_id": "s1", "offset": 3, "turn_id": "t1"}
    assert progress["lines"] == 4          # the heartbeat is not a frame of the turn


@pytest.mark.unit
def test_a_turn_no_longer_live_gives_its_saved_answer(svc, monkeypatch):
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _Res(status=404))
    monkeypatch.setattr(svc.catalog, "route", lambda *a, **k: (True, {"items": [
        {"role": "user", "content": "hi"}, {"role": "assistant", "content": "Saved answer"}]}))
    r = _Renderer()
    svc.follow_live_turn("s1", "t1", r, [], [], {"lines": 1}, requests.ConnectionError("cut"))
    assert r.final == "Saved answer"


@pytest.mark.unit
def test_no_answer_anywhere_raises_the_error(svc, monkeypatch):
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _Res(status=404))
    monkeypatch.setattr(svc.catalog, "route", lambda *a, **k: (True, {"items": [{"role": "user", "content": "hi"}]}))
    with pytest.raises(requests.ConnectionError):
        svc.follow_live_turn("s1", "t1", _Renderer(), [], [], {"lines": 1}, requests.ConnectionError("cut"))
