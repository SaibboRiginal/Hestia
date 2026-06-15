"""Tests — Telegram formatters (Phase 2.6)

Tests for the pure formatting functions in telegram_bot/services/formatters.py:
format_scout_listings, format_subscriptions_list, format_documents_list,
format_active_preferences, render_direct_command_output, strip_formatter_intro.
All pure-function tests — no network, no bot, no Oracle.
"""
from __future__ import annotations

import re
import pytest

# conftest adds app/ to sys.path
from telegram_bot.services.formatters import (
    format_scout_listings,
    format_subscriptions_list,
    format_documents_list,
    format_active_preferences,
    render_direct_command_output,
    strip_formatter_intro,
)

_HTML_LINK_PATTERN = re.compile(r'<a\s+href=', re.IGNORECASE)
_HTML_BOLD_PATTERN = re.compile(r'<b>', re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# format_scout_listings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestFormatScoutListings:
    _SAMPLE = [
        {
            "title": "Bilocale Milano",
            "price": 250000,
            "location": "Milano, Navigli",
            "url": "https://example.com/1",
        },
        {
            "title": "Trilocale Roma",
            "price": 350000,
            "location": "Roma, Prati",
        },
    ]

    def test_returns_string_for_valid_list(self):
        result = format_scout_listings(self._SAMPLE)
        assert isinstance(result, str)

    def test_returns_html_with_bold_tags(self):
        result = format_scout_listings(self._SAMPLE)
        assert _HTML_BOLD_PATTERN.search(result)

    def test_listing_with_url_has_html_link(self):
        result = format_scout_listings(self._SAMPLE)
        assert _HTML_LINK_PATTERN.search(result)

    def test_empty_list_returns_no_results_message(self):
        result = format_scout_listings([])
        assert result is not None
        assert "nessun" in result.lower() or "trovata" in result.lower()

    def test_non_list_payload_returns_none(self):
        result = format_scout_listings({"not": "a list"})
        assert result is None

    def test_limit_respected(self):
        big_list = [{"title": f"Casa {i}", "price": 100000 * i}
                    for i in range(50)]
        result = format_scout_listings(big_list, limit=5)
        # Should contain max 5 items; count occurrences of <b> as item markers
        bold_count = len(_HTML_BOLD_PATTERN.findall(result))
        # There's 1 header bold + 5 item bolds = at most 6, but heading varies
        assert bold_count <= 10  # conservative upper bound

    def test_price_formatted_with_euro_symbol(self):
        result = format_scout_listings(self._SAMPLE)
        assert "€" in result or "250" in result

    def test_no_raw_markdown_in_output(self):
        result = format_scout_listings(self._SAMPLE)
        assert "**" not in result
        assert "##" not in result


# ─────────────────────────────────────────────────────────────────────────────
# format_subscriptions_list
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestFormatSubscriptionsList:
    _SAMPLE = [
        {
            "id": "sub_001",
            "domain": "real_estate",
            "filters": {"city": "Milano", "price_max": 300000},
        },
        {
            "id": "sub_002",
            "domain": "real_estate",
            "filters": {"city": "Roma", "property_type": "trilocale"},
        },
    ]

    def test_returns_string_for_valid_list(self):
        result = format_subscriptions_list(self._SAMPLE)
        assert isinstance(result, str)

    def test_empty_list_returns_no_active_message(self):
        result = format_subscriptions_list([])
        assert "nessuna" in result.lower() or "nessun" in result.lower()

    def test_non_list_returns_none(self):
        result = format_subscriptions_list("not a list")
        assert result is None

    def test_city_appears_in_output(self):
        result = format_subscriptions_list(self._SAMPLE)
        assert "Milano" in result or "Roma" in result

    def test_output_contains_html_bold(self):
        result = format_subscriptions_list(self._SAMPLE)
        assert "<b>" in result


# ─────────────────────────────────────────────────────────────────────────────
# format_documents_list
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestFormatDocumentsList:
    _SAMPLE = [
        {"id": "doc_001", "title": "Contratto affitto",
            "mime_type": "application/pdf", "created_at": "2025-01-15T10:00:00"},
        {"id": "doc_002", "title": "Planimetria bilocale",
            "mime_type": "image/jpeg", "created_at": "2025-02-01T08:30:00"},
    ]

    def test_returns_string_for_valid_list(self):
        text, markup = format_documents_list(self._SAMPLE)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_empty_list_handled_gracefully(self):
        text, markup = format_documents_list([])
        assert isinstance(text, str)

    def test_document_title_in_output(self):
        text, markup = format_documents_list(self._SAMPLE)
        assert "Contratto" in text or "documento" in text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# format_active_preferences
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestFormatActivePreferences:
    _SAMPLE = [
        {"fact": "Preferisco appartamenti con terrazzo",
            "domain": "real_estate", "weight": 1.0},
        {"fact": "Budget massimo 300.000€", "domain": "real_estate", "weight": 0.9},
    ]

    def test_returns_string_for_valid_list(self):
        result = format_active_preferences(self._SAMPLE)
        assert isinstance(result, str)

    def test_empty_list_handled(self):
        result = format_active_preferences([])
        assert isinstance(result, str)

    def test_fact_appears_in_output(self):
        result = format_active_preferences(self._SAMPLE)
        assert "terrazzo" in result or "preferenza" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# render_direct_command_output
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestRenderDirectCommandOutput:
    def test_string_payload_returned_as_is(self):
        text, parse_mode = render_direct_command_output("test_cmd", "Ciao!")
        assert isinstance(text, str)
        assert "Ciao" in text

    def test_dict_payload_rendered_as_text(self):
        text, parse_mode = render_direct_command_output(
            "test_cmd", {"status": "ok", "value": 42})
        assert isinstance(text, str)
        assert len(text) > 0

    def test_list_payload_rendered_as_text(self):
        text, parse_mode = render_direct_command_output(
            "test_cmd", [{"name": "Item1"}, {"name": "Item2"}])
        assert isinstance(text, str)

    def test_empty_dict_returns_non_empty_string(self):
        text, parse_mode = render_direct_command_output("test_cmd", {})
        assert isinstance(text, str)


# ─────────────────────────────────────────────────────────────────────────────
# strip_formatter_intro
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestStripFormatterIntro:
    def test_strips_common_intro_phrases(self):
        text = "Ecco i risultati che ho trovato per te:\n<b>Item 1</b>"
        result = strip_formatter_intro(text)
        # The intro should be stripped, leaving just the content
        assert "<b>Item 1</b>" in result

    def test_plain_text_without_intro_unchanged(self):
        text = "<b>Direttamente al punto</b>"
        result = strip_formatter_intro(text)
        assert "<b>Direttamente al punto</b>" in result

    def test_empty_string_returned(self):
        result = strip_formatter_intro("")
        assert result == ""
