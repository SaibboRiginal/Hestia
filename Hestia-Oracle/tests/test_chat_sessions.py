"""Conversations: list, tags, pinned (Cindy 26, dossier 2026-10-24-tutto-brainstorm-cindy W7): tools chat_tag /
chat_list and the WebUI doors /api/ui/chats*, all passing through to Archive."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.services import chat_sessions


class FakeArchive:
    def __init__(self):
        self.calls = []
        self.meta = {"s2": {"title": None, "tags": [{"name": "casa", "color": "teal"}], "pinned": False}}

    def __call__(self, method, endpoint, body=None, query=None, timeout=6):
        self.calls.append((method, endpoint, body, query))
        if endpoint == "/chat/sessions/list":
            items = [{"session_id": "s2", "title": "Spese", "last_at": "2026-10-29T10:00:00", "pinned": False,
                      **self.meta["s2"]},
                     {"session_id": "s1", "title": "Palestra", "last_at": "2026-10-28T10:00:00", "pinned": False,
                      "tags": []}]
            if query and query.get("tag"):
                items = [i for i in items if any(t["name"] == query["tag"] for t in i["tags"])]
            return {"items": items[: int((query or {}).get("limit", 30))], "total": len(items)}
        if endpoint.startswith("/chat/sessions/") and method == "PUT":
            sid = endpoint.split("/")[3]
            before = dict(self.meta.get(sid) or {"title": None, "tags": [], "pinned": False})
            tags = list(before["tags"])
            if "tags" in body:
                tags = body["tags"]
            tags += [{"name": t["name"].lower(), "color": t["color"] or "blue"} for t in body.get("add_tags", [])]
            tags = [t for t in tags if t["name"] not in body.get("remove_tags", [])]
            self.meta[sid] = {"title": body.get("title", before["title"]), "tags": tags,
                              "pinned": body.get("pinned", before["pinned"])}
            return {"session_id": sid, **self.meta[sid], "before": before}
        if endpoint == "/chat/sessions/tags":
            return {"items": [{"name": "casa", "color": "teal", "count": 1}]}
        if endpoint.startswith("/chat/history/"):
            return [{"role": "user", "content": "ciao", "timestamp": "2026-10-29T10:00:00"}]
        return None


@pytest.mark.unit
def test_tag_without_session_takes_the_conversation_written_last_and_gives_undo():
    fake = FakeArchive()
    out = chat_sessions.tool_tag(fake, tags="Lavoro, urgente", color="red")
    assert out["session_id"] == "s2"
    assert [t["name"] for t in out["tags"]] == ["casa", "lavoro", "urgente"]
    assert out["undo"]["tool"] == "chat_tag"
    assert out["undo"]["args"]["replace"] == [{"name": "casa", "color": "teal"}]
    back = chat_sessions.tool_tag(fake, **out["undo"]["args"])
    assert back["tags"] == [{"name": "casa", "color": "teal"}]


@pytest.mark.unit
def test_list_filters_by_tag_and_draws_a_card():
    out = chat_sessions.tool_list(FakeArchive(), tag="casa")
    assert [i["session_id"] for i in out["items"]] == ["s2"]
    assert out["display"]["title"] == "Conversazioni" and "casa" in out["display"]["subtitle"]


@pytest.mark.unit
def test_archive_down_is_an_error_not_an_empty_list():
    with pytest.raises(chat_sessions.ChatSessionsError) as exc:
        chat_sessions.list_chats(lambda *a, **k: None)
    assert exc.value.status == 502


@pytest.fixture(scope="module")
def client():
    with patch("core.oracle_engine.OracleEngine", return_value=MagicMock()), patch("requests.post"):
        import main  # noqa: PLC0415
        yield main, TestClient(main.app)


@pytest.mark.api
def test_ui_doors_and_tools_registered(client):
    main, http = client
    fake = FakeArchive()
    with patch.object(main, "_chat_route", fake):
        assert http.get("/api/ui/chats", params={"tag": "casa"}).json()["items"][0]["session_id"] == "s2"
        assert http.get("/api/ui/chats/tags").json()["items"][0]["name"] == "casa"
        assert http.get("/api/ui/chats/s1/messages").json()["items"][0]["content"] == "ciao"
        r = http.put("/api/ui/chats/s1", json={"pinned": True, "add_tags": [{"name": "gym", "color": ""}]}).json()
        assert r["pinned"] is True and fake.calls[-1][2]["client"] == "webui"
    with patch.object(main, "_chat_route", lambda *a, **k: None):
        assert http.get("/api/ui/chats").status_code == 502
    names = {t.name for t in main._oracle_mcp_tools}
    assert {"chat_tag", "chat_list"} <= names
