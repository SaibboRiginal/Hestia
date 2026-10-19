"""Tests — external AIs through an access (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2, §B6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.access as access_mod
import core.catalog as catalog_mod
import core.external as external_mod
import core.mcp_server as server_mod
from core.access import AccessStore, RateLimiter, hash_token, usable
from core.catalog import ToolCatalog, visible_to
from core.external import ExternalDoor, setup_lines
from core.mcp_server import MCPServer

COMMANDS = [
    {"command": "forge_tasks", "service": "hephaestus", "method": "GET", "path": "/api/forge/tasks/brief",
     "clients": ["telegram", "ui", "external"]},
    {"command": "forge_task_note", "service": "hephaestus", "method": "POST", "path": "/api/forge/tasks/$task_id/notes",
     "clients": ["ui", "external"]},
    {"command": "forge_approve", "service": "hephaestus", "method": "POST",
     "path": "/api/forge/tasks/$task_id/approve", "clients": ["telegram", "ui"]},
    {"command": "agenda_add", "service": "chronos", "method": "POST", "path": "/api/agenda/items"},
]


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class FakeArchive:
    """Archive's mcp-access store in memory, reached like through Hub."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.used = 0

    def __call__(self, method, path, body=None):
        base = "api/mcp-access-store/accesses"
        rest = path[len(base):].strip("/")
        if method == "GET" and not rest:
            return 200, {"accesses": [{k: v for k, v in r.items() if k != "token_hash"} for r in self.rows.values()]}
        if method == "POST" and not rest:
            self.rows[body["access_id"]] = {**body, "revoked_at": None, "calls_today": 0}
            return 200, {k: v for k, v in self.rows[body["access_id"]].items() if k != "token_hash"}
        if method == "GET" and rest.startswith("by-hash/"):
            digest = rest.split("/", 1)[1]
            row = next((r for r in self.rows.values() if r.get("token_hash") == digest), None)
            return (200, {k: v for k, v in row.items() if k != "token_hash"}) if row else (404, {"detail": "unknown"})
        access_id, _, action = rest.partition("/")
        row = self.rows.get(access_id)
        if row is None:
            return 404, {"detail": "access not found"}
        if action == "used":
            self.used += 1
            return 200, {"status": "ok"}
        if method == "PATCH":
            if "revoked" in body:
                row["revoked_at"] = datetime.now(timezone.utc).isoformat() if body.pop("revoked") else None
            row.update(body)
            return 200, {k: v for k, v in row.items() if k != "token_hash"}
        if method == "DELETE":
            self.rows.pop(access_id)
            return 200, {"status": "deleted"}
        return 400, {"detail": "?"}


@pytest.fixture
def rig(monkeypatch):
    routed, inbox = [], []
    monkeypatch.setattr(catalog_mod.requests, "get", lambda url, timeout=0: _Resp({"commands": COMMANDS}))

    def _post(url, json=None, timeout=0):
        if "/route/hermes/" in url:
            inbox.append(json["body"])
            return _Resp({"status_code": 200, "payload": {}})
        routed.append((url, json))
        return _Resp({"status_code": 200, "payload": {"task": {"id": "abc123"}}})
    monkeypatch.setattr(server_mod.requests, "post", _post)
    values = {"mcp.tools.cache_ttl": 60, "mcp.discovery.hub_timeout": 8, "mcp.calls.timeout": 10,
              "mcp.external.max_calls_per_min": 20}
    monkeypatch.setattr(catalog_mod.settings, "get", lambda k: values[k])
    monkeypatch.setattr(server_mod.settings, "get", lambda k: values[k])
    monkeypatch.setattr(external_mod.settings, "get", lambda k: values[k])

    class _Thread:   # background work runs inline in tests
        def __init__(self, target=None, **kw):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(external_mod.threading, "Thread", _Thread)
    monkeypatch.setattr(access_mod.threading, "Thread", _Thread)
    archive = FakeArchive()
    store = AccessStore("http://hub/api")
    monkeypatch.setattr(store, "_archive", archive)
    server = MCPServer(ToolCatalog("http://hub/api"), "http://hub/api")
    app = FastAPI()
    app.include_router(server.router())
    app.include_router(ExternalDoor(server, store, "http://hub/api").router())
    return TestClient(app), store, archive, routed, inbox, values


def _rpc(client, method, params=None, token="", msg_id=1):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/mcp/external", json={"jsonrpc": "2.0", "id": msg_id, "method": method,
                                              "params": params or {}}, headers=headers)


def _create(client, **body):
    resp = client.post("/api/mcp/accesses", json={"name": "Claude Code PC", **body},
                       params={"base_url": "https://hestia.example"})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.api
