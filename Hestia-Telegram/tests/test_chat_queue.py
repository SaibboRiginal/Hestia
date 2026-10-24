"""Oracle offline chat queue (docs/work/2026-10-19-oracle-offline §3)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests


class _Archive:
    """Fake Archive /api/chat-queue behind the Hub route."""

    def __init__(self):
        self.items: list[dict] = []

    def route(self, url, json=None, **kw):
        path, method, body = url.split("/route/archive/")[1], json["method"], json.get("body") or {}
        if method == "POST" and path == "api/chat-queue":
            item = {**body, "id": len(self.items) + 1, "state": "queued", "created_at": "2026-10-19T10:42:00+00:00"}
            self.items.append(item)
            payload = {**item, "position": sum(1 for i in self.items if i["state"] == "queued")}
        elif method == "GET":
            payload = {"items": [i for i in self.items if i["state"] == "queued"]}
        elif path.endswith("/claim"):
            item = self.items[int(path.split("/")[2]) - 1]
            if item["state"] != "queued":
                return MagicMock(status_code=200, json=lambda: {"status_code": 409, "payload": {}})
            item["state"] = "answering"
            payload = item
        else:  # done
            item = self.items[int(path.split("/")[2]) - 1]
            item["state"] = "answered" if body.get("ok") else "queued"
            payload = item
        return MagicMock(status_code=200, json=lambda p=payload: {"status_code": 200, "payload": p})


@pytest.fixture
def env(monkeypatch):
    import telegram_bot.core as core_module
    core_module.ALLOWED_USER_ID = "99999"
    bot = MagicMock()
    core_module.bot = bot
    archive = _Archive()
    oracle = {"up": False, "calls": []}

    class _Stream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self, **kw):
            yield json.dumps({"type": "final", "reply": "Eccomi"}).encode()

        def raise_for_status(self):
            pass

    def post(url, json=None, **kw):
        if "/route/archive/" in url:
            return archive.route(url, json=json)
        if "/route/" in url:   # settings and other Hub routes: not Oracle
            return MagicMock(status_code=503, json=lambda: {})
        oracle["calls"].append(json)
        if not oracle["up"]:
            raise requests.ConnectionError("connection refused")
        return _Stream()

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", lambda *a, **kw: MagicMock(status_code=404, ok=False, json=lambda: {}))
    return bot, archive, oracle


@pytest.mark.unit
def test_offline_message_is_queued_with_fixed_reply(env, fake_message):
    bot, archive, _ = env
    from telegram_bot.services.chat_service import handle_chat_message
    with patch("session_store.get_session", return_value="s-1"), \
            patch("session_store.build_client_instructions_for_chat", return_value=""):
        handle_chat_message(fake_message(text="Ci sei?", chat_id=12345, message_id=7))
    assert [(i["text"], i["client_ref"], i["target"]) for i in archive.items] == [("Ci sei?", "7", "12345")]
    text = bot.edit_message_text.call_args[0][0]
    assert "Non disponibile" in text and "in coda" in text


@pytest.mark.unit
def test_drain_answers_a_chat_in_one_turn_and_once(env):
    """v3 C: every queued message of a chat goes to the assistant in one turn; it decides how to answer."""
    bot, archive, oracle = env
    from telegram_bot.services import chat_queue
    chat_queue.enqueue(12345, "s-1", "primo", 7)
    chat_queue.enqueue(12345, "s-1", "secondo", 8)
    chat_queue.enqueue(555, "s-2", "altra chat", 3)
    oracle["up"] = True
    out = chat_queue.drain("test")
    assert out["answered"] == 3
    assert [[q["text"] for q in c["queued"]] for c in oracle["calls"]] == [["primo", "secondo"], ["altra chat"]]
    assert oracle["calls"][0]["queued"][0]["written_at"] == "2026-10-19T10:42:00+00:00"
    assert all(i["state"] == "answered" for i in archive.items)
    replies = [c.kwargs.get("reply_to_message_id") for c in bot.send_message.call_args_list
               if c.kwargs.get("reply_to_message_id")]
    assert replies == [8, 3]   # under the last message of each chat
    assert chat_queue.drain("again")["answered"] == 0


@pytest.mark.unit
def test_drain_stops_when_still_offline(env):
    _, archive, oracle = env
    from telegram_bot.services import chat_queue
    chat_queue.enqueue(12345, "s-1", "primo", 7)
    chat_queue.enqueue(12345, "s-1", "secondo", 8)
    out = chat_queue.drain("test")
    assert out == {"status": "ok", "answered": 0, "failed": 2}
    assert len(oracle["calls"]) == 1 and all(i["state"] == "queued" for i in archive.items)
