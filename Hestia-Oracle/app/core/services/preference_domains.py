"""Preference domain classifier — embedding-based, no LLM.

Domain categories: setting ``oracle.memory.preference_domains`` (Impostazioni → Oracle → Memoria).
Preferences are assigned 0→N domains via embedding cosine similarity
against domain descriptions at creation time.  No dynamic domain creation.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── Domain definitions ──────────────────────────────────────────────────────
# { "domain_key": "description for embedding matching" } — default declared with the setting.

# Domains (name → description) and the similarity threshold are central settings
# (oracle.memory.preference_domains / oracle.memory.domain_threshold), read at use time.


def _settings():
    from core.services import oracle_settings  # lazy: settings import the provider registry
    return oracle_settings


def _parse_domains() -> dict[str, str]:
    """Current preference domains (setting; default = ``oracle_settings.DEFAULT_PREFERENCE_DOMAINS``)."""
    return _settings().preference_domains()


def similarity_threshold() -> float:
    return _settings().get_float(_settings().DOMAIN_THRESHOLD)


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
        self._warmed_for: dict[str, str] = {}
        self._warm()

    def _warm(self) -> None:
        """Pre-compute domain description embeddings (again when the domains setting changes)."""
        domains = _parse_domains()
        if domains == self._warmed_for:
            return
        self._domain_embeddings = {}
        self._warmed_for = dict(domains)
        for key in sorted(domains):
            desc = domains.get(key, key)
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

        self._warm()
        threshold = similarity_threshold()
        matches: list[str] = []
        for key in sorted(self._domain_embeddings):
            dom_vec = self._domain_embeddings.get(key, [])
            sim = cosine_similarity(vec, dom_vec)
            if sim >= threshold:
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
