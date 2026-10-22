"""Weather provider (Open-Meteo) and gateway endpoints — no network: recorded-shape responses."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from providers.weather import WeatherError, WeatherService, is_rainy

TODAY = date(2026, 10, 20)


def _forecast_blob(days: int = 16, rain_day: int = 1) -> dict:
    dates = [(TODAY + timedelta(days=i)).isoformat() for i in range(days)]
    hours = [f"{d}T{h:02d}:00" for d in dates for h in range(24)]
    rain_hours = {f"{dates[rain_day]}T{h:02d}:00" for h in (15, 16, 17)}
    return {
        "timezone": "Europe/Rome",
        "current": {"time": f"{dates[0]}T10:00", "temperature_2m": 14.6, "apparent_temperature": 13.2,
                    "relative_humidity_2m": 70, "is_day": 1, "weather_code": 2, "wind_speed_10m": 9.4,
                    "precipitation": 0.0},
        "daily": {"time": dates, "weather_code": [63 if i == rain_day else 1 for i in range(days)],
                  "temperature_2m_max": [18.4] * days, "temperature_2m_min": [9.6] * days,
                  "precipitation_sum": [6.2 if i == rain_day else 0 for i in range(days)],
                  "precipitation_probability_max": [90 if i == rain_day else 5 for i in range(days)],
                  "wind_speed_10m_max": [15] * days, "sunrise": [f"{d}T07:30" for d in dates],
                  "sunset": [f"{d}T18:20" for d in dates]},
        "hourly": {"time": hours, "temperature_2m": [12.0] * len(hours), "apparent_temperature": [11.0] * len(hours),
                   "precipitation_probability": [80 if t in rain_hours else 0 for t in hours],
                   "precipitation": [1.5 if t in rain_hours else 0 for t in hours],
                   "weather_code": [63 if t in rain_hours else 1 for t in hours],
                   "wind_speed_10m": [8] * len(hours), "is_day": [1] * len(hours)},
    }


GEO = {
    "milano": [{"name": "Milano", "latitude": 45.46, "longitude": 9.19, "country": "Italia", "country_code": "IT",
                "admin1": "Lombardia", "timezone": "Europe/Rome"}],
    "roma": [{"name": "Roma", "latitude": 41.89, "longitude": 12.48, "country": "Italia", "country_code": "IT",
              "admin1": "Lazio", "timezone": "Europe/Rome"}],
    "lugano": [{"name": "Lugano", "latitude": 46.0, "longitude": 8.95, "country": "Svizzera", "country_code": "CH",
                "admin1": "Ticino", "timezone": "Europe/Zurich"}],
}


class FakeHttp:
    def __init__(self, fail_forecast: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.fail_forecast = fail_forecast

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        test = self

        class R:
            status_code = 200

            def json(self_inner):
                if "geocoding" in url:
                    return {"results": GEO.get(str(params["name"]).strip().lower(), [])}
                if test.fail_forecast:
                    raise RuntimeError("boom")
                return _forecast_blob()
        if "forecast" in url and self.fail_forecast:
            raise ConnectionError("unreachable")
        return R()

    def count(self, kind: str) -> int:
        return sum(1 for u, _ in self.calls if kind in u)


PLACES = [{"id": "casa", "name": "Casa", "address": "Via Roma 3, 20121 Milano", "kind": "home"},
          {"id": "palestra", "name": "Palestra", "address": "Lugano", "kind": "other", "lat": 46.0, "lon": 8.95}]


def _svc(places=None, http=None, clock=None):
    t = {"now": 1000.0}
    svc = WeatherService(places=lambda: PLACES if places is None else places, cache_minutes=lambda: 30,
                         http_get=http or FakeHttp(), clock=clock or (lambda: t["now"]))
    return svc, t


@pytest.mark.unit
def test_now_uses_home_and_caches():
    http = FakeHttp()
    svc, t = _svc(http=http)
    a = svc.now()
    assert a["status"] == "ok" and a["place"]["name"] == "Casa" and a["place"]["lat"] == 45.46
    assert a["now"]["temp_c"] == 15 and a["now"]["condition"] == "parzialmente nuvoloso"
    assert a["today"]["date"] == TODAY.isoformat()
    svc.now()
    assert http.count("forecast") == 1          # second answer from cache
    t["now"] += 31 * 60
    svc.now()
    assert http.count("forecast") == 2          # cache expired


@pytest.mark.unit
def test_address_resolves_through_its_city_and_saved_coords_skip_geocoding():
    http = FakeHttp()
    svc, _ = _svc(http=http)
    assert svc.resolve("casa")["lat"] == 45.46
    r = svc.resolve("che tempo fa in palestra")
    assert r["saved"] == "palestra" and r["lat"] == 46.0
    assert all("Lugano" not in str(p.get("name")) for u, p in http.calls if "geocoding" in u)


@pytest.mark.unit
def test_needs_place_and_not_found():
    svc, _ = _svc(places=[])
    with pytest.raises(WeatherError) as e:
        svc.now()
    assert e.value.status == "needs_place"
    with pytest.raises(WeatherError) as e:
        svc.now("Atlantide")
    assert e.value.status == "place_not_found"


@pytest.mark.unit
def test_city_with_country_qualifier():
    svc, _ = _svc()
    assert svc.geocode("Lugano, Svizzera")[0]["country_code"] == "CH"
    assert svc.geocode("Lugano, IT") == [] or svc.geocode("Lugano, IT")[0]["name"] == "Lugano"


@pytest.mark.unit
def test_forecast_range_and_rain_hours():
    svc, _ = _svc()
    f = svc.forecast("Roma", (TODAY + timedelta(days=1)).isoformat())
    assert f["place"]["name"] == "Roma"
    rainy = f["days"][0]
    assert rainy["rain_prob"] == 90 and rainy["rain_hours"] == ["15:00", "16:00", "17:00"] and is_rainy(rainy)
    assert len(svc.forecast()["days"]) == 3
    with pytest.raises(WeatherError) as e:
        svc.forecast("", (TODAY + timedelta(days=40)).isoformat())
    assert e.value.status == "out_of_range"
    assert len(svc.forecast("", hourly=True)["days"][0]["hours"]) == 24


@pytest.mark.unit
def test_at_batch_per_item_status():
    http = FakeHttp()
    svc, _ = _svc(http=http)
    d1 = (TODAY + timedelta(days=1)).isoformat()
    r = svc.at([{"key": "a", "at": f"{d1}T16:00:00+02:00"},
                {"key": "b", "place": "Palestra", "date": d1},
                {"key": "c", "place": "Atlantide", "date": d1},
                {"key": "d", "date": (TODAY + timedelta(days=30)).isoformat()}])["items"]
    assert r["a"]["hour"]["rain_prob"] == 80 and r["a"]["day"]["date"] == d1
    assert r["b"]["status"] == "ok"
    assert r["c"]["status"] == "place_not_found"
    assert r["d"]["status"] == "out_of_range"
    assert http.count("forecast") == 2          # one per distinct place


@pytest.mark.unit
def test_provider_down_serves_stale_or_error():
    http = FakeHttp()
    svc, t = _svc(http=http)
    svc.now()
    http.fail_forecast = True
    t["now"] += 31 * 60
    assert svc.now()["stale"] is True
    svc2, _ = _svc(http=FakeHttp(fail_forecast=True))
    with pytest.raises(WeatherError) as e:
        svc2.now()
    assert e.value.status == "error"


@pytest.mark.unit
def test_resolved_places_feed_settings_editor():
    svc, _ = _svc(places=PLACES + [{"id": "x", "name": "Atlantide", "kind": "other"}])
    rows = {r["id"]: r for r in svc.resolved_places()}
    assert rows["casa"]["ok"] and "Milano" in rows["casa"]["resolved"]
    assert rows["x"]["ok"] is False


# ── gateway endpoints ────────────────────────────────────────────────────────
@pytest.fixture()
def client(monkeypatch):
    import app.main as m
    svc, _ = _svc()
    monkeypatch.setattr(m, "weather", svc)
    return TestClient(m.app, raise_server_exceptions=False)


@pytest.mark.api
def test_endpoints(client):
    assert client.get("/api/gateway/weather/now").json()["place"]["name"] == "Casa"
    f = client.get("/api/gateway/weather/forecast", params={"place": "roma", "hourly": "true"}).json()
    assert f["status"] == "ok" and "hours" in f["days"][0]
    assert client.get("/api/gateway/weather/now", params={"place": "Atlantide"}).json()["status"] == "place_not_found"
    at = client.post("/api/gateway/weather/at", json={"items": [{"key": "k", "date": TODAY.isoformat()}]}).json()
    assert at["items"]["k"]["status"] == "ok"
    assert client.post("/api/gateway/weather/at", json={"items": "x"}).status_code == 400
    assert client.get("/api/gateway/weather/place", params={"q": "Milano"}).json()["places"][0]["name"] == "Milano"
    opts = client.get("/api/gateway/weather/places").json()["options"]
    assert {o["value"] for o in opts} == {"casa", "palestra"}


@pytest.mark.api
def test_weather_tools_are_declared(client):
    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"weather_now", "weather_forecast"} <= names


@pytest.mark.api
def test_calendar_ensure(client, monkeypatch):
    import app.main as m

    class Prov:
        name = "google"
        n = 0

        def ensure_calendar(self, name):
            Prov.n += 1
            return "cal-123"
    monkeypatch.setattr(m._calendar_registry, "get", lambda name: Prov() if name == "google" else None)
    m._owned_calendars.clear()
    r = client.post("/api/gateway/calendar/calendars", json={"name": "Allenamenti"}).json()
    assert r == {"status": "ok", "provider": "google", "name": "Allenamenti", "calendar_id": "cal-123"}
    client.post("/api/gateway/calendar/calendars", json={"name": "Allenamenti"})
    assert Prov.n == 1
    assert client.post("/api/gateway/calendar/calendars", json={"name": "X", "provider": "outlook"}).json()["status"] == "unavailable"
    assert client.post("/api/gateway/calendar/calendars", json={}).status_code == 400
