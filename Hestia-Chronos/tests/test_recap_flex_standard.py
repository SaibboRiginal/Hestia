"""Daily recap dossier (docs/work/2026-10-20-recap-giornaliero) on Chronos: the agenda piece (§3.3), flexible jobs
around the user's events (§3.8) and standard activities restored in one click (§3.9). Archive mocked in memory."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Rome")


def _job(key, owner="athena", created_by="athena", status="confirmed", start="2026-10-01T21:30:00",
         flex=None, user_modified=False, runs=None, last_fired=None):
    params = {"flex": flex} if flex else {}
    return {"id": key, "external_id": key, "title": "Recap della sera", "start_at": start, "source": "hestia",
            "recurrence": "RRULE:FREQ=DAILY", "status": status, "kind": "job",
            "meta": {"type": "job", "owner": owner, "created_by": created_by, "params": params, "tz": "Europe/Rome",
                     "user_modified": user_modified, "runs": runs or [], "last_fired": last_fired,
                     "action": {"service": owner, "path": "/api/athena/recap"}}}


def _event(title, start, end, all_day=False):
    return {"id": title, "external_id": title, "source": "google", "title": title, "start_at": start.isoformat(),
            "end_at": end.isoformat(), "all_day": all_day, "status": "confirmed", "kind": "event"}


@pytest.fixture
def store():
    from services import agenda as A
    rows: dict[str, dict] = {}
    calendar: list[dict] = []

    def route(method, path, body=None, query=None, timeout=10):
        if method == "GET":
            if (query or {}).get("source") == "hestia":
                return list(rows.values())
            return list(rows.values()) + calendar
        rows[body["external_id"]] = {**body, "id": body["external_id"]}
        return rows[body["external_id"]]

    with patch.object(A.archive_client, "_route_archive", side_effect=route):
        yield A, rows, calendar


# ── §3.8 flex.plan ────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestFlexPlan:
    RULE = {"earliest": "20:00", "latest": "23:30"}
    GAP = timedelta(minutes=15)
    NOMINAL = datetime(2026, 10, 20, 21, 30, tzinfo=TZ)

    def _at(self, h, m=0):
        return datetime(2026, 10, 20, h, m, tzinfo=TZ)

    def test_free_evening_keeps_the_time(self):
        from services.flex import plan
        assert plan(self.NOMINAL, self.RULE, [], self.GAP) == (self.NOMINAL, "")

    def test_dinner_postpones_after_the_event(self):
        from services.flex import plan
        busy = [(self._at(21), self._at(22, 30), "Cena con Luca")]
        assert plan(self.NOMINAL, self.RULE, busy, self.GAP) == (self._at(22, 45), "dopo Cena con Luca")

    def test_chained_events_and_no_room_after_goes_before(self):
        from services.flex import plan
        busy = [(self._at(21), self._at(22), "Cinema"), (self._at(22), self._at(23, 30), "Bar")]
        assert plan(self.NOMINAL, self.RULE, busy, self.GAP) == (self._at(20, 45), "prima di Cinema")

    def test_whole_range_busy_goes_to_the_end(self):
        from services.flex import plan
        busy = [(self._at(19), self._at(23, 59), "Concerto")]
        fire, reason = plan(self.NOMINAL, self.RULE, busy, self.GAP)
        assert fire == self._at(23, 30) and reason.startswith("fine della fascia")

    def test_event_close_to_nominal_counts_with_the_gap(self):
        from services.flex import plan
        busy = [(self._at(21, 40), self._at(22), "Telefonata")]
        assert plan(self.NOMINAL, self.RULE, busy, self.GAP)[0] == self._at(22, 15)


# ── §3.8 tick with flex ──────────────────────────────────────────────────────
@pytest.mark.unit
def test_tick_fires_flexible_job_after_the_event_and_records_why(store):
    A, rows, calendar = store
    day = datetime(2026, 10, 20, tzinfo=TZ)
    rows["athena.recap.evening"] = _job("athena.recap.evening", flex={"earliest": "20:00", "latest": "23:30"},
                                        last_fired=(day - timedelta(hours=1)).isoformat())
    calendar.append(_event("Cena con Luca", day.replace(hour=21), day.replace(hour=22, minute=30)))
    with patch.object(A, "_fire", return_value=(True, "200: ok")) as fire:
        assert A.tick(now=day.replace(hour=21, minute=31).astimezone(timezone.utc))["fired"] == 0
        assert A.tick(now=day.replace(hour=22, minute=46).astimezone(timezone.utc))["fired"] == 1
        assert fire.call_count == 1
    run = rows["athena.recap.evening"]["meta"]["runs"][-1]
    assert run["flex"]["reason"] == "dopo Cena con Luca"
    assert run["flex"]["at"].startswith("2026-10-20T22:45")
    with patch.object(A, "_fire", return_value=(True, "200: ok")) as fire:
        A.tick(now=day.replace(hour=23, minute=10).astimezone(timezone.utc))
        assert fire.call_count == 0          # one recap per occurrence


@pytest.mark.unit
def test_tick_without_events_fires_at_the_nominal_time(store):
    A, rows, _ = store
    day = datetime(2026, 10, 20, tzinfo=TZ)
    rows["athena.recap.evening"] = _job("athena.recap.evening", flex={"earliest": "20:00", "latest": "23:30"},
                                        last_fired=(day - timedelta(hours=1)).isoformat())
    with patch.object(A, "_fire", return_value=(True, "200: ok")) as fire:
        A.tick(now=day.replace(hour=21, minute=30, second=30).astimezone(timezone.utc))
        assert fire.call_count == 1
    assert "flex" not in rows["athena.recap.evening"]["meta"]["runs"][-1]


# ── §3.3 agenda piece ────────────────────────────────────────────────────────
@pytest.mark.unit
def test_day_view_recap_lists_events_and_failed_jobs(store):
    from services import day_view
    A, rows, calendar = store
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    calendar.append(_event("Dentista", today.replace(hour=9), today.replace(hour=10)))
    calendar.append(_event("Ferie", tomorrow, tomorrow + timedelta(days=1), all_day=True))
    calendar.append(_event("Palestra", tomorrow.replace(hour=18, minute=30), tomorrow.replace(hour=19, minute=30)))
    occ = today.replace(hour=3).astimezone(timezone.utc).isoformat()
    rows["chronos.calendar_sync"] = {**_job("chronos.calendar_sync", owner="chronos", created_by="chronos",
                                            start=today.replace(hour=3).isoformat()),
                                     "title": "Sincronizza calendario"}
    rows["chronos.calendar_sync"]["meta"]["runs"] = [{"occurrence": occ, "ok": False, "detail": "502", "at": occ}]
    facts = day_view.recap(today.date(), tomorrow.date())
    assert facts["done"] == [{"text": "Impegni: 09:00 Dentista"}]
    assert facts["missed"] == [{"text": "Non riuscito: Sincronizza calendario", "tone": "danger"}]
    assert [n["text"] for n in facts["next"]] == ["Ferie (tutto il giorno)", "18:30 Palestra"]


# ── §3.9 standard activities ─────────────────────────────────────────────────
@pytest.mark.unit
def test_standard_lists_module_defaults_with_state_and_restore_brings_them_back(store):
    A, rows, _ = store
    rows["athena.recap.evening"] = _job("athena.recap.evening", status="cancelled")
    rows["hygieia.reminder"] = _job("hygieia.reminder", owner="hygieia", created_by="hygieia", user_modified=True,
                                    start="2026-10-01T22:15:00")
    rows["mine"] = _job("mine", owner="user", created_by="user")
    rows["scout.email_cycle"] = _job("scout.email_cycle", owner="scout", created_by="scout", status="cancelled")
    rows["scout.email_cycle"]["meta"]["params"] = {"retired_by_module": True}
    A._DECLARED["hygieia"] = {"hygieia.reminder": {"key": "hygieia.reminder", "start_at": "2026-10-01T20:00:00",
                                                   "title": "Promemoria routine"}}
    out = A.standard()
    states = {r["key"]: r["state"] for r in out["activities"]}
    assert states == {"athena.recap.evening": "eliminata", "hygieia.reminder": "modificata"}
    assert out["counts"]["eliminata"] == 1

    A.restore("athena.recap.evening")
    assert rows["athena.recap.evening"]["status"] == "confirmed"
    A.restore("hygieia.reminder")
    meta = rows["hygieia.reminder"]["meta"]
    assert not meta["user_modified"] and rows["hygieia.reminder"]["title"] == "Promemoria routine"
    assert rows["hygieia.reminder"]["start_at"].startswith("2026-10-01T20:00")
    assert {r["state"] for r in A.standard()["activities"]} == {"attiva"}
    with pytest.raises(A.AgendaError):
        A.restore("mine")


@pytest.mark.api
def test_standard_and_recap_endpoints(store):
    from fastapi.testclient import TestClient
    import main
    A, rows, _ = store
    rows["athena.recap.evening"] = _job("athena.recap.evening", status="cancelled")
    client = TestClient(main.app)
    body = client.get("/api/agenda/standard").json()
    assert body["activities"][0]["key"] == "athena.recap.evening" and body["activities"][0]["can_restore"]
    r = client.post("/api/agenda/standard/athena.recap.evening/restore")
    assert r.status_code == 200 and rows["athena.recap.evening"]["status"] == "confirmed"
    assert client.post("/api/agenda/standard/nope/restore").status_code == 404
    piece = client.get("/api/module/recap", params={"day": date(2020, 1, 1).isoformat()}).json()
    assert piece == {"module": "chronos", "empty": True}
