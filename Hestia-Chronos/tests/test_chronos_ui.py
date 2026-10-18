"""Chronos inside view (WebUI plugin «Esecuzioni»): manifest, /api/agenda/runs, /api/agenda/runs/failed.

SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Archive is mocked (agenda rows in memory).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _row(rid, key, owner, *, type_="job", status="confirmed", runs=None, skips=None, last=None, action=True,
         user_modified=False):
    return {"id": rid, "external_id": key, "title": f"Job {key}", "start_at": "2026-10-01T00:00:00+00:00",
            "recurrence": "RRULE:FREQ=HOURLY", "status": status, "kind": type_,
            "meta": {"type": type_, "owner": owner, "runs": runs or [], "skips": skips or [],
                     "last_result": last, "user_modified": user_modified,
                     "action": {"service": owner, "path": "/x"} if action else None}}


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


ROWS = [
    _row(1, "scout.mail", "scout", runs=[
        {"occurrence": _iso(3), "ok": True, "at": _iso(3), "by": "agenda", "duration_ms": 200},
        {"occurrence": _iso(2), "ok": False, "at": _iso(2), "by": "agenda", "duration_ms": 400, "detail": "502: x"}],
        skips=[_iso(1), (NOW + timedelta(hours=5)).isoformat()],
        last={"ok": False, "at": _iso(2), "detail": "502: x"}),
    _row(2, "hermes.retract", "hermes", runs=[
        {"occurrence": f"manual:{_iso(30)}", "ok": True, "at": _iso(30), "by": "user", "duration_ms": 50}],
        user_modified=True),
    _row(3, "forge.fix", "hephaestus", type_="task", status="failed", last={"ok": False, "at": _iso(80)}),
    _row(4, "chronos.night", "chronos", type_="window", action=False),
]


@pytest.fixture
def agenda():
    from services import agenda as A
    with patch.object(A, "_raw_items", return_value=ROWS):
        yield A


@pytest.mark.unit
class TestRuns:
    def test_runs_newest_first_with_skips(self, agenda):
        out = agenda.runs(now=NOW)
        assert [(r["key"], r["status"]) for r in out["runs"]] == [
            ("scout.mail", "skipped"), ("scout.mail", "failed"), ("scout.mail", "ok"), ("hermes.retract", "ok")]
        assert out["summary"] == {"ok": 2, "failed": 1, "skipped": 1, "avg_ms": 216, "failed_items": 1}
        manual = out["runs"][-1]
        assert manual["manual"] and manual["by"] == "user" and manual["can_run"]

    def test_filters(self, agenda):
        assert agenda.runs(status="failed", now=NOW)["count"] == 1
        assert agenda.runs(owner="hermes", now=NOW)["count"] == 1
        assert agenda.runs(since=NOW - timedelta(hours=24), now=NOW)["count"] == 3
        with pytest.raises(agenda.AgendaError):
            agenda.runs(status="boh")

    def test_owners(self, agenda):
        owners = {o["owner"]: o for o in agenda.runs(now=NOW)["owners"]}
        assert set(owners) == {"scout", "hermes", "hephaestus", "chronos"}
        assert owners["hephaestus"]["failed"] == 1 and owners["hephaestus"]["active"] == 0
        assert owners["hermes"]["user_modified"] == 1 and owners["chronos"]["types"] == {"window": 1}

    def test_failed_jobs_chips(self, agenda):
        chips = agenda.failed_jobs(now=NOW)
        assert [c["id"] for c in chips] == ["scout.mail", "forge.fix"]   # stopped task stays until retried
        assert chips[0]["label"] == "Job scout.mail" and chips[0]["state"] == "late"
        assert agenda.failed_jobs(since=NOW - timedelta(hours=1), now=NOW)[0]["id"] == "forge.fix"


def _client():
    from fastapi.testclient import TestClient
    with patch("requests.post"), patch("requests.get"), \
            patch("core.hub_client.register_on_hub"), \
            patch("services.sync_worker.start", MagicMock()), \
            patch("services.notification_worker.start", MagicMock()), \
            patch("hestia_common.startup_utils.wait_for_http_ready"):
        import main as chronos_main
        return TestClient(chronos_main.app, raise_server_exceptions=False)


@pytest.mark.api
class TestUiEndpoints:
    def test_manifest_is_core_plugin(self):
        m = _client().get("/api/ui/manifest").json()
        assert m["module"] == "chronos" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["api_prefix"] == "/api/agenda/" and web["entry"] == "/ui/webui/chronos.js"
        assert web["page"][0]["id"] == "esecuzioni" and web["page"][0]["order"] == 150
        assert web["widget"][0]["id"] == "falliti"
        qa = web["quick_action"][0]
        assert qa["path"] == "/api/agenda/items/{id}/run" and qa["source"] == "/api/agenda/runs/failed"

    def test_runs_endpoint(self, agenda):
        client = _client()
        body = client.get("/api/agenda/runs", params={"status": "failed"}).json()
        assert body["count"] == 1 and body["runs"][0]["detail"] == "502: x"
        assert client.get("/api/agenda/runs", params={"status": "x"}).status_code == 400
        assert client.get("/api/agenda/runs", params={"since": "ieri"}).status_code == 400

    def test_failed_endpoint(self, agenda):
        rows = _client().get("/api/agenda/runs/failed", params={"hours": 24 * 30}).json()
        assert {r["id"] for r in rows} >= {"forge.fix"}
