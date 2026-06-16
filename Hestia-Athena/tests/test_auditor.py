"""Tests for ConversationAuditor — unit tests with mocked HTTP.

Markers: unit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_APP_ROOT = Path(__file__).parents[1] / "app"
_REPO_ROOT = Path(__file__).parents[2]
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_APP_ROOT), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.auditor import ConversationAuditor, _JUDGE_PROMPT


@pytest.mark.unit
class TestConversationAuditor:
    """Unit tests — all outbound HTTP mocked."""

    @pytest.fixture
    def auditor(self):
        return ConversationAuditor("http://hub:19001/api")

    @pytest.fixture
    def mock_history(self):
        return [
            {"role": "user", "content": "Ciao"},
            {"role": "assistant", "content": "Ciao. Dimmi."},
            {"role": "user", "content": "Cerco case a Milano"},
            {"role": "assistant", "content": "Trovato un trilocale a 280k."},
        ]

    @pytest.fixture
    def mock_scores_response(self):
        return json.dumps([
            {"turn": 1, "style": 5, "accuracy": 5, "usefulness": 5,
             "overall": "excellent", "notes": "Conciso e diretto"},
            {"turn": 3, "style": 4, "accuracy": 5, "usefulness": 4,
             "overall": "good", "notes": "Corretto ma leggermente verboso"},
        ])

    def test_audit_session_no_history(self, auditor):
        """Returns no_history when Archive has no chat data."""
        with patch.object(auditor, "_fetch_chat_history", return_value=[]):
            result = auditor.audit_session("test_session", limit=5)
        assert result["status"] == "no_history"
        assert result["turns_scored"] == 0

    def test_audit_session_scores_and_submits(
        self, auditor, mock_history, mock_scores_response
    ):
        """Full flow: fetch history → score → submit."""
        with patch.object(
            auditor, "_fetch_chat_history", return_value=mock_history
        ):
            with patch.object(
                auditor, "_call_oracle_llm", return_value=mock_scores_response
            ):
                with patch.object(
                    auditor, "_submit_score", return_value=True
                ):
                    result = auditor.audit_session("test_session", limit=5)

        assert result["status"] == "ok"
        assert result["turns_scored"] == 2
        assert result["submitted"] == 2
        assert result["scores"][0]["style"] == 5
        assert result["scores"][0]["overall"] == "excellent"

    def test_audit_session_oracle_fails(self, auditor, mock_history):
        """Graceful handling when Oracle LLM is unreachable."""
        with patch.object(
            auditor, "_fetch_chat_history", return_value=mock_history
        ):
            with patch.object(
                auditor, "_call_oracle_llm", return_value=None
            ):
                result = auditor.audit_session("test_session", limit=5)

        assert result["turns_scored"] == 0

    def test_parse_scores_extracts_json_array(self, auditor, mock_history):
        """JSON extraction from LLM response with surrounding text."""
        raw = 'Ecco i risultati:\n[{"turn": 0, "style": 4, "accuracy": 5, "usefulness": 5, "overall": "good", "notes": "ok"}]\nFatto.'
        scores = auditor._parse_scores(
            raw,
            [(0, {"role": "assistant", "content": "test"})],
        )
        assert len(scores) == 1
        assert scores[0]["style"] == 4
        assert scores[0]["overall"] == "good"

    def test_parse_scores_handles_malformed(self, auditor, mock_history):
        """Malformed LLM output returns empty list."""
        scores = auditor._parse_scores(
            "Non ho capito, riproviamo...",
            [(0, {"role": "assistant", "content": "test"})],
        )
        assert scores == []

    def test_judge_prompt_contains_key_elements(self):
        """Judge prompt should include scoring dimensions and format."""
        assert "stile" in _JUDGE_PROMPT
        assert "accuratezza" in _JUDGE_PROMPT
        assert "utilita" in _JUDGE_PROMPT
        assert "CONVERSAZIONE DA VALUTARE" in _JUDGE_PROMPT
        assert "{conversation_text}" in _JUDGE_PROMPT

    def test_submit_score_calls_archive(self, auditor):
        """_submit_score should POST to Archive's feedback endpoint."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_session.post.return_value = mock_resp
        auditor._session = mock_session

        ok = auditor._submit_score(
            "test_session",
            {"style": 5, "accuracy": 5, "usefulness": 5,
             "overall": "excellent", "notes": "perfetto"},
        )
        assert ok is True
        # Verify it called the right URL
        call_url = mock_session.post.call_args[0][0]
        assert "/route/archive/api/feedback" in call_url
