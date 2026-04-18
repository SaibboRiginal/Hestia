"""Scout extraction pipeline.

Orchestrates:
    - Email sanitization -> LLM extraction
    - Listing enrichment via Atlas (web fetch) + per-site handlers
    - Geocoding enrichment via Nominatim
"""

import json
import os
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from core.atlas_client import AtlasClient
from evaluators.cloud_evaluator import CloudEvaluator
from tools.geocoding import GeocodingService
from worker.sites.registry import SiteHandlerRegistry


# ─────────────────────────────────────────────────────────────────────
#  Email sanitization
# ─────────────────────────────────────────────────────────────────────

def sanitize_email_for_ai(raw_html: str) -> str:
    """Strip email HTML down to clean text with ``[PROPERTY_LINK: url]`` markers."""
    if not raw_html or "Could not extract text body" in raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    for element in soup(["style", "script", "head", "title", "meta", "[document]"]):
        element.extract()

    for a_tag in soup.find_all("a", href=True):
        url = a_tag["href"]
        if "idealista.it" in url and any(
            x in url for x in ("immobile", "prodotto", "rapprochement")
        ):
            clean_text = a_tag.get_text(strip=True)
            a_tag.replace_with(f" {clean_text} [PROPERTY_LINK: {url}] ")
        else:
            a_tag.decompose()

    text = soup.get_text(separator="\n")
    return re.sub(r"\n\s*\n", "\n\n", text).strip()


# ─────────────────────────────────────────────────────────────────────
#  LLM brain
# ─────────────────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM_PROMPT = """\
You are Hestia, an advanced real estate data extraction AI.
Extract ALL property details into a STRICT JSON ARRAY.

CRITICAL:
1. Each house in the text has a link marked as [PROPERTY_LINK: URL].
2. You MUST extract this URL and use it as the "entity_id".
3. You MUST also include the URL inside the payload as "url".
4. If an address or city is present, preserve it clearly in payload.address.
5. If a property has no link, skip it.
6. For summary: extract the FULL description text from the email. \
DO NOT truncate or summarize. Include ALL details provided.
7. For listing_status: infer from the email text. Use ONLY one of:
   "available" | "in_negotiation" | "investment_occupied" | "sold" | "unknown"
   - "in_negotiation" if the email mentions "trattativa", "under offer" or similar.
   - "investment_occupied" if the listing is rented out or sold as investment with tenants.
   - "sold" if the property is already sold.
   - "available" if explicitly stated as free/available.
   - "unknown" if you cannot determine the status with confidence.

[
    {
        "entity_id": "Listing URL",
        "status": "active",
        "payload": {
            "url": "Listing URL",
            "title": "string",
            "price": 150000,
            "address": "string (full address with city/area if available)",
            "listing_status": "available | in_negotiation | investment_occupied | sold | unknown",
            "specs": {
                "surface_m2": 97,
                "rooms": 3,
                "bedrooms": 2,
                "bathrooms": 1,
                "floor": "string",
                "elevator": true,
                "balcony_or_terrace": true,
                "garage_or_parking": true,
                "heating": "string"
            },
            "summary": "FULL property description - DO NOT truncate"
        }
    }
]
"""


def get_extractor_brain() -> CloudEvaluator:
    return CloudEvaluator(
        system_prompt=_EXTRACTION_SYSTEM_PROMPT,
        api_key=os.getenv("GEMINI_API_KEY"),
    )


# ─────────────────────────────────────────────────────────────────────
#  AI response parsing
# ─────────────────────────────────────────────────────────────────────

def parse_ai_entities(raw_text: str) -> list[dict]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:-3].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:-3].strip()

    parsed = json.loads(cleaned)
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    return []


# ─────────────────────────────────────────────────────────────────────
#  URL normalization
# ─────────────────────────────────────────────────────────────────────

def normalize_listing_url(url: str) -> str:
    """Normalize listing URL: strip query params, fragments, trailing slashes."""
    if not url:
        return url
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


# ─────────────────────────────────────────────────────────────────────
#  Geocoding enrichment
# ─────────────────────────────────────────────────────────────────────

def enrich_payload_geolocation(payload: dict, geocoder: GeocodingService) -> dict:
    """Add lat/lon to payload via Nominatim geocoding."""
    if not isinstance(payload, dict):
        return payload

    existing = (
        payload.get("location")
        if isinstance(payload.get("location"), dict)
        else {}
    )
    if existing.get("lat") is not None and existing.get("lon") is not None:
        return payload

    candidates = _build_geocoding_candidates(payload)
    for query in candidates:
        if not query or len(query) < 3:
            continue
        try:
            geo = geocoder.geocode(query)
            if geo and len(geo) >= 2:
                payload = dict(payload)
                payload["location"] = {
                    "lat": geo[0],
                    "lon": geo[1],
                    "source": "nominatim",
                    "query": query,
                }
                return payload
        except Exception:
            continue

    address = str(payload.get("address", "")).strip()
    title = str(payload.get("title", "")).strip()
    print(f"[GEO] No geolocation for '{address or title}'")
    return payload


def _build_geocoding_candidates(payload: dict) -> list[str]:
    candidates: list[str] = []
    address = str(payload.get("address", "")).strip()
    title = str(payload.get("title", "")).strip()

    if address:
        candidates.append(address)
    if title and title not in candidates:
        candidates.append(title)
    if title and "," in title:
        city_part = title.split(",")[-1].strip()
        if city_part and city_part not in candidates:
            candidates.append(city_part)

    expanded: list[str] = []
    for c in candidates:
        if not c:
            continue
        expanded.append(c)
        if "italia" not in c.lower() and "italy" not in c.lower():
            expanded.append(f"{c}, Italia")
    return expanded


# ─────────────────────────────────────────────────────────────────────
#  Listing enrichment  (Atlas fetch + site handler)
# ─────────────────────────────────────────────────────────────────────

_atlas: Optional[AtlasClient] = None
_site_registry: Optional[SiteHandlerRegistry] = None


def _get_atlas() -> AtlasClient:
    global _atlas
    if _atlas is None:
        _atlas = AtlasClient()
    return _atlas


def _get_site_registry() -> SiteHandlerRegistry:
    global _site_registry
    if _site_registry is None:
        _site_registry = SiteHandlerRegistry()
    return _site_registry


def enrich_payload_from_listing(payload: dict, timeout_seconds: int = 30) -> dict:
    """Fetch the listing page via Atlas and enrich using a site-specific handler."""
    if not isinstance(payload, dict):
        return payload

    url = str(payload.get("url", "")).strip()
    if not url:
        print("[ENRICH] Skipped: no URL in payload")
        return payload

    registry = _get_site_registry()
    handler = registry.get_handler(url)
    if handler is None:
        print(f"[ENRICH] No site handler for {url}, skipping page enrichment")
        return payload

    normalized_url = handler.normalize_url(url)
    enriched = dict(payload)
    enriched["url"] = normalized_url
    enriched["source_site"] = handler.site_name

    print(
        f"[ENRICH] Fetching {normalized_url} via Atlas ({handler.site_name})")
    result = _get_atlas().fetch_html(normalized_url, timeout_seconds=timeout_seconds)
    if result is None or not result.html:
        print(f"[ENRICH] No HTML from Atlas for {normalized_url}")
        return enriched

    print(
        f"[ENRICH] Got {result.content_length} chars, enriching via {handler.site_name}")
    soup = BeautifulSoup(result.html, "html.parser")
    return handler.enrich(soup, enriched)
