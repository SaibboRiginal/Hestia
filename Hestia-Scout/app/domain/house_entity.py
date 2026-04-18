from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field

from domain.listing_status import ListingStatus, coerce_listing_status


class HouseLocation(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    query: Optional[str] = None
    source: Optional[str] = None


class HouseSpecs(BaseModel):
    floor: Optional[str] = None
    rooms: Optional[int] = None
    heating: Optional[str] = None
    bedrooms: Optional[int] = None
    elevator: bool = False
    bathrooms: Optional[int] = None
    surface_m2: Optional[float] = None
    garage_or_parking: bool = False
    balcony_or_terrace: bool = False


class HousePricing(BaseModel):
    price: Optional[int] = None
    price_per_m2: Optional[int] = None
    condo_fees: Optional[str] = None
    condo_fees_monthly_eur: Optional[int] = None


class HouseEnergy(BaseModel):
    year_built: Optional[int] = None
    property_state: Optional[str] = None
    heating: Optional[str] = None
    climatization: Optional[str] = None


class HouseContact(BaseModel):
    reference_id: Optional[str] = None
    agent_name: Optional[str] = None
    agency_name: Optional[str] = None
    updated_text: Optional[str] = None


class HouseMedia(BaseModel):
    photo_count: Optional[int] = None
    images: list[str] = Field(default_factory=list)


class HouseSurfaceDetail(BaseModel):
    name: Optional[str] = None
    floor: Optional[str] = None
    surface_m2: Optional[float] = None
    coefficient_pct: Optional[int] = None
    surface_type: Optional[str] = None
    commercial_surface_m2: Optional[float] = None


class HouseListingContext(BaseModel):
    nav_position: Optional[str] = None
    position: Optional[int] = None
    total_results: Optional[int] = None
    contact_reason_default: Optional[str] = None


class HousePayload(BaseModel):
    url: str
    source_site: Optional[str] = None
    title: Optional[str] = None
    price: Optional[int] = None
    address: Optional[str] = None
    summary: Optional[str] = None
    image: Optional[str] = None
    # Availability status inferred from email signals or page enrichment.
    # Defaults to unknown — callers must not treat unknown as unavailable.
    listing_status: ListingStatus = ListingStatus.UNKNOWN
    specs: HouseSpecs = Field(default_factory=HouseSpecs)
    location: Optional[HouseLocation] = None
    pricing: Optional[HousePricing] = None
    energy: Optional[HouseEnergy] = None
    contact: Optional[HouseContact] = None
    media: Optional[HouseMedia] = None
    surfaces: list[HouseSurfaceDetail] = Field(default_factory=list)
    characteristics: dict[str, str] = Field(default_factory=dict)
    additional_features: list[str] = Field(default_factory=list)
    listing: Optional[HouseListingContext] = None
    extras: dict = Field(default_factory=dict)


class HouseEntity(BaseModel):
    entity_id: str
    domain: str
    status: str = "active"
    payload: HousePayload

    @classmethod
    def from_extracted(
        cls,
        *,
        entity_id: str,
        payload: dict,
        domain: str,
        status: str = "active",
    ) -> "HouseEntity":
        normalized_id = _normalize_listing_url(entity_id)

        payload_copy = dict(payload or {})
        payload_url = str(payload_copy.get("url") or normalized_id).strip()
        payload_copy["url"] = _normalize_listing_url(payload_url)

        specs = payload_copy.get("specs") if isinstance(
            payload_copy.get("specs"), dict) else {}
        payload_copy["specs"] = _normalize_specs(specs)

        location = payload_copy.get("location") if isinstance(
            payload_copy.get("location"), dict) else None
        if location:
            payload_copy["location"] = {
                "lat": _to_float(location.get("lat")),
                "lon": _to_float(location.get("lon")),
                "query": _to_str_or_none(location.get("query")),
                "source": _to_str_or_none(location.get("source")),
            }

        payload_copy["price"] = _to_int_or_none(payload_copy.get("price"))
        payload_copy["source_site"] = _normalize_source_site(payload_copy)
        payload_copy["title"] = _to_str_or_none(payload_copy.get("title"))
        payload_copy["address"] = _to_str_or_none(payload_copy.get("address"))
        payload_copy["summary"] = _to_str_or_none(payload_copy.get("summary"))
        payload_copy["image"] = _to_str_or_none(payload_copy.get("image"))

        extras = payload_copy.get("extras")
        payload_copy["extras"] = extras if isinstance(extras, dict) else {}

        payload_copy["pricing"] = _normalize_pricing(payload_copy)
        payload_copy["energy"] = _normalize_energy(payload_copy)
        payload_copy["contact"] = _normalize_contact(payload_copy)
        payload_copy["media"] = _normalize_media(payload_copy)
        payload_copy["surfaces"] = _normalize_surfaces(
            payload_copy.get("surfaces"))
        payload_copy["characteristics"] = _normalize_characteristics(
            payload_copy.get("characteristics")
        )
        payload_copy["additional_features"] = _normalize_additional_features(
            payload_copy.get("additional_features")
        )
        payload_copy["listing"] = _normalize_listing_context(payload_copy)

        raw_listing_status = payload_copy.pop("listing_status", None)
        payload_copy["listing_status"] = coerce_listing_status(
            raw_listing_status)

        return cls(
            entity_id=normalized_id,
            domain=str(domain or "").strip() or "real_estate",
            status=str(status or "active").strip() or "active",
            payload=HousePayload(**payload_copy),
        )

    def to_archive_upsert_payload(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "domain": self.domain,
            "status": self.status,
            "payload": self.payload.model_dump(),
        }


def _normalize_listing_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(str(url).strip())
        clean_path = parsed.path.rstrip("/")
        return urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            clean_path,
            "", "", "",
        ))
    except Exception:
        return str(url).strip()


