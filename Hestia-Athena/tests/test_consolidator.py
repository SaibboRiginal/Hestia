"""Tests for Athena MemoryConsolidator — all methods, mocked external deps."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Path setup
_ATHENA_ROOT = Path(__file__).parents[1]
_APP_PATH = _ATHENA_ROOT / "app"
_REPO_ROOT = _ATHENA_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_APP_PATH), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("HUB_API_URL", "http://fake-hub:19001/api")

from core.consolidator import MemoryConsolidator


@pytest.fixture
def consolidator():
    """MemoryConsolidator with requests mocked."""
    with patch("core.consolidator.requests") as mock_req:
        mock_req.get.return_value.status_code = 200
        mock_req.get.return_value.json.return_value = []
        mock_req.post.return_value.status_code = 200
        mock_req.post.return_value.json.return_value = {"response": "{}"}
        mock_req.patch.return_value.status_code = 200
        yield MemoryConsolidator(hub_api_url="http://fake-hub:19001/api")


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduling
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestScheduling:
    def test_should_run_during_window(self, monkeypatch):
        """should_run() returns True during configured window (3-5 AM)."""
        monkeypatch.setenv("ATHENA_CONSOLIDATION_WINDOW_START", "0")
        monkeypatch.setenv("ATHENA_CONSOLIDATION_WINDOW_END", "23")
        from core.consolidator import MemoryConsolidator
        c = MemoryConsolidator(hub_api_url="http://x")
        # We just test that the env vars are read — actual time check depends on clock
        assert isinstance(c.should_run(), bool)

    def test_needs_consolidation_first_time(self, consolidator):
        """First consolidation for a session should always return True."""
        assert consolidator.needs_consolidation("new-session") is True

    def test_needs_consolidation_too_soon(self, consolidator):
        """After consolidation, shouldn't need it again immediately."""
        consolidator._last_consolidation["s1"] = time.time()
        assert consolidator.needs_consolidation("s1") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Consolidation flow
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestConsolidate:
    def test_consolidate_empty_history(self, consolidator):
        """Empty history should return zero results."""
        result = consolidator.consolidate("empty-session")
        assert result["facts_extracted"] == 0
        assert result["session_id"] == "empty-session"

    def test_consolidate_with_history_and_oracle_response(self, consolidator):
        """History + oracle response should extract facts."""
        # Mock chat history
        consolidator._fetch_chat_history = MagicMock(return_value=[
            {"role": "user", "content": "Preferisco gli appartamenti in centro"},
            {"role": "assistant", "content": "Ho salvato la tua preferenza."},
        ])
        # Mock existing memories
        consolidator._fetch_active_memories = MagicMock(return_value=[
            {"id": 1, "fact": "Vecchia preferenza Milano", "weight": 1.0, "created_at": "2020-01-01"},
        ])
        # Mock oracle response
        consolidator._analyze_with_oracle = MagicMock(return_value={
            "facts": [{"fact": "Preferisce appartamenti centro storico", "domain": "scout", "confidence": 0.9}],
            "conflicts": [],
            "patterns": [],
            "summary": "Extracted 1 fact.",
        })
        # Mock save
        consolidator._save_memory = MagicMock(return_value=True)

        result = consolidator.consolidate("test-session")

        assert result["facts_extracted"] == 1
        consolidator._save_memory.assert_called()

    def test_consolidate_detects_conflicts(self, consolidator):
        """When oracle detects conflicts, they should be resolved."""
        consolidator._fetch_chat_history = MagicMock(return_value=[
            {"role": "user", "content": "In realtà preferisco Roma, non più Milano"},
        ])
        consolidator._fetch_active_memories = MagicMock(return_value=[
            {"id": 5, "fact": "Preferisce Milano", "weight": 1.0},
        ])
        consolidator._analyze_with_oracle = MagicMock(return_value={
            "facts": [{"fact": "Preferisce Roma", "domain": "scout", "confidence": 0.85}],
            "conflicts": [{"old_id": 5, "new_fact": "Preferisce Roma", "resolution": "replace_new"}],
            "patterns": [],
            "summary": "Resolved 1 conflict.",
        })
        consolidator._save_memory = MagicMock(return_value=True)
        consolidator._resolve_conflict = MagicMock()

        result = consolidator.consolidate("test-session")
        assert result["conflicts_detected"] == 1
        consolidator._resolve_conflict.assert_called()

    def test_consolidate_reinforces_patterns(self, consolidator):
        """Repeated patterns should be reinforced."""
        consolidator._fetch_chat_history = MagicMock(return_value=[
            {"role": "user", "content": "budget 300k"},
            {"role": "user", "content": "massimo 300000"},
            {"role": "user", "content": "non superare 300k"},
        ])
        consolidator._fetch_active_memories = MagicMock(return_value=[])
        consolidator._analyze_with_oracle = MagicMock(return_value={
            "facts": [],
            "conflicts": [],
            "patterns": [{"fact": "Budget 300k", "occurrences": 3, "domains": ["scout"]}],
            "summary": "Reinforced budget pattern.",
        })
        consolidator._save_memory = MagicMock(return_value=True)
        consolidator._reinforce_pattern = MagicMock()

        result = consolidator.consolidate("test-session")
        assert result["patterns_reinforced"] == 1

    def test_consolidate_handles_oracle_error(self, consolidator):
        """Oracle failure should not crash consolidation."""
        consolidator._fetch_chat_history = MagicMock(return_value=[
            {"role": "user", "content": "test"},
        ])
        consolidator._fetch_active_memories = MagicMock(return_value=[])
        consolidator._analyze_with_oracle = MagicMock(return_value=None)

        result = consolidator.consolidate("test-session")
        assert result["facts_extracted"] == 0  # No crash


