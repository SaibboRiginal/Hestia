import math
import re
from typing import Optional

import requests


class GeocodingService:
    def __init__(self, user_agent: str = "hestia-scout/1.0"):
        self.user_agent = user_agent
        self._cache: dict[str, tuple[float, float]] = {}

    def geocode(self, query: str) -> Optional[tuple[float, float]]:
        if not query:
            return None
        normalized = re.sub(r"\s+", " ", str(query).strip().lower())
        if not normalized:
            return None

        if normalized in self._cache:
            return self._cache[normalized]

        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": normalized, "format": "json", "limit": 1},
                headers={"User-Agent": self.user_agent},
                timeout=6,
            )
            if response.status_code != 200:
                return None
            data = response.json() or []
            if not data:
                return None

            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            self._cache[normalized] = (lat, lon)
            return lat, lon
        except Exception:
            return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


def extract_city_from_text(text: str) -> Optional[str]:
    merged = (text or "").lower()
    match = re.search(
        r"\b(?:in|a|near|vicino\s+a|zona)\s+([a-zà-öø-ÿ'\- ]{2,50})", merged, flags=re.IGNORECASE)
    if not match:
        return None
    city = re.sub(r"\s+", " ", match.group(1)).strip(" .,!?:;")
    city = city.split(" e ")[0].split(" and ")[0].strip()
    return city or None