def _normalize_specs(specs: dict) -> dict:
    return {
        "floor": _to_str_or_none(specs.get("floor")),
        "rooms": _to_int_or_none(specs.get("rooms")),
        "heating": _to_str_or_none(specs.get("heating")),
        "bedrooms": _to_int_or_none(specs.get("bedrooms")),
        "elevator": _to_bool(specs.get("elevator")),
        "bathrooms": _to_int_or_none(specs.get("bathrooms")),
        "surface_m2": _to_float(specs.get("surface_m2")),
        "garage_or_parking": _to_bool(specs.get("garage_or_parking")),
        "balcony_or_terrace": _to_bool(specs.get("balcony_or_terrace")),
    }


def _normalize_pricing(payload: dict) -> Optional[dict]:
    source = payload.get("pricing") if isinstance(
        payload.get("pricing"), dict) else {}
    extras = payload.get("extras") if isinstance(
        payload.get("extras"), dict) else {}

    result = {
        "price": _to_int_or_none(source.get("price") or payload.get("price")),
        "price_per_m2": _to_int_or_none(source.get("price_per_m2") or extras.get("price_per_m2")),
        "condo_fees": _to_str_or_none(source.get("condo_fees") or extras.get("condo_fees")),
        "condo_fees_monthly_eur": _to_int_or_none(
            source.get("condo_fees_monthly_eur") or extras.get(
                "condo_fees_monthly_eur")
        ),
    }
    return result if any(v is not None for v in result.values()) else None


def _normalize_energy(payload: dict) -> Optional[dict]:
    source = payload.get("energy") if isinstance(
        payload.get("energy"), dict) else {}
    extras = payload.get("extras") if isinstance(
        payload.get("extras"), dict) else {}
    specs = payload.get("specs") if isinstance(
        payload.get("specs"), dict) else {}

    result = {
        "year_built": _to_int_or_none(source.get("year_built") or extras.get("year_built")),
        "property_state": _to_str_or_none(source.get("property_state") or extras.get("property_state")),
        "heating": _to_str_or_none(source.get("heating") or specs.get("heating") or extras.get("heating")),
        "climatization": _to_str_or_none(source.get("climatization") or extras.get("climatization")),
    }
    return result if any(v is not None for v in result.values()) else None


def _normalize_contact(payload: dict) -> Optional[dict]:
    source = payload.get("contact") if isinstance(
        payload.get("contact"), dict) else {}
    extras = payload.get("extras") if isinstance(
        payload.get("extras"), dict) else {}

    result = {
        "reference_id": _to_str_or_none(source.get("reference_id") or extras.get("reference_id")),
        "agent_name": _to_str_or_none(source.get("agent_name") or extras.get("agent_name")),
        "agency_name": _to_str_or_none(source.get("agency_name") or extras.get("agency_name")),
        "updated_text": _to_str_or_none(source.get("updated_text") or extras.get("updated_text")),
    }
    return result if any(v is not None for v in result.values()) else None


def _normalize_media(payload: dict) -> Optional[dict]:
    source = payload.get("media") if isinstance(
        payload.get("media"), dict) else {}
    extras = payload.get("extras") if isinstance(
        payload.get("extras"), dict) else {}

    images = source.get("images") if isinstance(
        source.get("images"), list) else []
    clean_images = []
    for image in images:
        text = _to_str_or_none(image)
        if text and text not in clean_images:
            clean_images.append(text)

    result = {
        "photo_count": _to_int_or_none(source.get("photo_count") or extras.get("photo_count"))
        or (len(clean_images) if clean_images else None),
        "images": clean_images,
    }

    if result["photo_count"] is None and not result["images"]:
        return None
    return result


def _normalize_surfaces(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    normalized: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "name": _to_str_or_none(item.get("name")),
            "floor": _to_str_or_none(item.get("floor")),
            "surface_m2": _to_float(item.get("surface_m2")),
            "coefficient_pct": _to_int_or_none(item.get("coefficient_pct")),
            "surface_type": _to_str_or_none(item.get("surface_type")),
            "commercial_surface_m2": _to_float(item.get("commercial_surface_m2")),
        })
    return normalized


def _normalize_additional_features(value) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _to_str_or_none(item)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_characteristics(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, item in value.items():
        k = _to_str_or_none(key)
        v = _to_str_or_none(item)
        if k and v:
            normalized[k] = v
    return normalized


def _normalize_listing_context(payload: dict) -> Optional[dict]:
    source = payload.get("listing") if isinstance(
        payload.get("listing"), dict) else {}
    result = {
        "nav_position": _to_str_or_none(source.get("nav_position")),
        "position": _to_int_or_none(source.get("position")),
        "total_results": _to_int_or_none(source.get("total_results")),
        "contact_reason_default": _to_str_or_none(source.get("contact_reason_default")),
    }
    return result if any(v is not None for v in result.values()) else None


def _normalize_source_site(payload: dict) -> Optional[str]:
    explicit = _to_str_or_none(payload.get("source_site"))
    if explicit:
        return explicit.lower()

    url = str(payload.get("url") or "").lower()
    if "immobiliare.it" in url:
        return "immobiliare"
    if "idealista.it" in url:
        return "idealista"
    return None


def _to_str_or_none(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except Exception:
        return None


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(" ", "")
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    try:
        return float(text)
    except Exception:
        return None


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on", "si", "sì"}
