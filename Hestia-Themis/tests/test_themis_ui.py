"""Themis inside view (WebUI plugin «Registro»): manifest, GET /api/settings/history (all keys, paged),
proposals status=all. SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Archive is mocked.

Markers: unit, api
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("THEMIS_DATA_DIR", tempfile.mkdtemp(prefix="themis-test-"))

from app.core.hub import HubError
from app.core.registry import Registry
from app.core.service import Themis
from hestia_common.settings_client import setting

HISTORY = [   # newest first, as Archive returns it
    {"id": 9, "key": "argus.poll.interval", "scope": "system", "scope_id": "", "old_value": 60, "new_value": 30,
     "actor": "user", "reason": "annulla", "created_at": "2026-10-18T10:00:00"},
    {"id": 8, "key": "oracle.chat.tone", "scope": "session", "scope_id": "s1", "old_value": None,
     "new_value": "warm", "actor": "webui", "reason": "nuova sessione", "created_at": "2026-10-18T09:30:00"},
    {"id": 7, "key": "argus.poll.interval", "scope": "system", "scope_id": "", "old_value": 30, "new_value": 60,
     "actor": "athena", "reason": "proposta approvata (telegram): meno carico", "created_at": "2026-10-18T09:00:00"},
    {"id": 6, "key": "argus.mode", "scope": "system", "scope_id": "", "old_value": "normal", "new_value": None,
     "actor": "external:claude-pc", "reason": "reset", "created_at": "2026-10-18T08:00:00"},
    {"id": 5, "key": "gone.setting", "scope": "system", "scope_id": "", "old_value": 1, "new_value": 2,
     "actor": "oracle", "reason": None, "created_at": "2026-10-18T07:00:00"},
]


class FakeHub:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def ok(self, svc, method, path, body=None, query=None, timeout=8):
        self.queries.append((path, query))
        if path == "api/settings-store/history":
            key = (query or {}).get("key")
            return [r for r in self.rows if not key or r["key"] == key]
        if path == "api/settings-store/proposals":
            return [{"proposal_id": "p1", "key": "argus.mode", "status": "rejected", "value": "calm"},
                    {"proposal_id": "p2", "key": "argus.mode", "status": "pending", "value": "calm"}]
        raise HubError(404)

    def call(self, *a, **kw):
        return 200, {}


def _themis(rows=HISTORY):
    reg = Registry(None)
    reg.register("argus", [setting("argus.poll.interval", "Intervallo", "int", 30),
                           setting("argus.mode", "Modo", "enum", "normal", options=["calm", "normal"])])
    reg.register("oracle", [setting("oracle.chat.tone", "Tono", "enum", "warm", scope="user",
                                    options=["warm", "neutral"])])
    return Themis(FakeHub(rows), reg)


@pytest.mark.unit
class TestHistoryAll:
    def test_all_keys_newest_first_without_sessions(self):
        out = _themis().history_all()
        assert [r["id"] for r in out["items"]] == [9, 7, 6, 5]
        assert out["total"] == 4 and out["next_offset"] is None and out["keep_per_key"] == 10
        by_id = {r["id"]: r for r in out["items"]}
        assert by_id[9]["kind"] == "undo" and by_id[7]["kind"] == "approved" and by_id[6]["kind"] == "reset"
        assert by_id[9]["label"] == "Intervallo" and by_id[9]["module"] == "argus"

    def test_undoable_only_latest_known_change(self):
        by_id = {r["id"]: r for r in _themis().history_all(sessions=True)["items"]}
        assert by_id[9]["undoable"] and not by_id[7]["undoable"]      # 7 is no longer the latest
        assert by_id[6]["undoable"]
        assert not by_id[5]["undoable"]                              # setting no longer declared
        assert not by_id[8]["undoable"] and by_id[8]["latest"]       # session copies are never undone here

    def test_filters_and_paging(self):
        t = _themis()
        assert [r["id"] for r in t.history_all(actor="external")["items"]] == [6]
        assert [r["id"] for r in t.history_all(actor="user,athena")["items"]] == [9, 7]
        assert [r["id"] for r in t.history_all(module="argus")["items"]] == [9, 7, 6]
        page = t.history_all(limit=2)
        assert [r["id"] for r in page["items"]] == [9, 7] and page["next_offset"] == 2
        assert [r["id"] for r in t.history_all(limit=2, offset=2)["items"]] == [6, 5]

    def test_key_filter_goes_to_archive(self):
        t = _themis()
        t.history_all(key="argus.mode")
        assert t.hub.queries[-1] == ("api/settings-store/history", {"key": "argus.mode", "limit": 500})


@pytest.mark.api
class TestUiEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import app.main as themis_main
        return TestClient(themis_main.app, raise_server_exceptions=False), themis_main

    def test_manifest_is_core_plugin(self, client):
        c, _ = client
        m = c.get("/api/ui/manifest").json()
        assert m["module"] == "themis" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["api_prefix"] == "/api/settings/" and web["entry"] == "/ui/webui/themis.js"
        assert web["page"][0]["id"] == "registro" and web["page"][0]["order"] == 160
        assert web["widget"] == []

    def test_history_endpoint(self, client):
        c, main = client
        with patch.object(main.themis, "hub", FakeHub(HISTORY)), patch.object(main.themis, "registry", _themis().registry):
            body = c.get("/api/settings/history", params={"limit": 1}).json()
            assert body["items"][0]["id"] == 9 and body["next_offset"] == 1
            props = c.get("/api/settings/proposals", params={"status": "all"}).json()["proposals"]
            assert {p["proposal_id"] for p in props} == {"p1", "p2"}
            pending = c.get("/api/settings/proposals").json()["proposals"]
            assert [p["proposal_id"] for p in pending] == ["p2"]