class TestAccesses:
    def test_create_shows_token_once_and_stores_only_a_hash(self, rig):
        c, _, archive, *_ = rig
        out = _create(c)
        token = out["token"]
        assert token.startswith("hst_") and token not in str(c.get("/api/mcp/accesses").json())
        row = next(iter(archive.rows.values()))
        assert row["token_hash"] == hash_token(token) and token not in str(row)
        assert out["setup"]["claude_code"].startswith("claude mcp add --transport http hestia https://hestia.example/mcp")

    def test_wrong_revoked_and_expired_tokens_get_401(self, rig):
        c, store, archive, *_ = rig
        assert _rpc(c, "tools/list").status_code == 401
        assert _rpc(c, "tools/list", token="hst_nope_nope_nope_nope").status_code == 401
        out = _create(c)
        assert _rpc(c, "tools/list", token=out["token"]).status_code == 200
        c.post(f"/api/mcp/accesses/{out['access']['access_id']}/revoke")
        resp = _rpc(c, "tools/list", token=out["token"])
        assert resp.status_code == 401
        challenge = resp.headers["www-authenticate"]     # tells OAuth clients where to start (RFC 9728)
        assert challenge.startswith('Bearer error="invalid_token"') and "/.well-known/oauth-protected-resource/mcp" in challenge
        renewed = c.post(f"/api/mcp/accesses/{out['access']['access_id']}/renew").json()
        assert _rpc(c, "tools/list", token=out["token"]).status_code == 401      # old token stops at once
        assert _rpc(c, "tools/list", token=renewed["token"]).status_code == 200
        archive.rows[out["access"]["access_id"]]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        store._forget()
        assert _rpc(c, "tools/list", token=renewed["token"]).status_code == 401

    def test_over_the_limit_gets_429(self, rig):
        c, *_, values = rig
        values["mcp.external.max_calls_per_min"] = 3
        token = _create(c)["token"]
        for i in range(3):
            assert _rpc(c, "ping", token=token, msg_id=i).status_code == 200
        resp = _rpc(c, "ping", token=token, msg_id=9)
        assert resp.status_code == 429 and resp.headers["retry-after"] == "60"


@pytest.mark.api
class TestExternalTools:
    def test_only_tools_marked_external_and_read_only_for_a_read_access(self, rig):
        c, *_ = rig
        token = _create(c, scope="read")["token"]
        names = [t["name"] for t in _rpc(c, "tools/list", token=token).json()["result"]["tools"]]
        assert names == ["forge_tasks"]
        write = _create(c, name="Cursor", scope="write")["token"]
        names = {t["name"] for t in _rpc(c, "tools/list", token=write).json()["result"]["tools"]}
        assert names == {"forge_tasks", "forge_task_note"}

    def test_read_access_calling_a_write_tool_gets_403(self, rig):
        c, _, _, routed, *_ = rig
        token = _create(c, scope="read")["token"]
        resp = _rpc(c, "tools/call", {"name": "forge_task_note", "arguments": {"task_id": "a", "text": "x"}}, token=token)
        assert resp.status_code == 403 and not routed

    def test_tool_list_of_an_access_and_hidden_tools(self, rig):
        c, *_ = rig
        token = _create(c, scope="write", tools=["forge_task_note"])["token"]
        names = [t["name"] for t in _rpc(c, "tools/list", token=token).json()["result"]["tools"]]
        assert names == ["forge_task_note"]
        for name in ("forge_tasks", "forge_approve", "agenda_add"):
            err = _rpc(c, "tools/call", {"name": name, "arguments": {"task_id": "a"}}, token=token).json()["error"]
            assert err["code"] == -32602

    def test_write_carries_access_name_never_the_callers_context_and_leaves_an_inbox_entry(self, rig):
        c, _, archive, routed, inbox, _ = rig
        token = _create(c, scope="write")["token"]
        res = _rpc(c, "tools/call", {"name": "forge_task_note", "arguments": {"task_id": "abc", "text": "causa: X"},
                                     "_meta": {"hestia": {"client": "telegram", "session_id": "s1",
                                                          "notify_target": "123"}}}, token=token).json()["result"]
        assert res["isError"] is False
        url, env = routed[-1]
        assert url.endswith("/route/hephaestus/api/forge/tasks/abc/notes")
        assert env["headers"] == {"X-Hestia-Access": "Claude Code PC"} and env["body"] == {"text": "causa: X"}
        assert inbox and inbox[-1]["metadata"]["quiet"] is True and "Claude Code PC" in inbox[-1]["message"]
        assert archive.used == 1

    def test_internal_mcp_is_unchanged(self, rig):
        c, *_ = rig
        out = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                     headers={"X-Hestia-Client": "telegram"}).json()
        assert {"forge_tasks", "forge_approve", "agenda_add"} <= {t["name"] for t in out["result"]["tools"]}


@pytest.mark.unit
class TestRules:
    def test_external_needs_explicit_flag(self):
        assert not visible_to({"clients": []}, "external") and not visible_to({"clients": ["*"]}, "external")
        assert visible_to({"clients": ["external"]}, "external") and visible_to({"clients": []}, "telegram")

    def test_usable_and_rate_limiter(self):
        now = datetime.now(timezone.utc)
        assert usable({"expires_at": (now + timedelta(days=1)).isoformat()}) == (True, "")
        assert usable({"revoked_at": now.isoformat()})[1] == "revoked"
        assert usable({"expires_at": (now - timedelta(seconds=1)).isoformat()})[1] == "expired"
        rl = RateLimiter()
        assert all(rl.allow("a", 2, now=t) for t in (0, 1)) and not rl.allow("a", 2, now=2) and rl.allow("a", 2, now=61)

    def test_setup_lines(self):
        lines = setup_lines("hst_x", "http://localhost:19015")
        assert lines["url"] == "http://localhost:19015/mcp" and '"Authorization": "Bearer hst_x"' in lines["json"]
