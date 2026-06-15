"""Tests — UserControlService (Phase 1.4)

Unit tests for UserControlService: defaults, parsing, validation, merging,
get_controls, update_controls, and save flow. All mocked — no network.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call
import pytest

from core.services.user_control_service import UserControlService

_CONTROL_PREFIX = "[CONTROL]"
_CONTROL_DOMAIN = "user_controls"
_CONTROL_CLASS = "durable_user_preference"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_service(rows: list[dict] | None = None) -> UserControlService:
    hub = MagicMock()
    hub.get.return_value = rows or []
    hub.post.return_value = {"ok": True}
    scribe = MagicMock()
    scribe.ask.return_value = "NONE"
    fallback = MagicMock()
    fallback.ask.return_value = "NONE"
    return UserControlService(hub, scribe, fallback)


def _control_row(data: dict, row_id: int = 1) -> dict:
    fact = f"{_CONTROL_PREFIX} {json.dumps(data)}"
    return {"id": row_id, "fact": fact, "domain": _CONTROL_DOMAIN}


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestUserControlServiceDefaults:
    def test_defaults_have_correct_keys(self):
        svc = _make_service()
        defaults = svc._defaults()
        assert "proactive_enabled" in defaults
        assert "allowed_categories" in defaults
        assert "quiet_hours" in defaults
        assert "reminder_aggressiveness" in defaults
        assert "dont_ask_again" in defaults
        assert "reset_scope" in defaults

    def test_defaults_proactive_enabled_true(self):
        svc = _make_service()
        assert svc._defaults()["proactive_enabled"] is True

    def test_defaults_reminder_aggressiveness_normal(self):
        svc = _make_service()
        assert svc._defaults()["reminder_aggressiveness"] == "normal"


@pytest.mark.unit
class TestControlParsing:
    def test_parse_valid_control_fact(self):
        fact = f"{_CONTROL_PREFIX} {{\"proactive_enabled\": false}}"
        result = UserControlService._parse_control_fact(fact)
        assert result is not None
        assert result.get("proactive_enabled") is False

    def test_parse_missing_prefix_returns_none(self):
        fact = json.dumps({"proactive_enabled": False})
        assert UserControlService._parse_control_fact(fact) is None

    def test_parse_malformed_json_returns_none(self):
        fact = f"{_CONTROL_PREFIX} {{not valid json}}"
        assert UserControlService._parse_control_fact(fact) is None

    def test_parse_empty_returns_none(self):
        assert UserControlService._parse_control_fact("") is None


@pytest.mark.unit
class TestNormalizeHHMM:
    def test_valid_hhmm_returns_padded(self):
        result = UserControlService._normalize_hhmm("9:30")
        assert result == "09:30"

    def test_full_format_unchanged(self):
        result = UserControlService._normalize_hhmm("22:00")
        assert result == "22:00"

    def test_dot_separator_normalised(self):
        result = UserControlService._normalize_hhmm("8.45")
        assert result == "08:45"

    def test_invalid_format_returns_none(self):
        assert UserControlService._normalize_hhmm("25:00") is None
        assert UserControlService._normalize_hhmm("abc") is None
        assert UserControlService._normalize_hhmm("12:60") is None

    def test_empty_returns_none(self):
        assert UserControlService._normalize_hhmm("") is None


@pytest.mark.unit
class TestGetControls:
    def test_no_rows_returns_defaults(self):
        svc = _make_service(rows=[])
        controls = svc.get_controls()
        assert controls == svc._defaults()

    def test_single_row_overrides_defaults(self):
        row = _control_row({"proactive_enabled": False,
                           "reminder_aggressiveness": "high"})
        svc = _make_service(rows=[row])
        controls = svc.get_controls()
        assert controls["proactive_enabled"] is False
        assert controls["reminder_aggressiveness"] == "high"

    def test_multiple_rows_picks_latest_by_id(self):
        older = _control_row({"proactive_enabled": True}, row_id=1)
        newer = _control_row({"proactive_enabled": False}, row_id=5)
        svc = _make_service(rows=[older, newer])
        controls = svc.get_controls()
        # Newest row has id=5 → proactive_enabled=False
        assert controls["proactive_enabled"] is False

    def test_invalid_aggressiveness_value_ignored(self):
        row = _control_row({"reminder_aggressiveness": "extreme"})
        svc = _make_service(rows=[row])
        controls = svc.get_controls()
        # "extreme" is not in allowed set → stays at default "normal"
        assert controls["reminder_aggressiveness"] == "normal"


@pytest.mark.unit
class TestUpdateControls:
    def test_valid_patch_saved_and_merged(self):
        svc = _make_service(rows=[])
        merged, saved = svc.update_controls({"proactive_enabled": False})
        assert merged["proactive_enabled"] is False
        svc._hub.post.assert_called_once()

    def test_empty_patch_returns_current_not_saved(self):
        svc = _make_service(rows=[])
        merged, saved = svc.update_controls({})
        assert saved is False
        svc._hub.post.assert_not_called()

    def test_quiet_hours_merged_into_existing(self):
        svc = _make_service(rows=[])
        merged, _ = svc.update_controls(
            {"quiet_hours": {"enabled": True, "start": "23:00", "end": "06:00"}})
        assert merged["quiet_hours"]["enabled"] is True
        assert merged["quiet_hours"]["start"] == "23:00"

    def test_save_failure_returns_false(self):
        svc = _make_service(rows=[])
        svc._hub.post.side_effect = Exception("Network error")
        _, saved = svc.update_controls({"proactive_enabled": False})
        assert saved is False

    def test_allowed_categories_deduplicated(self):
        svc = _make_service(rows=[])
        merged, _ = svc.update_controls({
            "allowed_categories": ["alerts", "tasks", "alerts", "tasks"]
        })
        cats = merged["allowed_categories"]
        assert len(cats) == len(set(cats))
