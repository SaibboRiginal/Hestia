"""Weather on the calendar page: horizon, located occurrences, provider events with a location."""
from datetime import date

import pytest

from services import agenda_weather

TODAY = date(2026, 10, 21)


def _route(calls, events=None, fail_weather=False):
    def route(*, method, path, query=None, body=None, timeout_seconds=20):
        calls.append((method, path, query, body))
        if path == "/api/gateway/calendar/events":
            return 200, {"events": events or []}
        if fail_weather:
            raise ConnectionError("hecate away")
        answers = {}
        for it in body["items"]:
            if it.get("place") == "Atlantide":
                answers[it["key"]] = {"status": "place_not_found"}
            else:
                answers[it["key"]] = {"status": "ok", "place": it.get("place") or "Casa",
                                      "day": {"date": (it.get("date") or it["at"][:10]), "min_c": 9, "max_c": 18},
                                      **({"hour": {"temp_c": 15, "rain_prob": 70}} if it.get("at") else {})}
        return 200, {"status": "ok", "items": answers}
    return route


@pytest.mark.unit
def test_days_only_inside_the_horizon():
    agenda_weather._ext_cache.clear()
    calls = []
    out = agenda_weather.build(_route(calls), "2026-10-15", "2026-11-30", [], today=TODAY)
    assert min(out["days"]) == "2026-10-21" and max(out["days"]) == "2026-11-03" and len(out["days"]) == 14
    assert agenda_weather.build(_route([]), "2026-10-01", "2026-10-10", [], today=TODAY)["days"] == {}


@pytest.mark.unit
def test_located_occurrences_and_external_events():
    agenda_weather._ext_cache.clear()
    calls = []
    events = [{"provider": "google", "event_id": "a", "title": "Dentista", "start_datetime": "2026-10-22T14:00:00+02:00",
               "location": "Lugano"},
              {"provider": "google", "event_id": "b", "title": "Call", "start_datetime": "2026-10-22T10:00:00+02:00",
               "location": "https://meet.example/x"},
              {"provider": "google", "event_id": "c", "title": "Nessun luogo", "start_datetime": "2026-10-22T10:00:00+02:00"}]
    located = [{"key": "hercules.activity.1|2026-10-23", "place": "Parco", "at": "2026-10-23T18:00:00+02:00"},
               {"key": "far", "place": "Parco", "at": "2026-12-23T18:00:00+02:00"},
               {"key": "bad", "place": "Atlantide", "at": "2026-10-23T18:00:00+02:00"}]
    out = agenda_weather.build(_route(calls, events), "2026-10-21", "2026-10-27", located, today=TODAY)
    assert out["events"]["hercules.activity.1|2026-10-23"]["hour"]["rain_prob"] == 70
    assert "far" not in out["events"] and "bad" not in out["events"]
    assert [x["title"] for x in out["external"]] == ["Dentista"]
    weather_calls = [c for c in calls if c[1] == "/api/gateway/weather/at"]
    assert len(weather_calls) == 1          # one Hecate call for everything


@pytest.mark.unit
def test_hecate_away_answers_empty():
    agenda_weather._ext_cache.clear()
    out = agenda_weather.build(_route([], fail_weather=True), "2026-10-21", "2026-10-27", [], today=TODAY)
    assert out["days"] == {} and out["events"] == {}
