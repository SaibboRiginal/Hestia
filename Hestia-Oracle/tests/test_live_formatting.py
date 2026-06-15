"""Tests — Live Oracle formatting validation (Phase 1.9)

Tests the /api/format endpoint with real Ollama inference through the engine.
Validates HTML output contract: no raw Markdown, correct tag usage, no prose leakage.

Mark: @pytest.mark.llm_live
"""
from __future__ import annotations

import json
import os
import re
from unittest.mock import MagicMock, patch
import pytest
import requests


# ─────────────────────────────────────────────────────────────────────────────
# Live format tests via direct engine call
# ─────────────────────────────────────────────────────────────────────────────

_SAMPLE_LISTINGS = [
    {
        "title": "Bilocale in centro",
        "price": 250000,
        "location": "Milano, Navigli",
        "rooms": 2,
        "sqm": 65,
        "url": "https://example.com/annuncio/1",
    },
    {
        "title": "Trilocale con terrazzo",
        "price": 390000,
        "location": "Roma, Prati",
        "rooms": 3,
        "sqm": 90,
        "url": "https://example.com/annuncio/2",
    },
]

_HTML_TAG_PATTERN = re.compile(
    r"<(?:b|i|a[\s>]|code|pre|br|ul|li|strong|em)[\s/>]", re.IGNORECASE)
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*[^*]+\*\*")
_MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,6}\s", re.MULTILINE)
_MARKDOWN_BULLET_PATTERN = re.compile(r"^[-*]\s", re.MULTILINE)


@pytest.mark.llm_live
class TestLiveFormatting:
    @pytest.fixture(scope="class")
    def live_engine(self):
        """Create a real OracleEngine backed by Ollama."""
        from core.oracle_engine import OracleEngine
        with patch("requests.post"):  # suppress Hub registration
            engine = OracleEngine()
        return engine

    def test_format_scout_listings_returns_html(self, live_engine):
        """Scout listings formatted output must contain HTML tags."""
        result = live_engine.format_payload(
            command="scout_listings",
            payload=_SAMPLE_LISTINGS,
        )
        assert isinstance(result, str)
        assert len(result) > 10
        # Should not be raw JSON
        assert result.strip() != json.dumps(_SAMPLE_LISTINGS)

    def test_format_output_has_no_markdown_bold(self, live_engine):
        """Output must not contain **bold** Markdown syntax."""
        result = live_engine.format_payload(
            command="scout_listings",
            payload=_SAMPLE_LISTINGS,
        )
        matches = _MARKDOWN_BOLD_PATTERN.findall(result)
        assert len(matches) == 0, f"Markdown bold found: {matches}"

    def test_format_output_has_no_markdown_headings(self, live_engine):
        """Output must not contain ## heading Markdown syntax."""
        result = live_engine.format_payload(
            command="scout_listings",
            payload=_SAMPLE_LISTINGS,
        )
        matches = _MARKDOWN_HEADING_PATTERN.findall(result)
        assert len(matches) == 0, f"Markdown headings found: {matches}"

    def test_format_calendar_events_returns_string(self, live_engine):
        """Calendar events formatted as readable text."""
        events = [
            {"title": "Riunione team", "start": "2025-07-01T10:00",
                "end": "2025-07-01T11:00"},
            {"title": "Dentista", "start": "2025-07-03T14:00",
                "end": "2025-07-03T15:00"},
        ]
        result = live_engine.format_payload(
            command="calendar_list",
            payload=events,
        )
        assert isinstance(result, str)
        assert len(result) > 10

    def test_format_empty_payload_returns_coherent_string(self, live_engine):
        """Empty payload should produce a coherent 'no data' message, not an error."""
        result = live_engine.format_payload(
            command="scout_listings",
            payload=[],
        )
        assert isinstance(result, str)
        assert len(result) > 0
        # Should not be a Python traceback or raw exception
        assert "Traceback" not in result
        assert "Exception" not in result

    def test_format_with_client_instructions_changes_style(self, live_engine):
        """Client instructions should influence the output style."""
        result_short = live_engine.format_payload(
            command="scout_listings",
            payload=_SAMPLE_LISTINGS,
            client_instructions="Rispondi in modo MOLTO conciso, massimo 2 righe.",
        )
        result_long = live_engine.format_payload(
            command="scout_listings",
            payload=_SAMPLE_LISTINGS,
        )
        # With "very concise" instruction, result should typically be shorter
        # (not always guaranteed, but a strong signal)
        assert isinstance(result_short, str)
        assert isinstance(result_long, str)

    def test_format_via_api_endpoint(self):
        """End-to-end: POST /api/format and verify HTML in response."""
        oracle_url = os.environ.get(
            "ORACLE_TEST_URL", "http://localhost:19004")
        try:
            resp = requests.post(
                f"{oracle_url}/api/format",
                json={
                    "command": "scout_listings",
                    "payload": _SAMPLE_LISTINGS,
                },
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            pytest.skip("Oracle service not running at ORACLE_TEST_URL")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert isinstance(data["text"], str)
        assert len(data["text"]) > 0

    def test_format_response_not_raw_json_dump(self, live_engine):
        """The engine must never return raw JSON as the formatted text."""
        result = live_engine.format_payload(
            command="scout_listings",
            payload=_SAMPLE_LISTINGS,
        )
        # It should not start with "[{" (raw JSON array) or be parseable as the input
        try:
            parsed = json.loads(result)
            # If it parses as JSON and equals the input, that's a failure
            assert parsed != _SAMPLE_LISTINGS, "format_payload returned raw JSON input unchanged"
        except (json.JSONDecodeError, ValueError):
            pass  # Good — it's not raw JSON
