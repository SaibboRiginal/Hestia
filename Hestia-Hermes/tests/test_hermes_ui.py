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
        pages = {p["id"]: p for p in web["page"]}
        assert list(pages) == ["notifiche", "consegne"]
        assert pages["notifiche"]["order"] == 140 and pages["notifiche"]["element"] == "hermes-inbox"
        assert pages["notifiche"]["badge"] == {"source": "/api/ui/inbox/counts", "field": "unread"}
        assert pages["notifiche"]["badge"]["source"].startswith(web["api_prefix"])
        assert pages["consegne"]["order"] == 141 and pages["consegne"]["parent"] == "notifiche"
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


@pytest.mark.api
class TestUiInbox:
    """«Notifiche» page: thin /api/ui/inbox* doors on the existing notifications logic (client = webui)."""

    def test_inbox_list_defaults_to_webui(self, app_client):
        client, main = app_client
        with patch.object(main.service.notifications, "inbox", return_value={"items": [], "counts": {}}) as m:
            assert client.get("/api/ui/inbox", params={"filter": "pending", "source": "scout",
                                                       "before": "2026-10-18T08:00:00Z"}).status_code == 200
        m.assert_called_once_with(filter_="pending", source="scout", before="2026-10-18T08:00:00Z",
                                  limit=40, client="webui")

    def test_counts_is_badge_source(self, app_client):
        client, main = app_client
        with patch.object(main.service.notifications, "counts", return_value={"unread": 3, "pending": 1}) as m:
            assert client.get("/api/ui/inbox/counts").json() == {"unread": 3, "pending": 1}
        m.assert_called_once_with("webui")

    def test_seen_and_seen_all(self, app_client):
        client, main = app_client
        n = main.service.notifications
        with patch.object(n, "mark_seen", return_value={"status": "ok", "changed": True}) as seen:
            assert client.post("/api/ui/inbox/n1/seen", json={}).json()["changed"] is True
            assert client.post("/api/ui/inbox/n2/seen").status_code == 200
        assert [c.args for c in seen.call_args_list] == [("n1", "webui"), ("n2", "webui")]
        with patch.object(n, "mark_all_seen", return_value={"status": "ok", "changed": 2}) as all_:
            assert client.post("/api/ui/inbox/seen-all", json={}).json()["changed"] == 2
        all_.assert_called_once_with("webui", None)

    def test_answer_passes_status_through(self, app_client):
        client, main = app_client
        n = main.service.notifications
        with patch.object(n, "answer", return_value=(200, {"status": "done", "answer": {"label": "Approva"}})) as m:
            r = client.post("/api/ui/inbox/n1/answer", json={"action_id": "ok"})
        assert r.status_code == 200 and r.json()["answer"]["label"] == "Approva"
        m.assert_called_once_with("n1", "ok", "webui")
        handled = {"status": "already_handled", "answer": {"by": "telegram"}}
        with patch.object(n, "answer", return_value=(409, handled)):
            r = client.post("/api/ui/inbox/n1/answer", json={"action_id": "ok"})
        assert r.status_code == 409 and r.json()["answer"]["by"] == "telegram"
        assert client.post("/api/ui/inbox/n1/answer", json={}).status_code == 422


@pytest.mark.unit
def test_ui_doors_for_secret_form_and_web_push(app_client):
    """W7: the inbox page and the WebUI shell reach the secret form and Web Push under the plugin prefix /api/ui/."""
    client, main = app_client
    with patch.object(main.service.notifications, "submit_secret", return_value=(200, {"status": "ok"})) as sub:
        r = client.post("/api/ui/inbox/n1/secret", json={"values": {"code": "123456"}})
    assert r.status_code == 200 and sub.call_args.args[:3] == ("n1", {}, "webui")   # values cleared after use
    with patch.object(main.webpush, "configured", return_value=False), patch.object(main.webpush, "public_key", return_value=""):
        assert client.get("/api/ui/push/key").json() == {"enabled": False, "public_key": ""}
    with patch.object(main.webpush, "subscribe", return_value={"status": "ok"}) as s:
        assert client.post("/api/ui/push/subscribe", json={"subscription": {"endpoint": "https://x"}}).json()["status"] == "ok"
    assert s.call_args.args[1] == {"endpoint": "https://x"}
