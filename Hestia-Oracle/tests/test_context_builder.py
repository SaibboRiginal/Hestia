"""Tests — context_builder temporal prompt context.

Validates that analysis prompts include explicit current datetime context so
relative-date user requests (e.g. domani) can be resolved deterministically.
"""
from __future__ import annotations

import pytest

from core.services.context_builder import ContextBuilder


@pytest.mark.unit
class TestContextBuilderTemporalContext:
    def test_analysis_prompt_includes_current_datetime_context_when_provided(self):
        builder = ContextBuilder(
            max_history_messages=6,
            max_history_chars=500,
            max_entities_in_context=12,
            max_field_chars=280,
        )

        prompt = builder.build_analysis_prompt(
            preference_facts=["Preferisce appuntamenti mattina"],
            valid_domains=["chronos"],
            active_filters={},
            filters_gt={},
            filters_lt={},
            sort_by=None,
            sort_order="desc",
            formatted_context='[{"title":"Riunione"}]',
            history_text="",
            user_message="Che eventi ho domani?",
            current_datetime_context="timezone=Europe/Rome\nnow_iso=2026-06-02T21:30:00+02:00\ntomorrow_date=2026-06-03",
        )

        assert "CURRENT_DATETIME_CONTEXT:" in prompt
        assert "now_iso=2026-06-02T21:30:00+02:00" in prompt
        assert "tomorrow_date=2026-06-03" in prompt

    def test_analysis_prompt_omits_current_datetime_context_when_empty(self):
        builder = ContextBuilder(
            max_history_messages=6,
            max_history_chars=500,
            max_entities_in_context=12,
            max_field_chars=280,
        )

        prompt = builder.build_analysis_prompt(
            preference_facts=[],
            valid_domains=["general"],
            active_filters={},
            filters_gt={},
            filters_lt={},
            sort_by=None,
            sort_order="desc",
            formatted_context="DATABASE_RESPONSE: No records found.",
            history_text="",
            user_message="Ciao",
            current_datetime_context="",
        )

        assert "CURRENT_DATETIME_CONTEXT:" not in prompt