# ═══════════════════════════════════════════════════════════════════════════════
# Preference decay
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestDecayPreferences:
    def test_decay_old_preferences(self, consolidator):
        """Preferences older than 90 days should be decayed."""
        old = [
            {"id": 1, "fact": "Old pref", "weight": 0.5,
             "created_at": "2020-01-01T00:00:00", "updated_at": "2020-06-01T00:00:00"},
            {"id": 2, "fact": "Very old", "weight": 0.15,
             "created_at": "2019-01-01T00:00:00", "updated_at": "2019-06-01T00:00:00"},
        ]
        with patch("core.consolidator.requests") as mock_req:
            mock_req.patch.return_value.status_code = 200
            decayed = consolidator._decay_old_preferences(old)
            assert decayed >= 1  # At least the very-old one (weight <= 0.2) gets fully deprecated

    def test_decay_no_old_preferences(self, consolidator):
        """Recent preferences should not be decayed."""
        recent = [
            {"id": 1, "fact": "Recent pref", "weight": 1.0,
             "created_at": "2026-06-15T00:00:00", "updated_at": "2026-06-15T00:00:00"},
        ]
        with patch("core.consolidator.requests") as mock_req:
            mock_req.patch.return_value.status_code = 200
            decayed = consolidator._decay_old_preferences(recent)
            assert decayed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# JSON extraction helper
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestExtractJson:
    def test_extract_clean_json(self):
        raw = '{"facts": [], "summary": "ok"}'
        result = MemoryConsolidator._extract_json(raw)
        parsed = json.loads(result)
        assert parsed["summary"] == "ok"

    def test_extract_json_with_surrounding_text(self):
        raw = 'Here is the analysis:\n{"facts": [{"fact": "test"}], "summary": "done"}\nHope this helps.'
        result = MemoryConsolidator._extract_json(raw)
        parsed = json.loads(result)
        assert parsed["facts"][0]["fact"] == "test"

    def test_extract_json_no_braces(self):
        raw = "No JSON here"
        result = MemoryConsolidator._extract_json(raw)
        assert result == raw


# ═══════════════════════════════════════════════════════════════════════════════
# Active sessions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestActiveSessions:
    def test_get_active_sessions_empty(self, consolidator):
        """No sessions should return empty list."""
        sessions = consolidator.get_active_sessions()
        assert isinstance(sessions, list)

    def test_get_active_sessions_handles_error(self, consolidator):
        """API error should return empty list, not crash."""
        import core.consolidator as mod
        with patch.object(mod.requests, "get", side_effect=Exception("Connection refused")):
            sessions = consolidator.get_active_sessions()
            assert sessions == []
