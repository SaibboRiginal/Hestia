"""Tests — chat_classifier module (Phase 1.3)

Tests for ChatClassifier.classify() and internal helpers.
All mocked — no network, no LLM.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from core.services.chat_classifier import ChatClassifier, QUICK_CHAT_CONFIDENCE_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_classifier(router_response: str, fallback_response: str | None = None) -> ChatClassifier:
    router = MagicMock()
    router.ask.return_value = router_response
    fallback = MagicMock()
    fallback.ask.return_value = fallback_response or router_response
    return ChatClassifier(router, fallback)


def _quick_chat_json(confidence: float = 0.9, action_intent: bool = False) -> str:
    return json.dumps(
        {
            "mode": "quick_chat",
            "domain": None,
            "confidence": confidence,
            "domains": ["general"],
            "filters": {},
            "filters_gt": {},
            "filters_lt": {},
            "sort_by": None,
            "sort_order": "desc",
            "action_intent": action_intent,
        }
    )


def _domain_query_json(
    domain: str = "scout",
    domains: list[str] | None = None,
    filters: dict | None = None,
    filters_gt: dict | None = None,
    filters_lt: dict | None = None,
    sort_by: str | None = None,
    sort_order: str = "desc",
    confidence: float = 0.85,
    action_intent: bool = False,
) -> str:
    return json.dumps(
        {
            "mode": "domain_query",
            "domain": domain,
            "confidence": confidence,
            "domains": domains or [domain],
            "filters": filters or {},
            "filters_gt": filters_gt or {},
            "filters_lt": filters_lt or {},
            "sort_by": sort_by,
            "sort_order": sort_order,
            "action_intent": action_intent,
        }
    )


SAMPLE_DOMAINS = ["scout", "chronos", "archive", "general"]

# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestChatClassifier:
    def test_quick_chat_classification(self):
        clf = _make_classifier(_quick_chat_json(0.95))
        mode, domain, confidence, valid_domains, *_ = clf.classify(
            "Ciao come stai?", "", SAMPLE_DOMAINS
        )
        assert mode == "quick_chat"
        assert confidence == pytest.approx(0.95, abs=0.01)

    def test_domain_query_classification_with_domain(self):
        clf = _make_classifier(_domain_query_json("scout", confidence=0.88))
        mode, domain, confidence, valid_domains, *_ = clf.classify(
            "Mostrami appartamenti a Milano", "", SAMPLE_DOMAINS
        )
        assert mode == "domain_query"
        assert domain == "scout"
        assert "scout" in valid_domains

    def test_invalid_mode_falls_back_to_domain_query(self):
        bad = json.dumps(
            {"mode": "unknown_mode", "confidence": 0.9, "domains": ["general"]})
        clf = _make_classifier(bad)
        mode, *_ = clf.classify("Qualcosa", "", SAMPLE_DOMAINS)
        assert mode == "domain_query"

    def test_domain_not_in_available_domains_is_nulled(self):
        resp = _domain_query_json("nonexistent_domain")
        clf = _make_classifier(resp)
        _, domain, *_ = clf.classify("Cercami qualcosa", "", SAMPLE_DOMAINS)
        assert domain is None

    def test_filters_parsed_correctly(self):
        resp = _domain_query_json(
            "scout",
            filters={"city": "Roma"},
            filters_gt={"price": 100000},
            filters_lt={"price": 500000},
        )
        clf = _make_classifier(resp)
        _, _, _, _, filters, filters_gt, filters_lt, *_ = clf.classify(
            "Appartamenti a Roma tra 100k e 500k", "", SAMPLE_DOMAINS
        )
        assert filters.get("city") == "Roma"
        assert filters_gt.get("price") == 100000
        assert filters_lt.get("price") == 500000

    def test_sort_by_and_sort_order_parsed(self):
        resp = _domain_query_json("scout", sort_by="price", sort_order="asc")
        clf = _make_classifier(resp)
        result = clf.classify(
            "Annunci per prezzo crescente", "", SAMPLE_DOMAINS
        )
        sort_by = result[7]
        sort_order = result[8]
        assert sort_by == "price"
        assert sort_order == "asc"

    def test_primary_router_fails_uses_fallback(self):
        router = MagicMock()
        router.ask.side_effect = RuntimeError("LLM down")
        fallback = MagicMock()
        fallback.ask.return_value = _quick_chat_json(0.9)
        clf = ChatClassifier(router, fallback)
        mode, *_ = clf.classify("Ciao", "", SAMPLE_DOMAINS)
        assert mode == "quick_chat"
        fallback.ask.assert_called_once()

    def test_both_routers_fail_returns_defaults(self):
        router = MagicMock()
        router.ask.side_effect = RuntimeError("LLM down")
        fallback = MagicMock()
        fallback.ask.side_effect = RuntimeError("Fallback down")
        clf = ChatClassifier(router, fallback)
        mode, domain, confidence, valid_domains, * \
            _ = clf.classify("Ciao", "", SAMPLE_DOMAINS)
        # defaults: domain_query, None, 0.0, ['general']
        assert mode == "domain_query"
        assert confidence == 0.0

    def test_malformed_json_returns_defaults(self):
        clf = _make_classifier("this is not json at all")
        mode, domain, confidence, * \
            _ = clf.classify("Qualcosa", "", SAMPLE_DOMAINS)
        assert mode == "domain_query"
        assert confidence == 0.0

    def test_confidence_clamped_between_zero_and_one(self):
        resp = json.dumps(
            {"mode": "quick_chat", "confidence": 5.0, "domains": ["general"]})
        clf = _make_classifier(resp)
        _, _, confidence, *_ = clf.classify("Ciao", "", SAMPLE_DOMAINS)
        assert 0.0 <= confidence <= 1.0

    def test_valid_domains_includes_general_as_fallback(self):
        resp = json.dumps(
            {"mode": "domain_query", "confidence": 0.8, "domains": []})
        clf = _make_classifier(resp)
        _, _, _, valid_domains, *_ = clf.classify("Test", "", SAMPLE_DOMAINS)
        assert "general" in valid_domains

    def test_quick_chat_confidence_threshold_is_float(self):
        assert isinstance(QUICK_CHAT_CONFIDENCE_THRESHOLD, float)
        assert 0.0 < QUICK_CHAT_CONFIDENCE_THRESHOLD <= 1.0

    def test_json_wrapped_in_prose_still_parsed(self):
        # LLMs sometimes wrap JSON in natural language
        inner = {"mode": "quick_chat",
                 "confidence": 0.8, "domains": ["general"]}
        resp = f"Here is my classification: {json.dumps(inner)} That's my answer."
        clf = _make_classifier(resp)
        mode, *_ = clf.classify("Ciao", "", SAMPLE_DOMAINS)
        assert mode == "quick_chat"

    def test_current_datetime_context_is_included_in_router_prompt(self):
        router = MagicMock()
        router.ask.return_value = _quick_chat_json(0.8)
        fallback = MagicMock()
        fallback.ask.return_value = _quick_chat_json(0.8)
        clf = ChatClassifier(router, fallback)

        clf.classify(
            "Cosa ho domani?",
            "",
            SAMPLE_DOMAINS,
            current_datetime_context="timezone=Europe/Rome\nnow_iso=2026-06-02T21:00:00+02:00",
        )

        assert router.ask.called
        sent_prompt = str(router.ask.call_args[0][0])
        assert "CURRENT_DATETIME_CONTEXT" in sent_prompt
        assert "2026-06-02T21:00:00+02:00" in sent_prompt

    def test_action_intent_true_when_user_requests_action(self):
        """action_intent should be True for imperative action requests."""
        resp = _domain_query_json("scout", action_intent=True)
        clf = _make_classifier(resp)
        result = clf.classify("Elimina tutti gli annunci vecchi", "", SAMPLE_DOMAINS)
        action_intent = result[9]  # 10th return value
        assert action_intent is True

    def test_action_intent_false_for_informational_query(self):
        """action_intent should be False for informational queries."""
        resp = _quick_chat_json(action_intent=False)
        clf = _make_classifier(resp)
        result = clf.classify("Ciao come stai?", "", SAMPLE_DOMAINS)
        action_intent = result[9]
        assert action_intent is False

    def test_action_intent_defaults_to_false(self):
        """When action_intent is missing from JSON, default to False."""
        resp = json.dumps({
            "mode": "domain_query", "confidence": 0.8, "domains": ["general"]
        })
        clf = _make_classifier(resp)
        result = clf.classify("Qualcosa", "", SAMPLE_DOMAINS)
        action_intent = result[9]
        assert action_intent is False
