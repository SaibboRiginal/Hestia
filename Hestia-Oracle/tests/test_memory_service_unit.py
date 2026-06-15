"""Unit tests for MemoryService — save_memory, search_memories, preference lifecycle.

All Archive/LLM calls mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from core.services.memory_service import (
    MemoryService,
    MEMORY_CLASS_PREFERENCE,
    MEMORY_CLASS_COMMITMENT,
    MEMORY_CLASS_CONVERSATION,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def memory_service():
    """MemoryService with all external deps mocked."""
    scribe = MagicMock()
    scribe.ask.return_value = "NONE"
    fallback_scribe = MagicMock()
    fallback_scribe.ask.return_value = "NONE"
    context_builder = MagicMock()
    context_builder.max_history_messages = 10
    context_builder.max_history_chars = 500
    context_builder.truncate = lambda text, max_len: str(text)[:max_len]

    svc = MemoryService(
        archive_url="http://fake-archive:19002/api",
        hub_api_url="http://fake-hub:19001/api",
        scribe_agent=scribe,
        fallback_scribe_agent=fallback_scribe,
        context_builder=context_builder,
    )

    # Mock _route_archive
    svc._route_archive = MagicMock(return_value={"ok": True})
    return svc


# ═══════════════════════════════════════════════════════════════════════════════
# save_memory (agent-loop tool handler)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSaveMemory:
    def test_save_memory_persists_fact(self, memory_service):
        ok, msg = memory_service.save_memory(
            fact="User prefers Roma",
            domain="general",
        )
        assert ok is True
        assert "Roma" in msg or "saved" in msg.lower()
        memory_service._route_archive.assert_called()
        call_args = memory_service._route_archive.call_args
        body = call_args[1].get("body", {})
        assert body.get("fact") == "User prefers Roma"
        assert body.get("memory_class") == MEMORY_CLASS_PREFERENCE

    def test_save_memory_rejects_empty_fact(self, memory_service):
        ok, msg = memory_service.save_memory(fact="", domain="general")
        assert ok is False
        assert "empty" in msg.lower() or "cannot" in msg.lower()

    def test_save_memory_rejects_whitespace_fact(self, memory_service):
        ok, msg = memory_service.save_memory(fact="   ", domain="general")
        assert ok is False

    def test_save_memory_defaults_domain_to_general(self, memory_service):
        ok, msg = memory_service.save_memory(fact="User likes coffee")
        assert ok is True
        call_args = memory_service._route_archive.call_args
        body = call_args[1].get("body", {})
        assert body.get("domain") == "general"

    def test_save_memory_handles_persistence_failure(self, memory_service):
        memory_service._route_archive.return_value = None
        ok, msg = memory_service.save_memory(fact="Test", domain="general")
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# search_memories (agent-loop tool handler)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSearchMemories:
    def test_search_memories_returns_results(self, memory_service):
        # Mock _get_active_memory
        memory_service._get_active_memory = MagicMock(return_value=[
            {"id": 1, "fact": "User likes Roma", "domain": "scout"},
            {"id": 2, "fact": "User prefers modern style", "domain": "scout"},
            {"id": 3, "fact": "Budget max 500k", "domain": "scout"},
        ])

        ok, results = memory_service.search_memories(query="Roma")
        assert ok is True
        assert len(results) >= 1
        assert any("Roma" in r.get("fact", "") for r in results)

    def test_search_memories_empty_query_returns_all(self, memory_service):
        memory_service._get_active_memory = MagicMock(return_value=[
            {"id": 1, "fact": "Pref A", "domain": "general"},
        ])
        ok, results = memory_service.search_memories(query="")
        assert ok is True
        assert len(results) >= 1

    def test_search_memories_no_match_returns_empty(self, memory_service):
        memory_service._get_active_memory = MagicMock(return_value=[
            {"id": 1, "fact": "User likes Roma", "domain": "scout"},
        ])
        ok, results = memory_service.search_memories(query="Milano")
        assert ok is True
        assert len(results) == 0

    def test_search_memories_handles_exception(self, memory_service):
        memory_service._get_active_memory = MagicMock(side_effect=RuntimeError("DB down"))
        ok, results = memory_service.search_memories(query="Roma")
        assert ok is False
        assert isinstance(results, str)

    def test_search_memories_case_insensitive(self, memory_service):
        memory_service._get_active_memory = MagicMock(return_value=[
            {"id": 1, "fact": "User likes ROMA", "domain": "scout"},
        ])
        ok, results = memory_service.search_memories(query="roma")
        assert ok is True
        assert len(results) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# _save_memory_fact (internal)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSaveMemoryFact:
    def test_save_memory_fact_correct_payload(self, memory_service):
        memory_service._route_archive.return_value = {"id": 42}
        ok = memory_service._save_memory_fact(
            fact="Test fact",
            domain="scout",
            memory_class=MEMORY_CLASS_PREFERENCE,
        )
        assert ok is True
        call_body = memory_service._route_archive.call_args[1]["body"]
        assert call_body["fact"] == "Test fact"
        assert call_body["domain"] == "scout"
        assert call_body["weight"] == 1.0

    def test_save_memory_fact_returns_false_on_failure(self, memory_service):
        memory_service._route_archive.return_value = None
        ok = memory_service._save_memory_fact("Test", "general", MEMORY_CLASS_PREFERENCE)
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# _ask fallback chain
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestAskFallback:
    def test_primary_used_when_available(self, memory_service):
        memory_service.scribe.ask.return_value = "Primary response"
        result = memory_service._ask("Test prompt")
        assert result == "Primary response"

    def test_fallback_used_when_primary_fails(self, memory_service):
        memory_service.scribe.ask.side_effect = RuntimeError("Primary down")
        memory_service.fallback_scribe.ask.return_value = "Fallback response"
        result = memory_service._ask("Test prompt")
        assert result == "Fallback response"

    def test_both_fail_returns_none(self, memory_service):
        memory_service.scribe.ask.side_effect = RuntimeError("Primary down")
        memory_service.fallback_scribe.ask.side_effect = RuntimeError("Fallback down")
        result = memory_service._ask("Test prompt")
        assert result == "NONE"


# ═══════════════════════════════════════════════════════════════════════════════
# _save_subscriptions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSaveSubscriptions:
    def test_add_subscription_emits_signal(self, memory_service):
        memory_service._route_archive.return_value = {"subscription_id": "sub-123"}
        subs = [{
            "action": "ADD",
            "subscription_id": "sub-123",
            "domain": "scout",
            "event_type": "entity.upserted",
            "filters": {"city": "Roma"},
            "channels": [{"type": "telegram", "target": "12345"}],
        }]
        signals = memory_service._save_subscriptions(subs, {}, "test-session")
        assert len(signals) == 1
        assert signals[0]["event"] == "subscription.added"

    def test_deprecate_subscription_disables_it(self, memory_service):
        memory_service._route_archive.return_value = {"ok": True}
        existing = {
            "sub-456": {
                "subscription_id": "sub-456",
                "domain": "scout",
                "event_type": "entity.upserted",
                "filters": {},
                "channels": [{"type": "telegram", "target": "12345"}],
                "is_active": True,
            }
        }
        subs = [{"action": "DEPRECATE", "subscription_id": "sub-456"}]
        signals = memory_service._save_subscriptions(subs, existing, "test-session")
        assert len(signals) == 1
        assert signals[0]["event"] == "subscription.removed"

    def test_upsert_updates_existing(self, memory_service):
        memory_service._route_archive.return_value = {"ok": True}
        existing = {
            "sub-789": {
                "subscription_id": "sub-789",
                "domain": "scout",
                "event_type": "entity.upserted",
                "filters": {"city": "Roma"},
                "channels": [{"type": "telegram", "target": "12345"}],
                "is_active": True,
            }
        }
        subs = [{
            "action": "ADD",
            "subscription_id": "sub-789",
            "domain": "scout",
            "event_type": "entity.upserted",
            "filters": {"city": "Milano"},  # changed
            "channels": [{"type": "telegram", "target": "12345"}],
        }]
        signals = memory_service._save_subscriptions(subs, existing, "test-session")
        # Should detect change and emit "changed"
        assert len(signals) == 1
        assert signals[0]["event"] == "subscription.changed"

    def test_no_signal_for_identical_upsert(self, memory_service):
        memory_service._route_archive.return_value = {"ok": True}
        payload = {
            "subscription_id": "sub-999",
            "domain": "scout",
            "event_type": "entity.upserted",
            "filters": {"city": "Roma"},
            "channels": [{"type": "telegram", "target": "12345"}],
            "is_active": True,
        }
        existing = {"sub-999": dict(payload)}
        subs = [{"action": "ADD", **payload}]
        signals = memory_service._save_subscriptions(subs, existing, "test-session")
        # No change → no signal
        assert len(signals) == 0

    def test_empty_subscription_id_skipped(self, memory_service):
        subs = [{"action": "ADD", "subscription_id": "", "domain": "scout"}]
        signals = memory_service._save_subscriptions(subs, {}, "test-session")
        assert len(signals) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# _save_preferences
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSavePreferences:
    def test_add_preference_emits_signal(self, memory_service):
        memory_service._save_memory_fact = MagicMock(return_value=True)
        actions = [{"action": "ADD", "fact": "User likes Roma", "domain": "scout"}]
        signals = memory_service._save_preferences(actions, {})
        assert len(signals) == 1
        assert signals[0]["event"] == "memory.preference.added"

    def test_deprecate_preference_emits_signal(self, memory_service):
        memory_service._route_archive.return_value = {"ok": True}
        actions = [{"action": "DEPRECATE", "id": 42}]
        prefs_by_id = {42: {"id": 42, "fact": "Old preference", "domain": "general"}}
        signals = memory_service._save_preferences(actions, prefs_by_id)
        assert len(signals) == 1
        assert signals[0]["event"] == "memory.preference.removed"


# ═══════════════════════════════════════════════════════════════════════════════
# Memory class constants
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestMemoryClasses:
    def test_constants_are_distinct(self):
        classes = [
            MEMORY_CLASS_CONVERSATION,
            MEMORY_CLASS_PREFERENCE,
            MEMORY_CLASS_COMMITMENT,
        ]
        assert len(classes) == len(set(classes))

    def test_preference_class_is_correct(self):
        assert MEMORY_CLASS_PREFERENCE == "durable_user_preference"

    def test_commitment_class_is_correct(self):
        assert MEMORY_CLASS_COMMITMENT == "assistant_commitment"
