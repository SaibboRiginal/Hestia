"""Short stable key of a listing (entity ids are URLs): used in the WebUI plugin paths and notification links."""
from __future__ import annotations

import hashlib


def listing_key(entity_id: str) -> str:
    return hashlib.sha1(str(entity_id or "").strip().encode("utf-8")).hexdigest()[:12]
