"""Hermes inside view (WebUI plugin «Consegne»): manifest + /api/ui/* reads.

SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Archive is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _row(nid, state="delivered", **extra):
    notification = {"title": "Titolo", "message": "<b>Ciao</b> &amp; benvenuto", "level": "info",
                    "source": "scout", "audience": "global", "actions": [], **extra.pop("n", {})}
    payload = {"notification": notification, "deliveries": extra.pop("deliveries", {}), **extra}
    return {"outbound_event_id": nid, "lifecycle_state": state, "created_at": "2026-10-18T08:00:00+00:00",
            "event_type": "entity.upserted", "domain": "real_estate", "payload": payload}


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient
    with patch("requests.post"), patch("requests.get"), \
            patch("hestia_common.startup_utils.wait_for_http_ready"):
        import src.main as hermes_main
        client = TestClient(hermes_main.app, raise_server_exceptions=False)
    return client, hermes_main


@pytest.mark.unit
class TestDeliveryView:
    def test_flags_and_clients(self):
        from modules.ui_view import delivery_view
        v = delivery_view(_row("n1", n={"held": "important", "quiet": True}, deliveries={
            "telegram": {"state": "delivered", "at": "t", "ref": "9", "retracted": "t2"},
            "webui": {"state": "failed", "attempts": 3, "detail": "<i>timeout</i>"}}))
        assert v["preview"] == "Ciao & benvenuto"
        assert v["flags"]["held"] == "important" and v["flags"]["quiet"] and v["flags"]["retracted"]
        assert v["flags"]["failed"] and not v["flags"]["answered"]
        assert v["clients"]["webui"] == {"state": "failed", "at": None, "attempts": 3, "retracted": None,
                                         "detail": "timeout"}
        assert "ref" not in v["clients"]["telegram"]

    def test_answer_and_pending(self):
        from modules.ui_view import delivery_view
        answered = delivery_view(_row("n2", "answered", n={"actions": [{"id": "ok", "label": "Approva"}]},
                                      answer={"by": "telegram", "action_id": "ok", "label": "Approva",
                                              "status": "done", "outcome_text": "<b>Fatto</b>"}))
        assert answered["flags"]["answered"] and not answered["flags"]["pending"]
        assert answered["answer"]["outcome_text"] == "Fatto" and answered["actions"] == ["Approva"]
        open_ = delivery_view(_row("n3", "seen", n={"actions": [{"id": "ok", "label": "Approva"}]}))
        assert open_["flags"]["pending"]

    def test_summary_counts(self):
        from modules.ui_view import delivery_view, summarize
        items = [delivery_view(_row("a", deliveries={"telegram": {"state": "delivered"}})),
                 delivery_view(_row("b", "superseded", n={"held": "quiet"},
                                    deliveries={"telegram": {"state": "skipped"}}))]
        s = summarize(items)
        assert s["total"] == 2 and s["held"] == 1 and s["superseded"] == 1
        assert s["clients"]["telegram"] == {"delivered": 1, "skipped": 1, "failed": 0}

    def test_deliveries_query_and_filters(self):
        from modules import ui_view
        archive = MagicMock()
        archive._route_archive.return_value = [_row("a", deliveries={"webui": {"state": "delivered"}}),
                                               _row("b", n={"quiet": True})]
        out = ui_view.deliveries(archive, since="2026-10-18T00:00:00Z", flag="quiet")
        query = archive._route_archive.call_args.kwargs["query"]
        assert query["channel"] == "notification" and query["created_after"] == "2026-10-18T00:00:00Z"
        assert "superseded" in query["lifecycle_states"]
        assert [i["id"] for i in out["items"]] == ["b"] and out["next_before"] is None
        assert [i["id"] for i in ui_view.deliveries(archive, client="webui")["items"]] == ["a"]

    def test_bad_input_and_archive_down(self):
        from modules import ui_view
        archive = MagicMock()
        with pytest.raises(ValueError):
            ui_view.deliveries(archive, flag="nope")
        with pytest.raises(ValueError):
            ui_view.deliveries(archive, since="ieri")
        archive._route_archive.return_value = None
        with pytest.raises(ui_view.ArchiveUnavailable):
            ui_view.deliveries(archive)
        with pytest.raises(ui_view.ArchiveUnavailable):
            ui_view.subscriptions(archive)


@pytest.mark.api
class TestUiEndpoints:
    def test_manifest_is_core_plugin(self, app_client):
        client, _ = app_client
        m = client.get("/api/ui/manifest").json()
        assert m["module"] == "hermes" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["api_prefix"] == "/api/ui/" and web["entry"] == "/ui/webui/hermes.js"
        assert [p["id"] for p in web["page"]] == ["consegne"] and web["page"][0]["order"] == 140
        assert [w["id"] for w in web["widget"]] == ["oggi"] and web["widget"][0]["open_page"] == "consegne"

    def test_deliveries_endpoint(self, app_client):
        client, main = app_client
        with patch.object(main.service.archive, "_route_archive", return_value=[_row("n1")]):
            body = client.get("/api/ui/deliveries", params={"limit": 1}).json()
        assert body["items"][0]["id"] == "n1" and body["summary"]["total"] == 1
        assert body["next_before"] == "2026-10-18T08:00:00+00:00"

    def test_deliveries_errors(self, app_client):
        client, main = app_client
        assert client.get("/api/ui/deliveries", params={"flag": "x"}).status_code == 400
        with patch.object(main.service.archive, "_route_archive", return_value=None):
            assert client.get("/api/ui/deliveries").status_code == 502

    def test_subscriptions_endpoint(self, app_client):
        client, main = app_client
        rows = [{"subscription_id": "sys-action-required-owner", "owner": "owner", "domain": "system",
                 "event_type": "service.action_required", "filters": {},
                 "channels": [{"type": "all", "target": "owner"}], "updated_at": "2026-10-18T08:00:00"}]
        with patch.object(main.service.archive, "_route_archive", return_value=rows):
            body = client.get("/api/ui/subscriptions").json()
        assert body["count"] == 1 and body["subscriptions"][0]["channels"] == [{"type": "all"}]
