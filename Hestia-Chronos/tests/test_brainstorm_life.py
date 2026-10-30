"""Brainstorm + Cindy wave 2 on Chronos (docs/work/2026-10-24-tutto-brainstorm-cindy): routines in words,
special events, smart calendar, the life API tools. Archive mocked in memory."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Rome")


@pytest.fixture
def store():
    from services import agenda as A
    rows: dict[str, dict] = {}

    def route(method, path, body=None, query=None, timeout=10):
        if method == "GET":
            return list(rows.values())
        if method == "PUT" and "chronos-store" in path:
            return {"applied": []}
        rows[body["external_id"]] = {**body, "id": body["external_id"]}
        return rows[body["external_id"]]

    with patch.object(A.archive_client, "_route_archive", side_effect=route):
        yield A, rows


def _ev(title, start, end, source="google"):
    return {"id": title, "external_id": title, "source": source, "title": title, "start_at": start.isoformat(),
            "end_at": end.isoformat(), "all_day": False, "status": "confirmed"}


# ── smart calendar ───────────────────────────────────────────────────────────
@pytest.mark.unit
class TestSmartCalendar:
    def _at(self, h, m=0):
        return datetime(2026, 10, 27, h, m, tzinfo=TZ)

    def test_overlap_proposes_the_first_free_slot(self):
        from services import smart_calendar as S
        with patch.object(S, "_gap", return_value=timedelta(minutes=15)):
            out = S.conflicts([_ev("Dentista", self._at(10), self._at(11)),
                               _ev("Call", self._at(10, 30), self._at(11, 30)),
                               _ev("Pranzo", self._at(12), self._at(13))])
        assert len(out) == 1 and out[0]["move"]["title"] == "Call" and out[0]["keep"]["title"] == "Dentista"
        assert out[0]["to"] == self._at(13, 15)

    def test_assistant_items_and_all_day_are_ignored(self):
        from services import smart_calendar as S
        a = _ev("Job", self._at(9), self._at(10), source="hestia")
        b = _ev("Riunione", self._at(9), self._at(10))
        assert S.conflicts([a, b]) == []

    def test_kept_event_is_not_proposed_again(self):
        from services import smart_calendar as S
        items = [_ev("A", self._at(10), self._at(11)), _ev("B", self._at(10, 30), self._at(11))]
        with patch.object(S.archive_client, "list_items", return_value=items), \
                patch.object(S.hermes_client, "publish_event") as pub, patch.object(S.life_store, "put"):
            first = S.check(now=self._at(7))
            S.keep("B")
            second = S.check(now=self._at(7))
        assert len(first["proposals"]) == 1 and second["proposals"] == []
        action = pub.call_args_list[0].args[3]["_actions"][0]
        assert action["method"] == "PATCH" and action["path"] == "/api/calendar/events/B"
        S._kept.discard("B")


# ── special events ───────────────────────────────────────────────────────────
@pytest.mark.unit
class TestSpecial:
    def test_birthday_is_yearly_and_counts_days(self, store):
        from services import special
        item = special.add(title="Compleanno di Anna", day="1990-11-03", kind="birthday", person="Anna")
        assert "FREQ=YEARLY" in item["recurrence"]
        rows = special.list_special(date(2026, 10, 27))
        assert rows[0]["next"] == "2026-11-03" and rows[0]["in_days"] == 7 and rows[0]["lead_days"] == 7

    def test_daily_pass_sends_lead_and_day_notices(self, store):
        from services import special
        special.add(title="Anniversario", day="2015-10-27", kind="anniversary")
        special.add(title="Compleanno di Luca", day="1992-11-03", kind="birthday", person="Luca")
        with patch.object(special.hermes_client, "publish_event") as pub, \
                patch.object(special, "_push_moment", return_value=0) as push:
            out = special.run_daily(date(2026, 10, 27))
        assert len(out["today"]) == 1 and len(out["soon"]) == 1
        assert {c.args[1] for c in pub.call_args_list} == {"special.today", "special.soon"}
        assert push.call_args.args[0]["kind"] == "anniversary"

    def test_module_source_does_not_override_owner_edit(self, store):
        from services import special
        A, rows = store
        special.add(title="Compleanno di Bea", day="1991-05-02", kind="birthday", key="special.person.bea", by="hera")
        rows["special.person.bea"]["meta"]["user_modified"] = True
        again = special.add(title="Altro titolo", day="1991-05-03", kind="birthday", key="special.person.bea",
                            by="hera")
        assert again["title"] == "Compleanno di Bea"

    def test_bad_date_is_refused(self):
        from services import agenda, special
        with pytest.raises(agenda.AgendaError):
            special.add(title="x", day="31/12")


# ── routines ─────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestRoutines:
    def test_time_routine_is_an_agenda_job(self, store):
        from services import routines
        item = routines.create(title="Notizie", instruction="Dimmi le notizie", recurrence="FREQ=DAILY;BYHOUR=8")
        assert item["type"] == "job" and item["action"]["path"] == f"/api/routines/{item['key']}/run"
        assert routines.list_routines()[0]["trigger"] == "orario"

    def test_routine_needs_instruction_and_trigger(self, store):
        from services import agenda, routines
        with pytest.raises(agenda.AgendaError):
            routines.create(title="x", instruction="", recurrence="FREQ=DAILY")
        with pytest.raises(agenda.AgendaError):
            routines.create(title="x", instruction="fai")

    def test_template_fills_fields(self, store):
        from services import agenda, routines
        with pytest.raises(agenda.AgendaError):
            routines.from_template("radar", {})
        item = routines.from_template("radar", {"topic": "Formula 1"})
        r = routines.routine_of(item)
        assert "Formula 1" in r["instruction"] and r["precheck"]["args"]["q"] == "Formula 1 notizie oggi"
        assert r["deliver"] == "recap"

    def test_empty_precheck_stops_without_the_model(self, store):
        from services import routines
        item = routines.create(title="Case", instruction="Le migliori", recurrence="FREQ=DAILY",
                               precheck={"tool": "scout_listings", "args": {}})
        with patch.object(routines, "_mcp") as mcp, patch.object(routines, "_ask_oracle") as ask:
            mcp.return_value.call.return_value = (True, {"items": []})
            out = routines.run(item["key"])
        assert out["ran"] is False and out["reason"] == "niente di nuovo"
        ask.assert_not_called()

    def test_nothing_to_say_is_not_delivered(self, store):
        from services import routines
        item = routines.create(title="Settimana", instruction="Cosa c'è", recurrence="FREQ=WEEKLY")
        with patch.object(routines, "_ask_oracle", return_value={"reply": "NIENTE.", "changes": []}), \
                patch.object(routines.hermes_client, "publish_event") as pub:
            out = routines.run(item["key"])
        assert out["delivered"] is False
        pub.assert_not_called()

    def test_answer_goes_to_hermes_with_routine_origin(self, store):
        from services import routines
        item = routines.create(title="Settimana", instruction="Cosa c'è", recurrence="FREQ=WEEKLY")
        with patch.object(routines, "_ask_oracle", return_value={"reply": "Martedì dentista", "changes": []}) as ask, \
                patch.object(routines.hermes_client, "publish_event") as pub:
            out = routines.run(item["key"])
        assert out["delivered"] and ask.call_args.args[0] == item["key"]
        assert pub.call_args.args[1] == "routine.result" and pub.call_args.args[3]["_message"] == "Martedì dentista"

    def test_recap_delivery_is_kept_for_the_evening(self, store):
        from services import routines
        item = routines.create(title="Radar", instruction="Notizie", recurrence="FREQ=DAILY", deliver="recap")
        with patch.object(routines, "_ask_oracle", return_value={"reply": "Tre notizie", "changes": []}), \
                patch.object(routines.life_store, "put") as put:
            routines.run(item["key"])
        assert any(r["text"] == "Tre notizie" for r in routines.recap_lines())
        assert put.call_args.args[0] == "routine_result"

    def test_assistant_question_becomes_a_notification_that_asks(self, store):
        """2026-10-30-domande-nelle-notifiche: ask_user in a routine turn reaches the owner as a question."""
        from services import routines
        item = routines.create(title="Spesa", instruction="Cosa manca", recurrence="FREQ=WEEKLY", deliver="recap")
        frame = {"type": "question", "question_id": "ask_9", "prompt": "", "kind": "multi_choice",
                 "options": [{"value": "Pane", "label": "Pane"}, {"value": "Latte", "label": "Latte"}],
                 "allow_other": True}
        with patch.object(routines, "_ask_oracle", return_value={"reply": "Cosa compro?", "changes": [],
                                                                 "questions": [frame]}), \
                patch.object(routines.hermes_client, "publish_event") as pub:
            out = routines.run(item["key"])
        assert out["deliver"] == "question" and pub.call_count == 1
        payload = pub.call_args.args[3]
        assert pub.call_args.args[1] == "routine.question" and payload["_message"] == "Cosa compro?"
        q = payload["_question"]
        assert q["kind"] == "multi_choice" and q["allow_other"] and q["service"] == "chronos"
        assert q["path"] == f"/api/routines/{item['key']}/answer" and q["body"] == {"question_id": "ask_9"}
        assert not any(r.get("text") == "Cosa compro?" for r in routines.recap_lines())   # never for the evening

    def test_answer_continues_the_routine(self, store):
        from unittest.mock import MagicMock
        from services import routines
        item = routines.create(title="Spesa", instruction="Cosa manca", recurrence="FREQ=WEEKLY")
        resp = MagicMock(content=b"x", status_code=200)
        resp.json.return_value = {"status_code": 200, "payload": {"resolved": True,
                                                                  "resume": {"message": "Risposta: Pane"}}}

        class NowThread:
            def __init__(self, target, **kw):
                self.target = target

            def start(self):
                self.target()
        with patch.object(routines.requests, "post", return_value=resp) as post, \
                patch.object(routines.threading, "Thread", NowThread), \
                patch.object(routines, "_ask_oracle", return_value={"reply": "Aggiunto il pane", "changes": []}) as ask, \
                patch.object(routines.hermes_client, "publish_event") as pub:
            out = routines.answer(item["key"], "ask_9", "Pane", "telegram")
        assert out["resumed"] is True
        sent = post.call_args.kwargs["json"]["body"]
        assert sent == {"session_id": f"routine:{item['key']}", "question_id": "ask_9", "answer": "Pane",
                        "client": "telegram"}
        assert ask.call_args.args[2] == "Risposta: Pane"
        assert pub.call_args.args[3]["_message"] == "Aggiunto il pane"

    def test_answer_to_a_closed_question_is_409(self, store):
        from unittest.mock import MagicMock
        from services import agenda, routines
        item = routines.create(title="Spesa", instruction="Cosa manca", recurrence="FREQ=WEEKLY")
        resp = MagicMock(content=b"x", status_code=200)
        resp.json.return_value = {"status_code": 404, "payload": {"detail": "not found"}}
        with patch.object(routines.requests, "post", return_value=resp), pytest.raises(agenda.AgendaError) as err:
            routines.answer(item["key"], "ask_9", "Pane")
        assert err.value.status_code == 409

    def test_precheck_empty_shapes(self):
        from services.routines import _empty
        assert _empty([]) and _empty({"count": 0}) and _empty({"items": []})
        assert not _empty({"items": [1]}) and not _empty("testo")


# ── tools and routes ─────────────────────────────────────────────────────────
@pytest.mark.unit
def test_every_life_tool_has_a_route_and_a_unique_name():
    import re
    import life_api
    import main
    tools = life_api.mcp_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    routes = {(m.upper(), re.sub(r"\{[^}]+\}", "{}", path))
              for path, ops in main.app.openapi()["paths"].items() for m in ops}
    for t in tools:
        assert (t.method, re.sub(r"\{[^}]+\}", "{}", t.path)) in routes, t.name
    keys = [r["key"] for r in life_api.boot_rules()]
    assert keys == ["chronos.special.daily", "chronos.smart_calendar"]


@pytest.mark.unit
def test_plugin_pages_reach_routines_and_special_under_the_api_prefix(store):
    """The WebUI proxy only lets the plugin call /api/agenda/…: «Routine» and «Eventi speciali» live there too."""
    import re
    from pathlib import Path
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    created = c.post("/api/agenda/routines", json={"title": "Meteo", "instruction": "dimmi se piove",
                                                   "recurrence": "FREQ=DAILY"})
    assert created.status_code == 200
    assert [r["title"] for r in c.get("/api/agenda/routines").json()["items"]] == ["Meteo"]
    assert c.get("/api/agenda/routines/templates").json()["templates"][0]["id"] == "radar"
    assert c.post("/api/agenda/special", json={"title": "Compleanno di Anna", "day": "2000-02-14",
                                               "kind": "birthday"}).status_code == 200
    assert c.get("/api/agenda/special").json()["items"][0]["yearly"] is True
    pages = {p["id"]: p for p in c.get("/api/ui/manifest").json()["clients"]["webui"]["page"]}
    src = (Path(__file__).parents[1] / "ui" / "src" / "index.ts").read_text(encoding="utf-8")
    defined = set(re.findall(r"'(chronos-[a-z-]+)'\s*:", src))
    assert {p["element"] for p in pages.values()} <= defined
    assert pages["routine"]["element"] == "chronos-routines" and pages["eventi"]["element"] == "chronos-special"
