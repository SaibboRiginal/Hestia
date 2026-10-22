"""Weather provider — Open-Meteo (free, no key, no account) behind one small interface.

Hecate is the only place in Hestia that talks to the weather service: modules and the assistant ask Hecate
(``/api/gateway/weather/*`` through Hub, tools ``weather_*``). One upstream call per place fetches current
conditions + 16 days (daily and hourly); it is cached ``hecate.weather.cache_minutes`` and every question
(now, a day range, a given hour) is answered from that one blob.

Places: Marko's personal places (``themis.personal.places``: ``[{id, name, address, kind, lat?, lon?}]``, one
``kind=home`` = default). A ``place`` argument may be a saved place's name («palestra»), its address, or any
city; Open-Meteo geocoding is city-level, so an address resolves through its city part.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from datetime import date, timedelta
from typing import Any, Callable

import requests

logger = logging.getLogger("hestia_hecate.weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_DAYS = 16
_TIMEOUT = 8

# WMO weather interpretation codes → Italian text + a generic icon name (clients map it to their own icons).
WMO: dict[int, tuple[str, str]] = {
    0: ("sereno", "sun"), 1: ("poco nuvoloso", "sun"), 2: ("parzialmente nuvoloso", "cloud-sun"),
    3: ("coperto", "cloud"), 45: ("nebbia", "fog"), 48: ("nebbia con brina", "fog"),
    51: ("pioviggine leggera", "drizzle"), 53: ("pioviggine", "drizzle"), 55: ("pioviggine intensa", "drizzle"),
    56: ("pioviggine gelata", "drizzle"), 57: ("pioviggine gelata intensa", "drizzle"),
    61: ("pioggia debole", "rain"), 63: ("pioggia", "rain"), 65: ("pioggia forte", "rain"),
    66: ("pioggia gelata", "rain"), 67: ("pioggia gelata forte", "rain"),
    71: ("neve debole", "snow"), 73: ("neve", "snow"), 75: ("neve forte", "snow"), 77: ("nevischio", "snow"),
    80: ("rovesci deboli", "rain"), 81: ("rovesci", "rain"), 82: ("rovesci violenti", "rain"),
    85: ("rovesci di neve", "snow"), 86: ("forti rovesci di neve", "snow"),
    95: ("temporale", "storm"), 96: ("temporale con grandine", "storm"), 99: ("temporale con grandine forte", "storm"),
}
RAINY_ICONS = {"drizzle", "rain", "snow", "storm"}

_CURRENT = "temperature_2m,apparent_temperature,relative_humidity_2m,is_day,weather_code,wind_speed_10m,precipitation"
_DAILY = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
          "wind_speed_10m_max,sunrise,sunset")
_HOURLY = "temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m,is_day"


class WeatherError(Exception):
    """Something the caller should read as ``status`` (needs_place, place_not_found, out_of_range, error)."""

    def __init__(self, status: str, message: str, hint: str = ""):
        super().__init__(message)
        self.status, self.message, self.hint = status, message, hint

    def as_dict(self) -> dict:
        out = {"status": self.status, "error": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


def condition(code: Any) -> tuple[str, str]:
    try:
        return WMO.get(int(code), ("—", "cloud"))
    except (TypeError, ValueError):
        return ("—", "cloud")


def _norm(text: Any) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ,]", " ", s)).strip()


def _round(v: Any, nd: int = 0) -> Any:
    if v is None:
        return None
    try:
        return round(float(v), nd) if nd else int(round(float(v)))
    except (TypeError, ValueError):
        return None


class WeatherService:
    """Resolves places and answers weather questions from a cached Open-Meteo forecast."""

    def __init__(self, places: Callable[[], list], cache_minutes: Callable[[], int],
                 http_get: Callable[..., Any] | None = None, clock: Callable[[], float] = time.time):
        self._places = places
        self._cache_minutes = cache_minutes
        self._get = http_get or (lambda url, params: requests.get(url, params=params, timeout=_TIMEOUT))
        self._clock = clock
        self._lock = threading.Lock()
        self._forecasts: dict[tuple[float, float], tuple[float, dict]] = {}
        self._geo: dict[str, tuple[float, list[dict]]] = {}

    # ── upstream ────────────────────────────────────────────────────────────
    def _json(self, url: str, params: dict) -> dict:
        resp = self._get(url, params)
        if getattr(resp, "status_code", 200) >= 400:
            raise WeatherError("error", f"servizio meteo: HTTP {resp.status_code}")
        return resp.json() or {}

    def geocode(self, query: str, count: int = 5) -> list[dict]:
        """City-level candidates for ``query`` («Milano», «Milano, IT», «Via Roma 3, 20121 Milano»)."""
        q = str(query or "").strip()
        if not q:
            return []
        key = _norm(q)
        ttl = 7 * 86400
        with self._lock:
            hit = self._geo.get(key)
            if hit and self._clock() - hit[0] < ttl:
                return hit[1]
        parts = [p.strip() for p in q.split(",") if p.strip()]
        found: list[dict] = []
        # 1) «Città, Paese/Regione»  2) the whole text  3) each part from the end (address → its city)
        tries: list[tuple[str, str]] = []
        if len(parts) == 2 and len(parts[1]) <= 30:
            tries.append((parts[0], parts[1]))
        tries.append((q, ""))
        for p in reversed(parts):
            name = re.sub(r"\b\d{4,5}\b", "", p).strip()
            if name and not name[:1].isdigit() and not re.match(r"(?i)^(via|viale|piazza|corso|largo|vicolo|strada)\b", name):
                tries.append((name, ""))
        seen: set[str] = set()
        for name, qualifier in tries:
            if (name, qualifier) in seen:
                continue
            seen.add((name, qualifier))
            data = self._json(GEOCODING_URL, {"name": name, "count": max(count, 10) if qualifier else count,
                                              "language": "it", "format": "json"})
            rows = data.get("results") or []
            if qualifier:
                qn = _norm(qualifier)
                rows = [r for r in rows if qn in (_norm(r.get("country")), _norm(r.get("country_code")),
                                                  _norm(r.get("admin1")), _norm(r.get("admin2")))]
            if rows:
                found = [{"name": r.get("name"), "region": r.get("admin1") or "", "country": r.get("country") or "",
                          "country_code": r.get("country_code") or "", "lat": r.get("latitude"),
                          "lon": r.get("longitude"), "timezone": r.get("timezone") or "auto"} for r in rows[:count]]
                break
        with self._lock:
            self._geo[key] = (self._clock(), found)
        logger.info("event=weather_place_resolved query_len=%s found=%s", len(q), len(found))
        return found

    def _forecast(self, lat: float, lon: float) -> tuple[dict, bool, bool]:
        """(blob, cached, stale) for a point; one upstream call per point per cache window."""
        key = (round(float(lat), 2), round(float(lon), 2))
        ttl = max(1, int(self._cache_minutes() or 30)) * 60
        with self._lock:
            hit = self._forecasts.get(key)
        if hit and self._clock() - hit[0] < ttl:
            return hit[1], True, False
        try:
            blob = self._json(FORECAST_URL, {"latitude": key[0], "longitude": key[1], "current": _CURRENT,
                                             "daily": _DAILY, "hourly": _HOURLY, "timezone": "auto",
                                             "forecast_days": MAX_DAYS})
        except Exception as exc:
            logger.warning("[🔄] event=weather_fetch_failed lat=%s lon=%s error=%s cached=%s",
                           key[0], key[1], exc, bool(hit))
            if hit:
                return hit[1], True, True
            if isinstance(exc, WeatherError):
                raise
            raise WeatherError("error", "servizio meteo non raggiungibile", "riprova tra poco")
        with self._lock:
            self._forecasts[key] = (self._clock(), blob)
        logger.info("event=weather_fetched lat=%s lon=%s cached=false", key[0], key[1])
        return blob, False, False

    # ── places ──────────────────────────────────────────────────────────────
    def places(self) -> list[dict]:
        out = []
        for p in self._places() or []:
            if isinstance(p, dict) and (p.get("name") or p.get("address")):
                out.append(p)
        return out

    def home(self) -> dict | None:
        ps = self.places()
        return next((p for p in ps if str(p.get("kind") or "") == "home"), None)

    def match_saved(self, text: str) -> dict | None:
        """A saved place whose name, or address, matches ``text`` (exact first, then contained)."""
        t = _norm(text)
        if not t:
            return None
        ps = self.places()
        for field in ("name", "address"):
            for p in ps:
                if _norm(p.get(field)) == t:
                    return p
        for p in ps:
            n = _norm(p.get("name"))
            if n and re.search(rf"\b{re.escape(n)}\b", t):
                return p
        return None

    def resolve(self, place: str = "") -> dict:
        """``{name, label, lat, lon, saved?, kind?}`` for a place text, a saved place or home."""
        text = str(place or "").strip()
        saved = self.match_saved(text) if text else self.home()
        if not text and not saved:
            raise WeatherError("needs_place", "nessun luogo indicato e nessuna Casa tra i tuoi luoghi",
                               "aggiungi Casa nei tuoi luoghi (Impostazioni → Personali → Luoghi) o indica un luogo")
        if saved:
            label = str(saved.get("name") or saved.get("address"))
            if saved.get("lat") not in (None, "") and saved.get("lon") not in (None, ""):
                return {"name": label, "label": label, "lat": float(saved["lat"]), "lon": float(saved["lon"]),
                        "saved": saved.get("id") or label, "kind": saved.get("kind") or "other"}
            query = str(saved.get("address") or saved.get("name") or "")
            found = self.geocode(query, count=1)
            if not found:
                raise WeatherError("place_not_found", f"non trovo «{label}» sulla mappa",
                                   "nei tuoi luoghi scrivi la città (es. «Milano») o aggiungi le coordinate")
            g = found[0]
            return {"name": label, "label": f"{label} · {g['name']}", "lat": g["lat"], "lon": g["lon"],
                    "saved": saved.get("id") or label, "kind": saved.get("kind") or "other",
                    "region": g["region"], "country": g["country"]}
        found = self.geocode(text, count=1)
        if not found:
            raise WeatherError("place_not_found", f"non trovo «{text}»", "prova con «Città, Paese»")
        g = found[0]
        return {"name": g["name"], "label": ", ".join(x for x in (g["name"], g["region"], g["country_code"]) if x),
                "lat": g["lat"], "lon": g["lon"], "region": g["region"], "country": g["country"]}

    def resolved_places(self) -> list[dict]:
        """Every saved place with what it resolves to (settings editor «Luoghi»)."""
        out = []
        for p in self.places():
            row = {"id": p.get("id") or p.get("name"), "name": p.get("name"), "kind": p.get("kind") or "other"}
            try:
                r = self.resolve(str(p.get("name") or p.get("address")))
                row.update({"ok": True, "resolved": r["label"], "lat": r["lat"], "lon": r["lon"]})
            except WeatherError as exc:
                row.update({"ok": False, "error": exc.message})
            out.append(row)
        return out

    # ── answers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _place_out(r: dict, blob: dict) -> dict:
        return {"name": r["name"], "label": r["label"], "lat": r["lat"], "lon": r["lon"],
                "timezone": blob.get("timezone") or "", **({"saved": r["saved"]} if r.get("saved") else {})}

    @staticmethod
    def _days(blob: dict) -> list[dict]:
        d = blob.get("daily") or {}
        out = []
        for i, day in enumerate(d.get("time") or []):
            def at(k, _i=i):
                arr = d.get(k) or []
                return arr[_i] if _i < len(arr) else None
            text, icon = condition(at("weather_code"))
            out.append({"date": day, "min_c": _round(at("temperature_2m_min")), "max_c": _round(at("temperature_2m_max")),
                        "condition": text, "icon": icon, "code": at("weather_code"),
                        "rain_mm": _round(at("precipitation_sum"), 1), "rain_prob": _round(at("precipitation_probability_max")),
                        "wind_kmh": _round(at("wind_speed_10m_max")),
                        "sunrise": str(at("sunrise") or "")[11:16], "sunset": str(at("sunset") or "")[11:16]})
        return out

    @staticmethod
    def _hours(blob: dict) -> list[dict]:
        h = blob.get("hourly") or {}
        out = []
        for i, t in enumerate(h.get("time") or []):
            def at(k, _i=i):
                arr = h.get(k) or []
                return arr[_i] if _i < len(arr) else None
            text, icon = condition(at("weather_code"))
            out.append({"time": t, "temp_c": _round(at("temperature_2m")), "feels_c": _round(at("apparent_temperature")),
                        "rain_prob": _round(at("precipitation_probability")), "rain_mm": _round(at("precipitation"), 1),
                        "condition": text, "icon": icon, "code": at("weather_code"),
                        "wind_kmh": _round(at("wind_speed_10m")), "is_day": bool(at("is_day"))})
        return out

    @classmethod
    def _rain_hours(cls, hours: list[dict], day: str) -> list[str]:
        return [h["time"][11:16] for h in hours if h["time"].startswith(day)
                and ((h.get("rain_prob") or 0) >= 50 or (h.get("rain_mm") or 0) >= 0.5)]

    def now(self, place: str = "") -> dict:
        r = self.resolve(place)
        blob, cached, stale = self._forecast(r["lat"], r["lon"])
        c = blob.get("current") or {}
        text, icon = condition(c.get("weather_code"))
        days = self._days(blob)
        today = dict(days[0]) if days else {}
        if today:
            today["rain_hours"] = self._rain_hours(self._hours(blob), today["date"])
        out = {"status": "ok", "place": self._place_out(r, blob),
               "now": {"time": c.get("time"), "temp_c": _round(c.get("temperature_2m")),
                       "feels_c": _round(c.get("apparent_temperature")), "condition": text, "icon": icon,
                       "code": c.get("weather_code"), "is_day": bool(c.get("is_day")),
                       "wind_kmh": _round(c.get("wind_speed_10m")), "humidity": _round(c.get("relative_humidity_2m")),
                       "rain_mm": _round(c.get("precipitation"), 1)},
               "today": today, "cached": cached}
        if stale:
            out["stale"] = True
        return out

    def forecast(self, place: str = "", date_from: str = "", date_to: str = "", hourly: bool = False) -> dict:
        r = self.resolve(place)
        blob, cached, stale = self._forecast(r["lat"], r["lon"])
        days = self._days(blob)
        if not days:
            raise WeatherError("error", "previsione vuota")
        first, last = date.fromisoformat(days[0]["date"]), date.fromisoformat(days[-1]["date"])
        try:
            d_from = date.fromisoformat(date_from) if date_from else first
            d_to = date.fromisoformat(date_to) if date_to else max(d_from, min(first + timedelta(days=2), last))
        except ValueError:
            raise WeatherError("error", "date non valide (formato AAAA-MM-GG)")
        if d_to < d_from:
            d_from, d_to = d_to, d_from
        if d_to < first or d_from > last:
            raise WeatherError("out_of_range", f"ho la previsione dal {first.isoformat()} al {last.isoformat()}",
                               "il meteo arriva fino a 16 giorni avanti e non copre il passato")
        d_from, d_to = max(d_from, first), min(d_to, last)
        hours = self._hours(blob)
        picked = []
        for d in days:
            if d_from.isoformat() <= d["date"] <= d_to.isoformat():
                row = dict(d, rain_hours=self._rain_hours(hours, d["date"]))
                if hourly:
                    row["hours"] = [h for h in hours if h["time"].startswith(d["date"])]
                picked.append(row)
        out = {"status": "ok", "place": self._place_out(r, blob), "days": picked, "cached": cached}
        if stale:
            out["stale"] = True
        return out

    def at(self, items: list[dict]) -> dict:
        """Weather at (place, hour or day) for many items — agenda chips and activity planning.

        Each item: ``{key, place?, at?: ISO datetime, date?: YYYY-MM-DD}``; answers keyed by ``key``. One forecast
        per distinct place; a failing item answers its own status, never the whole batch."""
        out: dict[str, Any] = {}
        resolved: dict[str, Any] = {}
        for it in (items or [])[:200]:
            if not isinstance(it, dict):
                continue
            key = str(it.get("key") or len(out))
            place = str(it.get("place") or "")
            try:
                if place not in resolved:
                    try:
                        r = self.resolve(place)
                        blob, _, stale = self._forecast(r["lat"], r["lon"])
                        resolved[place] = (r, blob, stale)
                    except WeatherError as exc:
                        resolved[place] = exc
                cached = resolved[place]
                if isinstance(cached, WeatherError):
                    raise cached
                r, blob, stale = cached
                when = str(it.get("at") or "")
                day = str(it.get("date") or when[:10])
                days = {d["date"]: d for d in self._days(blob)}
                if day not in days:
                    out[key] = {"status": "out_of_range"}
                    continue
                row: dict[str, Any] = {"status": "ok", "place": r["label"], **({"stale": True} if stale else {}),
                                       "day": days[day]}
                if len(when) >= 13:
                    hour = when[:13]
                    h = next((x for x in self._hours(blob) if x["time"].startswith(hour)), None)
                    if h:
                        row["hour"] = h
                out[key] = row
            except WeatherError as exc:
                out[key] = exc.as_dict()
        return {"status": "ok", "items": out}


def is_rainy(day_or_hour: dict | None) -> bool:
    """Shared reading of «it rains» for a day/hour row: probability ≥ 50 % or ≥ 1 mm, or a rainy condition."""
    if not day_or_hour:
        return False
    return ((day_or_hour.get("rain_prob") or 0) >= 50 or (day_or_hour.get("rain_mm") or 0) >= 1
            or day_or_hour.get("icon") in RAINY_ICONS and (day_or_hour.get("rain_prob") or 0) >= 30)

