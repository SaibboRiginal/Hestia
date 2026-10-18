"""Tests — Argus "inside view" WebUI plugin (docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3/A6).

Manifest (kind core, Salute page, Stato sistema widget, Ricontrolla quick action, order 110), the in-memory
health history / incidents, the new read endpoints and the monitor hooks that feed them.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

# The docker SDK is only needed for argus.logs.source=docker; dev boxes may not have it installed.
sys.modules.setdefault("docker", types.ModuleType("docker"))

from core.ui_plugin import ui  # noqa: E402
from schemas.reports import HealthReport  # noqa: E402
from services import health_history as hh  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    hh.reset()
    yield
    hh.reset()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main as argus_main
    return TestClient(argus_main.app)   # no context manager: lifespan (Hub, monitor loop) not started


@pytest.mark.unit
class TestArgusManifest:
    def test_kind_pages_widgets_actions(self):
        m = ui.manifest()
        assert m["module"] == "argus" and m["kind"] == "core"
        webui = m["clients"]["webui"]
        assert webui["entry"] == "/ui/webui/argus.js" and webui["api_prefix"] == "/api/argus/"
        (p,) = webui["page"]
        assert (p["id"], p["label"], p["element"], p["order"]) == ("salute", "Salute", "argus-health", 110)
        (w,) = webui["widget"]
        assert (w["id"], w["label"], w["element"], w["auto"]) == ("stato", "Stato sistema", "argus-status-widget", True)
        (q,) = webui["quick_action"]
        assert q["path"] == "/api/argus/recheck/{id}" and q["source"] == "/api/argus/recheck-targets"
        assert q["method"] == "POST"

    def test_capabilities_in_hub_registration(self):
        from core import hub_client
        with patch.object(hub_client.requests, "post") as post:
            hub_client.register()
        caps = post.call_args.kwargs["json"]["capabilities"]
        assert caps["ui_manifest"].endswith("/api/ui/manifest") and caps["ui_version"]


@pytest.mark.unit
class TestHealthHistory:
    def test_strip_uptime_and_overview(self):
        now = 100_000.0 * 60
        for i in range(60):            # last hour: oracle up, then down in the last 10 minutes
            t = now - (60 - i) * 60 + 1
            hh.record("oracle", "down" if i >= 50 else "up", "Connection refused" if i >= 50 else None, at=t)
            hh.record("hub", "up", at=t)
        hist = hh.history(minutes=60, buckets=6, now=now)
        o = hist["services"]["oracle"]
        assert o["strip"] == "uuuuud" and o["status"] == "down" and o["uptime_pct"] == pytest.approx(83.3)
        assert hist["services"]["hub"]["strip"] == "uuuuuu"
        ov = hh.overview()
        assert (ov["total"], ov["healthy"], ov["unhealthy"]) == (2, 1, 1)
        assert ov["unhealthy_services"][0]["service"] == "oracle"

    def test_empty_buckets_are_dashes(self):
        now = 50_000.0 * 60
        hh.record("scout", "degraded", "HTTP 500", at=now - 30)
        assert hh.history(minutes=60, buckets=4, now=now)["services"]["scout"]["strip"] == "---w"

    def test_incident_lifecycle(self):
        assert hh.note_unhealthy("hecate", "down", "Connection refused") is True
        assert hh.note_unhealthy("hecate", "degraded", "HTTP 503") is False
        hh.note_action("hecate", "remediation", "Riparazione richiesta a Hephaestus", ok=True)
        hh.note_action("nobody", "alert", "ignored")
        inc = hh.incidents()
        assert inc["open_count"] == 1 and [a["kind"] for a in inc["open"][0]["actions"]] == \
            ["detected", "status", "remediation"]
        hh.note_recovered("hecate")
        inc = hh.incidents()
        assert inc["open"] == [] and inc["recent"][0]["status"] == "up"
        assert inc["recent"][0]["actions"][-1]["kind"] == "recovered"

    def test_recheck_targets(self):
        hh.record("oracle", "up")
        hh.record("scout", "down", "Connection refused")
        assert [c["id"] for c in hh.recheck_targets()] == ["scout"]
        assert hh.recheck_targets()[0]["label"] == "Ricontrolla scout"


@pytest.mark.unit
class TestMonitorHooks:
    def test_cycle_feeds_history_and_incidents(self):
        from services import monitor_service as ms
        down = {"scout": HealthReport(service="scout", status="down", error="Connection refused")}
        up = {"scout": HealthReport(service="scout", status="up")}
        with patch.object(ms.hub_client, "discover_services", return_value=[{"name": "scout"}]), \
                patch.object(ms, "send_alert"), patch.object(ms, "send_recovery"), \
                patch.object(ms, "_collect_new_log_events", return_value=[]), \
                patch.object(ms, "_report_degraded"), patch.object(ms, "_plan_recheck"), \
                patch.object(ms.cfg, "get_bool", return_value=False):
            with patch.object(ms.health_poller, "poll_all", return_value=down):
                ms._run_once()
            assert hh.incidents()["open"][0]["service"] == "scout"
            assert [a["kind"] for a in hh.incidents()["open"][0]["actions"]] == ["detected", "alert"]
            with patch.object(ms.health_poller, "poll_all", return_value=up):
                ms._run_once()
        assert hh.incidents()["open"] == [] and hh.incidents()["recent"][0]["service"] == "scout"
        assert hh.overview()["cycles"] == 2 and hh.overview()["healthy"] == 1
        ms._unhealthy.clear()


@pytest.mark.api
class TestArgusUiApi:
    def test_overview_history_incidents_targets(self, client):
        hh.record("scout", "down", "Connection refused")
        hh.note_unhealthy("scout", "down", "Connection refused")
        assert client.get("/api/argus/overview").json()["unhealthy"] == 1
        hist = client.get("/api/argus/history", params={"minutes": 60, "buckets": 12}).json()
        assert hist["buckets"] == 12 and len(hist["services"]["scout"]["strip"]) == 12
        assert client.get("/api/argus/history", params={"minutes": 99999}).status_code == 422
        assert client.get("/api/argus/incidents").json()["open"][0]["service"] == "scout"
        assert client.get("/api/argus/recheck-targets").json()["items"][0]["id"] == "scout"

    def test_manifest_served(self, client):
        body = client.get("/api/ui/manifest").json()
        assert body["module"] == "argus" and body["kind"] == "core"
