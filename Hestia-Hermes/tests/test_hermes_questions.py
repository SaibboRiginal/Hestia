"""Questions in notifications (docs/work/2026-10-30-domande-nelle-notifiche): ``_question`` like the chat card."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

Q = {"kind": "multi_choice", "options": ["Pane", {"value": "latte", "label": "Latte"}, "Uova"],
     "allow_other": True, "service": "chronos", "path": "/api/routines/r1/answer", "body": {"question_id": "ask_1"}}


@pytest.fixture
def center():
    from modules.clients import NotifyClient
    from modules.notifications import NotificationCenter
    clients = MagicMock()
    clients.clients.return_value = [NotifyClient("telegram", "/api/notify"), NotifyClient("webui", "/api/notify")]
    c = NotificationCenter(MagicMock(), clients=clients, hub_api_url="http://hub/api")
    c.archive.find_active_outbound_event.return_value = None
    c.archive.patch_outbound_event.return_value = (200, {"outbound_event_id": "n1", "payload": {}})
    c.presence = MagicMock()
    c.presence.effect.return_value = "all"
    c.presence.get.return_value = None
    return c


def _row(question, state="delivered"):
    from modules.notifications import normalize_question
    return {"outbound_event_id": "n1", "lifecycle_state": state,
            "payload": {"notification": {"title": "Spesa", "question": normalize_question(question)}}}


@pytest.mark.unit
class TestNormalize:
    def test_shapes(self):
        from modules.notifications import normalize_question, public_question
        q = normalize_question(Q)
        assert q["options"] == [{"value": "Pane", "label": "Pane"}, {"value": "latte", "label": "Latte"},
                                {"value": "Uova", "label": "Uova"}]
        assert public_question(q) == {"kind": "multi_choice", "options": q["options"], "allow_other": True}
        assert normalize_question({"service": "x", "path": "/p"})["options"][0]["label"] == "Sì"
        free = normalize_question({"kind": "free_text", "service": "x", "path": "/p", "options": ["a", "b"]})
        assert free["options"] == [] and free["allow_other"] is True

    def test_malformed_is_ignored(self):
        from modules.notifications import normalize_question
        assert normalize_question({"kind": "single_choice", "options": ["solo"], "service": "x", "path": "/p"}) is None
        assert normalize_question({"kind": "confirm", "service": "x", "path": "no-slash"}) is None
        assert normalize_question("nope") is None


@pytest.mark.unit
class TestPublishAndView:
    def test_clients_see_question_not_route(self, center):
        bodies = {}

        def fake_route(service, path, body, **kw):
            bodies[service] = body
            return 200, {"delivered": True}
        with patch.object(center, "_route", side_effect=fake_route):
            center.publish(message="Cosa compro?", event_type="routine.result", domain="assistant", question=Q)
        q = bodies["webui"]["question"]
        assert q["kind"] == "multi_choice" and "service" not in q and "path" not in q
        assert bodies["telegram"]["question"] == q

    def test_question_is_pending(self):
        from modules.notifications import view
        v = view(_row(Q))
        assert v["pending"] is True and v["question"]["kind"] == "multi_choice"
        assert view(_row(Q, state="answered"))["pending"] is False

    def test_not_held_by_presence(self, center):
        from modules.notifications import presence_holds
        center.presence.effect.return_value = "important"
        with patch.object(center, "_route", return_value=(200, {"delivered": True})):
            center.publish(message="?", event_type="x.y", domain="system", question=Q)
        spec = center.archive.upsert_outbound_event.call_args.args[0]["payload"]["notification"]
        assert "held" not in spec
        assert presence_holds("important", "info", [], None) is True


@pytest.mark.unit
class TestReply:
    def test_multi_answer_forwarded_once(self, center):
        center.archive.get_outbound_event.return_value = _row(Q)
        with patch.object(center, "_route", return_value=(200, {"message": "Ok, li aggiungo"})) as route, \
                patch.object(center, "_broadcast") as broadcast:
            status, body = center.reply("n1", "latte\nPane\nCaffè", "telegram")
        assert status == 200 and body["answer"]["outcome_text"] == "Ok, li aggiungo"
        service, path, sent = route.call_args.args[:3]
        assert (service, path) == ("chronos", "/api/routines/r1/answer")
        assert sent["question_id"] == "ask_1" and sent["answers"] == ["latte", "Pane", "Caffè"]
        assert sent["client"] == "telegram" and sent["notification_id"] == "n1"
        claim = center.archive.patch_outbound_event.call_args_list[0]
        assert claim.kwargs["payload_merge"]["answer"]["label"] == "Latte, Pane, Caffè"
        assert broadcast.call_args.args[1]["state"] == "answered"

    def test_single_choice_takes_one_and_refuses_unknown(self, center):
        center.archive.get_outbound_event.return_value = _row(
            {"kind": "single_choice", "options": ["A", "B"], "service": "m", "path": "/p"})
        status, body = center.reply("n1", "Z", "webui")
        assert status == 400 and body["status"] == "unknown_option"

    def test_late_answer_is_409(self, center):
        center.archive.get_outbound_event.return_value = _row(Q)
        center.archive.patch_outbound_event.return_value = (409, {"lifecycle_state": "answered"})
        status, body = center.reply("n1", "Pane", "webui")
        assert status == 409 and body["status"] == "already_handled"

    def test_module_error_releases_claim(self, center):
        center.archive.get_outbound_event.return_value = _row(Q)
        with patch.object(center, "_route", return_value=(500, "boom")):
            status, _ = center.reply("n1", "Pane", "webui")
        assert status == 502
        release = center.archive.patch_outbound_event.call_args_list[-1]
        assert release.args[1] == "seen" and release.kwargs["only_if_states"] == ["answered"]

    def test_no_question_or_empty(self, center):
        center.archive.get_outbound_event.return_value = {"outbound_event_id": "n1", "payload": {"notification": {}}}
        assert center.reply("n1", "x", "webui")[0] == 404
        center.archive.get_outbound_event.return_value = _row(Q)
        assert center.reply("n1", "  ", "webui")[0] == 400
