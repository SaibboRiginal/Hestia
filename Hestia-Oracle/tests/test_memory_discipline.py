"""Memory discipline with a real model (bench 2026-10-30): one fact = one row, the chat's own memory tools win
over the background extractor, what an action saved is not saved again as a memory."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.memory_intent import same_fact
from core.services.memory_service import MemoryService

pytestmark = pytest.mark.unit

JOB = "Lavoro come sviluppatore software in un'azienda a Udine, dalle 09:00 alle 18:00."


def test_same_fact_in_other_words():
    assert same_fact("L'utente è allergico alle noccioline.", "L'utente è allergico alle noccioline.")
    assert same_fact("Lavoro come sviluppatore software a Udine, orario 09:00-18:00.", JOB)
    assert same_fact("L'utente lavora come sviluppatore software a Udine con orario 09:00-18:00.", JOB)


def test_new_details_are_not_the_same_fact():
    assert not same_fact("L'utente lavora come sviluppatore software a Udine con orario 09:00-18:00.",
                         "L'utente ha un lavoro d'ufficio con orario 9-18.")
    assert not same_fact("L'utente preferisce il tè verde.", "L'utente preferisce il caffè amaro.")
    assert not same_fact("", JOB)


def _service(rows):
    svc = MemoryService.__new__(MemoryService)
    svc._get_active_memory = MagicMock(return_value=rows)
    svc._save_memory_fact = MagicMock(return_value=True)
    svc.pref_domain_classifier = None
    return svc


def test_memory_save_tool_does_not_store_a_known_fact():
    svc = _service([{"id": 8, "fact": JOB}])
    ok, out = svc.save_memory("L'utente lavora come sviluppatore software a Udine, orario 9-18.")
    assert ok and out["already_known"] and out["id"] == 8
    svc._save_memory_fact.assert_not_called()
    ok, out = svc.save_memory("L'utente è allergico alle noccioline.")
    assert ok and "Memory saved" in out
    svc._save_memory_fact.assert_called_once()


def test_extractor_skips_known_facts():
    svc = _service([{"id": 8, "fact": JOB}])
    signals = svc._save_preferences([{"action": "ADD", "fact": "L'utente lavora come sviluppatore a Udine 9-18."},
                                     {"action": "ADD", "fact": "L'utente ha un gatto di nome Fuffi."}], {})
    assert [s["data"]["fact"] for s in signals] == ["L'utente ha un gatto di nome Fuffi."]


def test_extractor_off_when_the_chat_used_its_memory_tools():
    svc = _service([])
    svc._ask = MagicMock(return_value="NONE")
    svc._build_conversation_context = MagicMock(return_value=([], ["general"], ""))
    assert svc.extract_and_save_preferences("sono allergico alle noccioline", "s1", memory_by_tool=True) == []
    svc._ask.assert_not_called()


def test_extractor_off_when_an_action_stored_it():
    """«mia mamma si chiama Laura» → people_add and a memory (small-model bench 2026-10-30)."""
    svc = _service([])
    svc._ask = MagicMock(return_value="NONE")
    svc._build_conversation_context = MagicMock(return_value=([], ["general"], ""))
    assert svc.extract_and_save_preferences("mia mamma si chiama Laura e vive a Trieste", "s1",
                                            done_actions=["Aggiungi persona"]) == []
    svc.extract_and_save_preferences("ricordami ogni lunedì alle 9 di pesarmi", "s1", done_actions=["Nuova routine"])
    svc._ask.assert_not_called()


def test_extractor_sees_what_the_turn_already_did_when_asked_to_remember():
    svc = _service([])
    svc._ask = MagicMock(return_value="NONE")
    svc._build_conversation_context = MagicMock(return_value=([], ["general"], ""))
    svc.extract_and_save_preferences("ricorda che mia mamma si chiama Laura, e segnala nelle persone", "s1",
                                     done_actions=["Aggiungi persona"])
    prompt = svc._ask.call_args[0][0]
    assert "AZIONI GIÀ FATTE IN QUESTO TURNO: Aggiungi persona" in prompt
    assert "promemoria, non memoria" in prompt


def test_search_finds_other_word_forms():
    """«dimentica dove lavoro» must find «L'utente lavora…», or nothing is forgotten."""
    svc = _service([{"id": 12, "fact": "L'utente lavora come sviluppatore a Udine."},
                    {"id": 13, "fact": "L'utente è allergico alle noccioline."}])
    ok, rows = svc.search_memories("lavoro")
    assert ok and [r["id"] for r in rows] == [12]


def test_quick_answer_that_claims_an_action_is_asked_again():
    from core.oracle_engine import _CLAIMED_ACTION, OracleEngine
    assert _CLAIMED_ACTION.search("Ho registrato la stanchezza. Riduco gli impegni non urgenti.")
    assert _CLAIMED_ACTION.search("Ho registrato il carico ridotto per oggi.")
    assert not _CLAIMED_ACTION.search("Riposati: una giornata leggera aiuta.")
    assert not _CLAIMED_ACTION.search("Non ho salvato nulla.")
    eng = OracleEngine.__new__(OracleEngine)
    eng._ask_analyst = MagicMock(side_effect=["Ho registrato la stanchezza.", "Capita: oggi vai piano."])
    assert eng._quick_answer("oggi sono stanco", "", None, None) == "Capita: oggi vai piano."
    assert "non hai fatto nessuna azione" in eng._ask_analyst.call_args_list[1][0][0]
