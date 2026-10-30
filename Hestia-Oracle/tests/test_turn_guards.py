"""Turn guards: fixed rules on writes, whatever the model decides (bench with small models, 2026-10-30)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.agent_loop import ToolDefinition
from core.services.turn_guards import MAX_WRITES, TurnGuards, is_question_or_advice

pytestmark = pytest.mark.unit


def _tool(name, writes=True, out=(True, {"ok": True})):
    return ToolDefinition(name=name, description="", parameters={}, handler=MagicMock(return_value=out),
                          writes=writes, title=name)


def _turn(message, *tools):
    TurnGuards(message).wrap(list(tools))
    return tools


def test_question_and_advice():
    assert is_question_or_advice("stasera voglio una pizza, mi consigli qualcosa?")
    assert is_question_or_advice("cosa mi metto domani?")
    assert not is_question_or_advice("ho speso 23 euro al supermercato")
    assert not is_question_or_advice("mi aggiungi la giacca al guardaroba?")
    assert not is_question_or_advice("ho fatto 5 km, lo registri?")


def test_a_question_writes_nothing():
    """«mi consigli una pizza?» registered a dinner (bench round 2)."""
    meal, read = _tool("cibo_pasto"), _tool("cibo_pasti", writes=False)
    _turn("stasera voglio mangiare una pizza, mi consigli qualcosa?", meal, read)
    ok, why = meal.handler(text="pizza")
    assert not ok and why.startswith("BLOCCATO")
    assert read.handler()[0]


def test_a_write_tool_with_no_values_reads_on_a_question():
    """cibo_dieta with no params only reads the diet: refused, the pizza advice ended empty (bench round 4)."""
    diet = _tool("cibo_dieta")
    _turn("stasera voglio una pizza, che mi consigli?", diet)
    assert diet.handler()[0]
    assert not diet.handler(goal="dimagrire")[0]


def test_refused_call_is_not_a_failure_for_the_user():
    from core.agent_loop import _failed_writes
    log = [{"tool": "cibo_pasto", "title": "Pasto", "ok": False, "writes": True, "refused": True},
           {"tool": "finance_add", "title": "Spesa", "ok": False, "writes": True}]
    assert _failed_writes(log) == ["Spesa"]


def test_proposals_pass_on_a_question():
    prop = _tool("settings_propose")
    _turn("puoi rispondermi più breve?", prop)
    assert prop.handler(key="x")[0]


def test_one_thing_one_place():
    """«mia mamma si chiama Laura» → person card and a memory (bench round 3)."""
    person, mem = _tool("people_add"), _tool("memory.save", out=(True, "Memory saved"))
    _turn("mia mamma si chiama Laura e vive a Trieste", person, mem)
    assert person.handler(name="Laura")[0]
    ok, out = mem.handler(fact="La madre si chiama Laura")
    assert ok and out["already_known"]
    person2, mem2 = _tool("people_add"), _tool("memory.save", out=(True, "Memory saved"))
    _turn("ricorda che mia mamma si chiama Laura e segnala nelle persone", person2, mem2)
    person2.handler(name="Laura")
    assert mem2.handler(fact="x") == (True, "Memory saved")


def test_delete_needs_the_users_words():
    rm = _tool("finance_delete")
    _turn("ho speso 23 euro al supermercato", rm)
    assert not rm.handler(id="t1")[0]
    rm2 = _tool("finance_delete")
    _turn("cancella la spesa di ieri", rm2)
    assert rm2.handler(id="t1")[0]


def test_forge_needs_a_yes_or_an_explicit_build_ask():
    """A small model started a dev task on «vorrei un comando…» without asking (bench round 3)."""
    dev = _tool("forge_develop")
    _turn("vorrei un comando che mi mostra il meteo della settimana", dev)
    ok, why = dev.handler(request="meteo")
    assert not ok and "ask_user" in why
    for msg in ("sì, procedi", "sviluppa un comando per il meteo della settimana"):
        dev = _tool("forge_develop")
        _turn(msg, dev)
        assert dev.handler(request="meteo")[0]


def test_runaway_writes_stop():
    add = _tool("finance_add")
    _turn("registra queste spese", add)
    results = [add.handler(amount=i)[0] for i in range(MAX_WRITES + 2)]
    assert results.count(True) == MAX_WRITES and results[-1] is False
