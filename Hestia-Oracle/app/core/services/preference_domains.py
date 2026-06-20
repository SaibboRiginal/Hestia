"""Preference domain classifier — embedding-based, no LLM.

Fixed domain categories (Rulebook 1.4: configurable via env var).
Preferences are assigned 0→N domains via embedding cosine similarity
against domain descriptions at creation time.  No dynamic domain creation.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Callable

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── Domain definitions ──────────────────────────────────────────────────────
# Format: JSON object  { "domain_key": "description for embedding matching" }
# Set ORACLE_PREFERENCE_DOMAINS to override.
_DEFAULT_DOMAINS: dict[str, str] = {
    "general": "Universal preferences, default catch-all for anything not fitting other domains",
    "calendar": "Scheduling, time management, appointments, events, deadlines, agenda, reminders",
    "real_estate": "Housing, property, apartments, listings, buying, selling, renting homes, real estate market",
    "email": "Messages, communication, inbox, correspondence, mail, letters, notifications",
    "system": "Technology, services, monitoring, software, hardware, tech infrastructure, servers",
    "food": "Cuisine, restaurants, dietary preferences, cooking, eating, food, meals, recipes",
    "work": "Professional life, projects, career, workplace, business, job, office, employment",
    "health": "Medical, fitness, wellness, exercise, healthcare, doctor, gym, nutrition",
    "travel": "Trips, transportation, locations, navigation, commuting, vacations, flights, hotels",
    "finance": "Money, budgeting, purchases, banking, investments, savings, expenses, payments",
}

# Similarity threshold: preference assigned to domain if cosine sim > this.
_SIMILARITY_THRESHOLD: float = float(
    os.getenv("ORACLE_PREF_DOMAIN_SIM_THRESHOLD", "0.55"))


def _parse_domains() -> dict[str, str]:
    raw = os.getenv("ORACLE_PREFERENCE_DOMAINS", "")
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            logger.warning(
                "event=pref_domains_parse_failed "
                "ORACLE_PREFERENCE_DOMAINS is not valid JSON; using defaults")
    return dict(_DEFAULT_DOMAINS)


PREFERENCE_DOMAINS: dict[str, str] = _parse_domains()
DOMAIN_KEYS: list[str] = sorted(PREFERENCE_DOMAINS.keys())
SIMILARITY_THRESHOLD: float = _SIMILARITY_THRESHOLD


# ── Cosine similarity (pure Python, no numpy dependency) ────────────────────

def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> float:
    return sum(x * x for x in v) ** 0.5


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


# ── Domain classifier ───────────────────────────────────────────────────────

class PreferenceDomainClassifier:
    """Assign preferences to fixed domains via embedding similarity.

    Domain description embeddings are pre-computed once on construction.
    Preference embeddings are computed at classification time via *embed_fn*.
    """

    def __init__(self, embed_fn: Callable[[str], list[float]]) -> None:
        self._embed = embed_fn
        self._domain_embeddings: dict[str, list[float]] = {}
        self._warm()

    def _warm(self) -> None:
        """Pre-compute domain description embeddings."""
        for key in DOMAIN_KEYS:
            desc = PREFERENCE_DOMAINS.get(key, key)
            try:
                vec = self._embed(desc)
                self._domain_embeddings[key] = vec
                logger.debug(
                    "event=pref_domain_embedding_cached domain=%s dims=%d",
                    key, len(vec),
                )
            except Exception as exc:
                logger.warning(
                    "event=pref_domain_embedding_failed domain=%s error=%s",
                    key, exc,
                )
                # Use zero vector as fallback — domain won't match anything
                self._domain_embeddings[key] = []

    def classify(self, text: str) -> list[str]:
        """Return 0→N domain keys matching *text* via embedding similarity."""
        clean = str(text or "").strip()
        if not clean:
            return ["general"]

        try:
            vec = self._embed(clean)
        except Exception as exc:
            logger.warning(
                "event=pref_embedding_failed text_preview=%s error=%s — defaulting to general",
                clean[:100], exc,
            )
            return ["general"]

        if not vec:
            return ["general"]

        matches: list[str] = []
        for key in DOMAIN_KEYS:
            dom_vec = self._domain_embeddings.get(key, [])
            sim = cosine_similarity(vec, dom_vec)
            if sim >= SIMILARITY_THRESHOLD:
                matches.append(key)
                logger.trace(
                    "event=pref_domain_match text_preview=%s domain=%s sim=%.3f",
                    clean[:80], key, sim,
                )

        # "general" is always included — universal preferences
        if "general" not in matches:
            matches.insert(0, "general")

        logger.debug(
            "event=pref_domains_assigned text_preview=%s domains=%s",
            clean[:120], matches,
        )
        return matches
