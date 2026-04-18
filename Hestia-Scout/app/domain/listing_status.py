"""Standardized listing status enum and keyword-based detection.

Status values are source-agnostic and intentionally minimal to cover
what can be reasonably inferred from real estate emails across multiple
Italian listing platforms.
"""

from __future__ import annotations

import re
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

_SOLD_PATTERNS: list[str] = [
    r"\bvendita\s+conclusa\b",
    r"\bgià\s+venduto\b",
    r"\bimmobile\s+venduto\b",
    r"\bvenduto\b",
    r"\bsold\b",
]

_NEGOTIATION_PATTERNS: list[str] = [
    r"\btrattativa\s+in\s+corso\b",
    r"\bin\s+trattativa\b",
    r"\btrattativa\s+riservata\b",
    r"\btrattativa\b",
    r"\bunder\s+offer\b",
    r"\bunder\s+negotiation\b",
]

_INVESTMENT_PATTERNS: list[str] = [
    r"\bgià\s+affittato\b",
    r"\baffittato\b",
    r"\bimmobile\s+occupato\b",
    r"\boccupato\s+da\s+inquilino\b",
    r"\binquilino\s+presente\b",
    r"\bvendita\s+con\s+inquilino\b",
    r"\binvestimento\s+immobiliare\b",
    r"\btenant\s+occupied\b",
]

_AVAILABLE_PATTERNS: list[str] = [
    r"\bdisponibile\s+subito\b",
    r"\blibero\s+subito\b",
    r"\bimmediately\s+available\b",
]

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
