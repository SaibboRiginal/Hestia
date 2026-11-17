"""Standardized listing status enum and keyword-based detection.

Status values are source-agnostic and intentionally minimal to cover
what can be reasonably inferred from real estate emails across multiple
Italian listing platforms.
"""

from __future__ import annotations

import re

from hestia_common.i18n import words
from enum import Enum


class ListingStatus(str, Enum):
    """Availability status of a real estate listing.

    ``unknown`` is the safe default when the status cannot be determined
    with confidence from the available text.
    """
    AVAILABLE = "available"
    IN_NEGOTIATION = "in_negotiation"
    INVESTMENT_OCCUPIED = "investment_occupied"
    SOLD = "sold"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────
#  Keyword signal tables  (ordered by specificity — most specific first)
# ─────────────────────────────────────────────────────────────────────

# Patterns of every language: scout.status.<kind> in locales/<lang>/words.json (regex fragments).
_PATTERN_KEYS = {"sold": "scout.status.sold", "negotiation": "scout.status.negotiation",
                 "occupied": "scout.status.occupied", "available": "scout.status.available"}
_SOLD_PATTERNS: list[str] = list(words(_PATTERN_KEYS["sold"]))
_NEGOTIATION_PATTERNS: list[str] = list(words(_PATTERN_KEYS["negotiation"]))
_INVESTMENT_PATTERNS: list[str] = list(words(_PATTERN_KEYS["occupied"]))
_AVAILABLE_PATTERNS: list[str] = list(words(_PATTERN_KEYS["available"]))

# Compile all patterns once at module load
_COMPILED: dict[ListingStatus, list[re.Pattern]] = {
    ListingStatus.SOLD: [re.compile(p, re.IGNORECASE) for p in _SOLD_PATTERNS],
    ListingStatus.IN_NEGOTIATION: [re.compile(p, re.IGNORECASE) for p in _NEGOTIATION_PATTERNS],
    ListingStatus.INVESTMENT_OCCUPIED: [re.compile(p, re.IGNORECASE) for p in _INVESTMENT_PATTERNS],
    ListingStatus.AVAILABLE: [re.compile(p, re.IGNORECASE) for p in _AVAILABLE_PATTERNS],
}

# Detection priority: sold > in_negotiation > investment_occupied > available
_DETECTION_ORDER: list[ListingStatus] = [
    ListingStatus.SOLD,
    ListingStatus.IN_NEGOTIATION,
    ListingStatus.INVESTMENT_OCCUPIED,
    ListingStatus.AVAILABLE,
]


def detect_listing_status(text: str) -> ListingStatus:
    """Detect listing availability from plain email or page text.

    Returns ``ListingStatus.UNKNOWN`` when no signal is found — callers
    must treat ``unknown`` as "no change" for existing entities, and as
    a valid default field value for new entities.
    """
    if not text or not text.strip():
        return ListingStatus.UNKNOWN

    for status in _DETECTION_ORDER:
        for pattern in _COMPILED[status]:
            if pattern.search(text):
                return status

    return ListingStatus.UNKNOWN


def coerce_listing_status(raw: str | None) -> ListingStatus:
    """Safely coerce an LLM-produced string to a ``ListingStatus`` value.

    Falls back to ``UNKNOWN`` for unrecognised strings so that a model
    hallucination never raises an exception.
    """
    if not raw:
        return ListingStatus.UNKNOWN
    normalized = str(raw).strip().lower()
    for member in ListingStatus:
        if member.value == normalized:
            return member
    return ListingStatus.UNKNOWN
