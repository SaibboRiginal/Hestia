"""Extended tests for ContextBuilder — compaction, protected messages, history building.

Covers the 75% gap in context_builder.py.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from core.services.context_builder import ContextBuilder


@pytest.fixture
def builder():
    return ContextBuilder(
        max_history_messages=10,
        max_history_chars=500,
        max_entities_in_context=5,
        max_field_chars=100,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# compact_history
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestCompactHistory:
    def test_empty_history_returns_empty_string(self, builder):
        assert builder.compact_history([]) == ""

    def test_single_message(self, builder):
        history = [{"role": "user", "content": "Ciao"}]
        result = builder.compact_history(history)
        assert "User: Ciao" in result
        assert "PREVIOUS CONVERSATION" in result

    def test_user_and_assistant_roles(self, builder):
        history = [
            {"role": "user", "content": "Domanda"},
            {"role": "assistant", "content": "Risposta"},
        ]
        result = builder.compact_history(history)
        assert "User: Domanda" in result
        assert "Hestia: Risposta" in result

    def test_truncates_long_messages(self, builder):
        history = [{"role": "user", "content": "x" * 1000}]
        result = builder.compact_history(history)
        content = result.split("User: ")[1]
        assert len(content) <= builder.max_history_chars + 5  # +truncation char

    def test_limits_to_max_messages(self, builder):
        history = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        result = builder.compact_history(history)
        # Should only have last 10 messages
        assert "msg0" not in result
        assert "msg19" in result


# ═══════════════════════════════════════════════════════════════════════════════
# compact_entity
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestCompactEntity:
    def test_priority_keys_included(self, builder):
        entity = {
            "id": 1, "entity_id": "abc", "url": "https://example.com",
            "title": "Test", "price": 100000, "summary": "A test entity",
            "status": "active", "extra_field": "should be excluded",
        }
        compact = builder.compact_entity(entity)
        assert "id" in compact
        assert "title" in compact
        assert "url" in compact

    def test_truncates_long_string_fields(self, builder):
        entity = {"title": "T" * 200, "description": "D" * 200}
        compact = builder.compact_entity(entity)
        assert len(compact.get("title", "")) <= builder.max_field_chars + 1

    def test_empty_entity_returns_record_key(self, builder):
        compact = builder.compact_entity({})
        assert "record" in compact

    def test_nested_dict_fields(self, builder):
        entity = {
            "title": "Test",
            "specs": {"surface_m2": 80, "rooms": 3, "floor": 2},
        }
        compact = builder.compact_entity(entity)
        assert "specs" in compact
        assert compact["specs"]["surface_m2"] == 80


# ═══════════════════════════════════════════════════════════════════════════════
# compact_entities_for_prompt
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestCompactEntitiesForPrompt:
    def test_empty_entities_returns_no_records_message(self, builder):
        result = builder.compact_entities_for_prompt([])
        assert "No records found" in result

    def test_single_entity_json_output(self, builder):
        entities = [{"title": "Test", "price": 100000}]
        result = builder.compact_entities_for_prompt(entities)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Test"

    def test_limits_to_max_entities(self, builder):
        entities = [{"title": f"Item{i}"} for i in range(10)]
        result = builder.compact_entities_for_prompt(entities)
        parsed = json.loads(result)
        assert len(parsed) <= builder.max_entities_in_context


# ═══════════════════════════════════════════════════════════════════════════════
# build_analysis_prompt
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestBuildAnalysisPrompt:
    def test_includes_all_sections(self, builder):
        prompt = builder.build_analysis_prompt(
            preference_facts=["Preferisce Roma"],
            valid_domains=["scout"],
            active_filters={"city": "Milano"},
            filters_gt={},
            filters_lt={"price": 500000},
            sort_by="price",
            sort_order="asc",
            formatted_context='[{"title": "Test"}]',
            history_text="User: Ciao\n",
            user_message="Cerca case",
            current_datetime_context="today_date=2026-06-12",
        )
        assert "USER_PREFERENCES" in prompt
        assert "Preferisce Roma" in prompt
        assert "ROUTE_METADATA" in prompt
        assert "scout" in prompt
        assert "CONTEXT_DATA_RECORDS" in prompt
        assert "USER_QUESTION" in prompt
        assert "Cerca case" in prompt
        assert "today_date=2026-06-12" in prompt

    def test_no_preferences_shows_none_message(self, builder):
        prompt = builder.build_analysis_prompt(
            preference_facts=[], valid_domains=["general"],
            active_filters={}, filters_gt={}, filters_lt={},
            sort_by=None, sort_order="desc",
            formatted_context="test", history_text="",
            user_message="Hello",
        )
        assert "Nessuna preferenza" in prompt

    def test_omits_datetime_when_none(self, builder):
        prompt = builder.build_analysis_prompt(
            preference_facts=[], valid_domains=["general"],
            active_filters={}, filters_gt={}, filters_lt={},
            sort_by=None, sort_order="desc",
            formatted_context="test", history_text="",
            user_message="Hello",
            current_datetime_context=None,
        )
        assert "CURRENT_DATETIME_CONTEXT" not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# needs_compaction
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestNeedsCompaction:
    def test_small_history_no_compaction(self, builder):
        history = [{"role": "user", "content": "msg"}] * 5
        assert builder.needs_compaction(history) is False

    def test_large_history_needs_compaction(self, builder):
        history = [{"role": "user", "content": "msg"}] * 25
        assert builder.needs_compaction(history) is True


# ═══════════════════════════════════════════════════════════════════════════════
# extract_protected_messages
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestExtractProtectedMessages:
    def test_extracts_preference_tagged_messages(self, builder):
        history = [
            {"role": "assistant", "content": "[PREFERENCE] User likes Roma"},
            {"role": "user", "content": "Normal message"},
        ]
        protected = builder.extract_protected_messages(history)
        assert len(protected) == 1
        assert "Roma" in protected[0]["content"]

    def test_extracts_subscription_tagged_messages(self, builder):
        history = [
            {"role": "assistant", "content": "[SUBSCRIPTION] scout alert active"},
        ]
        protected = builder.extract_protected_messages(history)
        assert len(protected) == 1

    def test_extracts_commitment_tagged_messages(self, builder):
        history = [
            {"role": "assistant", "content": "[COMMITMENT] Will check tomorrow"},
        ]
        protected = builder.extract_protected_messages(history)
        assert len(protected) == 1

    def test_no_protected_messages_returns_empty(self, builder):
        history = [{"role": "user", "content": "Just a normal message"}]
        protected = builder.extract_protected_messages(history)
        assert len(protected) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# build_compaction_prompt
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestBuildCompactionPrompt:
    def test_includes_message_content(self, builder):
        history = [
            {"role": "user", "content": "Ciao"},
            {"role": "assistant", "content": "Salve!"},
        ]
        prompt = builder.build_compaction_prompt(history)
        assert "User: Ciao" in prompt
        assert "Hestia: Salve!" in prompt

    def test_empty_history(self, builder):
        prompt = builder.build_compaction_prompt([])
        assert isinstance(prompt, str)


# ═══════════════════════════════════════════════════════════════════════════════
# truncate
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestTruncate:
    def test_short_string_not_truncated(self, builder):
        assert builder.truncate("hello", 100) == "hello"

    def test_long_string_truncated_with_ellipsis(self, builder):
        result = builder.truncate("x" * 200, 100)
        assert len(result) <= 100
        assert "…" in result

    def test_exact_length_not_truncated(self, builder):
        text = "x" * 100
        assert builder.truncate(text, 100) == text
