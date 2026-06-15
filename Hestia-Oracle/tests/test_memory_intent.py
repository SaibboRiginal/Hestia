"""Tests — memory_intent module (Phase 1.2)

Pure function tests: no mocking, no network, no LLM.
All 11 cases from TESTING.md §1.2.
"""
import pytest

# The conftest.py adds app/ to sys.path
from core.services.memory_intent import (
    has_notification_intent,
    has_preference_intent,
    has_deprecate_intent,
    is_fact_grounded_in_message,
)

# ── has_preference_intent ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestHasPreferenceIntent:
    def test_italian_explicit_keyword_preferisco(self):
        assert has_preference_intent(
            "preferisco appartamenti con terrazzo") is True

    def test_italian_keyword_vorrei(self):
        assert has_preference_intent("vorrei qualcosa con 3 stanze") is True

    def test_english_keyword_i_like(self):
        assert has_preference_intent(
            "i like open spaces and natural light") is True

    def test_english_keyword_looking_for(self):
        assert has_preference_intent(
            "I'm looking for a 2-bedroom flat") is True

    def test_budget_keyword(self):
        assert has_preference_intent("il mio budget massimo è 300000") is True

    def test_no_preference_neutral_query(self):
        assert has_preference_intent("com'è il meteo oggi?") is False

    def test_no_preference_greeting(self):
        assert has_preference_intent("ciao come stai") is False

    def test_empty_string_returns_false(self):
        assert has_preference_intent("") is False

    def test_whitespace_only_returns_false(self):
        assert has_preference_intent("   ") is False


# ── has_notification_intent ───────────────────────────────────────────────────

@pytest.mark.unit
class TestHasNotificationIntent:
    def test_italian_avvisami(self):
        assert has_notification_intent(
            "avvisami se escono nuovi annunci") is True

    def test_italian_notifica(self):
        assert has_notification_intent("attiva notifica per Milano") is True

    def test_english_alert(self):
        assert has_notification_intent(
            "send me an alert when new listings arrive") is True

    def test_no_notification_casual(self):
        assert has_notification_intent("mostrami gli annunci") is False

    def test_empty_string_returns_false(self):
        assert has_notification_intent("") is False


# ── has_deprecate_intent ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestHasDeprecateIntent:
    def test_italian_cancella(self):
        assert has_deprecate_intent(
            "cancella la mia preferenza sul budget") is True

    def test_italian_dimentica(self):
        assert has_deprecate_intent(
            "dimentica quello che ti ho detto sul tono") is True

    def test_english_forget(self):
        assert has_deprecate_intent("forget my previous setting") is True

    def test_english_reset(self):
        assert has_deprecate_intent("reset everything") is True

    def test_no_deprecate_casual(self):
        assert has_deprecate_intent("puoi mostrarmi la lista?") is False

    def test_empty_returns_false(self):
        assert has_deprecate_intent("") is False


# ── is_fact_grounded_in_message ───────────────────────────────────────────────

@pytest.mark.unit
class TestIsFactGroundedInMessage:
    def test_fact_grounded_with_shared_token(self):
        # 'appartamento' appears in both fact and message
        result = is_fact_grounded_in_message(
            "L'utente cerca appartamento con terrazzo",
            "voglio un appartamento con grande terrazzo",
        )
        assert result is True

    def test_fact_not_grounded_unrelated(self):
        result = is_fact_grounded_in_message(
            "L'utente preferisce auto sportive",
            "vorrei un appartamento a Milano",
        )
        assert result is False

    def test_synthetic_fragment_oracle_rejected(self):
        # 'oracle' in fact but not in message → reject
        result = is_fact_grounded_in_message(
            "oracle said the user wants something",
            "vorrei qualcosa di tranquillo",
        )
        assert result is False

    def test_synthetic_fragment_hestia_rejected(self):
        result = is_fact_grounded_in_message(
            "hestia remember the user wants sushi",
            "voglio uscire stasera",
        )
        assert result is False

    def test_synthetic_fragment_allowed_if_in_message(self):
        # 'hestia' in both fact AND message → allowed
        result = is_fact_grounded_in_message(
            "hestia deve ricordare il budget",
            "hestia ricorda il mio budget di 200k",
        )
        assert result is True

    def test_empty_fact_returns_false(self):
        assert is_fact_grounded_in_message("", "non importa") is False

    def test_empty_message_returns_false(self):
        assert is_fact_grounded_in_message(
            "preferisce case grandi", "") is False

    def test_both_empty_returns_false(self):
        assert is_fact_grounded_in_message("", "") is False

    def test_short_tokens_under_threshold_not_counted(self):
        # Tokens shorter than 4 chars are ignored; if no overlap, returns False.
        result = is_fact_grounded_in_message("si no ma va", "ok si no")
        # Both have only short tokens → no overlap counted → False
        assert result is False
