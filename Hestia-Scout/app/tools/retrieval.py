from typing import Any, Optional

import requests

from tools.geocoding import GeocodingService, extract_city_from_text, haversine_km
from tools.schemas import ModuleToolQueryRequest, RealEstateSearchRequest


class ScoutRetrievalService:
    def __init__(self, archive_api_url: str, target_domain: str, geocoder: GeocodingService, hub_api_url: str | None = None):
        self.archive_api_url = archive_api_url
        self.target_domain = target_domain
        self.geocoder = geocoder
        self.hub_api_url = (hub_api_url or "").rstrip("/")

    def _to_number(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _normalize_text(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _compact_entity(self, entity: dict) -> dict:
        specs = entity.get("specs") if isinstance(
            entity.get("specs"), dict) else {}
        location = entity.get("location") if isinstance(
            entity.get("location"), dict) else {}
        return {
            "url": entity.get("url") or entity.get("entity_id"),
            "title": entity.get("title"),
            "price": entity.get("price"),
            "address": entity.get("address"),
            "summary": entity.get("summary"),
            "location": {
                "lat": location.get("lat"),
                "lon": location.get("lon"),
            },
            "specs": {
                "surface_m2": specs.get("surface_m2"),
                "rooms": specs.get("rooms"),
                "bedrooms": specs.get("bedrooms"),
                "bathrooms": specs.get("bathrooms"),
                "elevator": specs.get("elevator"),
                "balcony_or_terrace": specs.get("balcony_or_terrace"),
                "garage_or_parking": specs.get("garage_or_parking"),
            },
        }

    def _fetch_archive_entities(self, req: RealEstateSearchRequest) -> list[dict]:
        search_url = self.archive_api_url.replace(
            "/archive", "/entities/search")

        filters_gt = {}
        filters_lt = {}
        if req.price_min is not None:
            filters_gt["price"] = req.price_min
        if req.rooms_min is not None:
            filters_gt["rooms"] = req.rooms_min
        if req.surface_min is not None:
            filters_gt["surface_m2"] = req.surface_min
        if req.price_max is not None:
            filters_lt["price"] = req.price_max

        payload = {
            "domain": self.target_domain,
            "limit": min(max(req.limit * 5, 30), 100),
            "filters": {},
            "filters_gt": filters_gt or None,
            "filters_lt": filters_lt or None,
            "sort_by": "price" if req.price_max is not None else None,
            "sort_order": "asc" if req.price_max is not None else "desc",
            "query_vector": None,
        }

        if self.hub_api_url:
            response = requests.post(
                f"{self.hub_api_url}/route/archive/api/entities/search",
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": payload,
                    "timeout_seconds": 8,
                },
                timeout=9,
            )
            if response.status_code != 200:
                return []
            routed = response.json() or {}
            if int(routed.get("status_code", 500)) >= 400:
                return []
            rows = routed.get("payload") or []
            return rows if isinstance(rows, list) else []

        response = requests.post(search_url, json=payload, timeout=8)
        if response.status_code != 200:
            return []
        rows = response.json() or []
        return rows if isinstance(rows, list) else []

    def _score_entity(self, entity: dict, req: RealEstateSearchRequest, center_geo: Optional[tuple[float, float]]) -> float:
        score = 0.0

        q = self._normalize_text(req.query)
        if q:
            text_blob = " ".join([
                self._normalize_text(entity.get("title")),
                self._normalize_text(entity.get("summary")),
                self._normalize_text(entity.get("address")),
            ])
            for token in [t for t in q.split() if len(t) > 2][:12]:
                if token in text_blob:
                    score += 1.2

        if req.city:
            city_l = self._normalize_text(req.city)
            city_blob = " ".join([
                self._normalize_text(entity.get("title")),
                self._normalize_text(entity.get("summary")),
                self._normalize_text(entity.get("address")),
            ])
            if city_l and city_l in city_blob:
                score += 2.0

        price = self._to_number(entity.get("price"))
        specs = entity.get("specs") if isinstance(
            entity.get("specs"), dict) else {}
        rooms = self._to_number(specs.get("rooms"))
        surface = self._to_number(specs.get("surface_m2"))

        if req.price_max is not None and price is not None and price <= req.price_max:
            score += 2.0
        if req.price_min is not None and price is not None and price >= req.price_min:
            score += 1.0
        if req.rooms_min is not None and rooms is not None and rooms >= req.rooms_min:
            score += 1.5
        if req.surface_min is not None and surface is not None and surface >= req.surface_min:
            score += 1.0

        if center_geo:
            location = entity.get("location") if isinstance(
                entity.get("location"), dict) else {}
            lat = self._to_number(location.get("lat"))
            lon = self._to_number(location.get("lon"))
            if lat is not None and lon is not None:
                distance = haversine_km(center_geo[0], center_geo[1], lat, lon)
                score += max(0.0, 2.5 - (distance / max(req.radius_km, 1.0)))

        return score

    def _apply_geo_filter(self, entities: list[dict], req: RealEstateSearchRequest, center_geo: Optional[tuple[float, float]]) -> list[dict]:
        if not center_geo:
            return entities

        should_filter_by_distance = req.nearby or bool(req.city)
        if not should_filter_by_distance:
            return entities

        filtered = []
        for entity in entities:
            location = entity.get("location") if isinstance(
                entity.get("location"), dict) else {}
            lat = self._to_number(location.get("lat"))
            lon = self._to_number(location.get("lon"))
            if lat is None or lon is None:
                continue
            distance = haversine_km(center_geo[0], center_geo[1], lat, lon)
            if distance <= req.radius_km:
                entity = dict(entity)
                entity["distance_km"] = round(distance, 2)
                filtered.append(entity)
        return filtered

    def from_module_query(self, req: ModuleToolQueryRequest) -> RealEstateSearchRequest:
        pref_blob = " ".join(req.preferences)
        merged_text = f"{req.query} {pref_blob}".strip()

        city = req.filters.get("city") if isinstance(
            req.filters, dict) else None
        city = city or extract_city_from_text(merged_text)

        nearby = bool(req.filters.get("nearby", False)) if isinstance(
            req.filters, dict) else False
        if any(token in merged_text.lower() for token in ["nearby", "vicino", "dintorni", "vicinanze"]):
            nearby = True

        radius_km = 20.0
        if isinstance(req.filters, dict) and req.filters.get("radius_km") is not None:
            try:
                radius_km = float(req.filters.get("radius_km"))
            except Exception:
                radius_km = 20.0

        price_max = req.filters_lt.get("price") if isinstance(
            req.filters_lt, dict) else None
        price_min = req.filters_gt.get("price") if isinstance(
            req.filters_gt, dict) else None
        rooms_min = req.filters_gt.get("rooms") if isinstance(
            req.filters_gt, dict) else None
        surface_min = req.filters_gt.get("surface_m2") if isinstance(
            req.filters_gt, dict) else None

        return RealEstateSearchRequest(
            query=req.query,
            limit=req.limit,
            city=city,
            nearby=nearby,
            radius_km=radius_km,
            price_max=price_max,
            price_min=price_min,
            rooms_min=rooms_min,
            surface_min=surface_min,
        )

    @staticmethod
    def _fmt_price(value) -> str:
        if value is None:
            return ""
        try:
            n = float(value)
            if n >= 1000000:
                return f"{n/1000000:.1f}M €"
            return f"{int(n):,} €".replace(",", ".")
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _fmt_surface(value) -> str:
        if value is None:
            return ""
        try:
            return f"{int(float(value))} m²"
        except (ValueError, TypeError):
            return ""

    @staticmethod
    def _fmt_rooms(value) -> str:
        if value is None:
            return ""
        try:
            n = int(float(value))
            return f"{n} locali" if n > 1 else "1 locale"
        except (ValueError, TypeError):
            return ""

    def search(self, req: RealEstateSearchRequest) -> list[dict]:
        entities = self._fetch_archive_entities(req)

        center_geo = None
        if req.city:
            center_geo = self.geocoder.geocode(req.city)

        geo_filtered = self._apply_geo_filter(entities, req, center_geo)
        working_set = geo_filtered if (req.nearby and center_geo) else entities

        ranked = sorted(
            working_set,
            key=lambda entity: self._score_entity(entity, req, center_geo),
            reverse=True,
        )
        return [self._compact_entity(entity) for entity in ranked[: req.limit]]

    def search_formatted(self, req: RealEstateSearchRequest) -> str:
        """Return pre-formatted markdown with one [title](url) bullet per listing.
        The LLM can pass this through directly without needing to format links."""
        items = self.search(req)
        if not items:
            return "Nessuna casa trovata."
        lines = []
        for item in items:
            title = str(item.get("title") or "Casa").strip()
            url = str(item.get("url") or "").strip()
            price = self._fmt_price(item.get("price"))
            address = str(item.get("address") or "").strip()
            specs = item.get("specs") if isinstance(item.get("specs"), dict) else {}
            surface = self._fmt_surface(specs.get("surface_m2"))
            rooms = self._fmt_rooms(specs.get("rooms"))

            detail_parts = [p for p in [price, surface, rooms, address] if p]
            detail = " · ".join(detail_parts) if detail_parts else ""

            if url:
                label = f"{title}"
                if detail:
                    label += f" — {detail}"
                lines.append(f"• [{label}]({url})")
            else:
                lines.append(f"• {title} — {detail}" if detail else f"• {title}")

        return f"🏠 **Case disponibili** ({len(items)})\n\n" + "\n\n".join(lines)
