"""Quiet mood capture (docs/work/2026-10-30-diario-umore): the deterministic gate, the model answer, the fallback
when the model is offline or dumb, the undo, the notice. Markers: unit"""
from __future__ import annotations

import pytest

from core.services import stream_emitter
from core.services.mood_capture import MoodCapture, guess, is_undo, mood_clauses, parse_answer

pytestmark = pytest.mark.unit

# What the user says → the label the gate must see (None = nothing to record).
BENCH = [
    ("oggi sono stanco", "stanco"),
    ("Oggi sono stanco morto", "stanco"),
    ("sono distrutta, giornata infinita", "stanco"),
    ("sono stanco, cosa mangio stasera?", "stanco"),
    ("mi sento giù", "giù"),
    ("mi sento uno schifo oggi", "giù"),
    ("non sto bene", "giù"),
    ("sto benissimo!", "contento"),
    ("oggi sto bene", "contento"),
    ("sono felice, ho passato l'esame", "contento"),
    ("sono carico per la palestra", "carico"),
    ("oggi spacco", "carico"),
    ("sono un po' nervoso per il colloquio", "nervoso"),
    ("sono in ansia per domani", "ansioso"),
    ("sono stressato dal lavoro", "ansioso"),
    ("mi sento triste", "triste"),
    ("sono incazzato nero", "arrabbiato"),
    ("ho la febbre, sono a letto", "malato"),
    ("che giornata pesante", "stanco"),
    ("giornata fantastica oggi", ""),
    ("mia moglie è stanca ma io sono carico", "carico"),
    ("ciao", None),
    ("test", None),
    ("che tempo fa domani?", None),
    ("perché sono sempre stanco?", None),
    ("Luca è stanco", None),
    ("oggi Luca è stanco", None),
    ("se fossi stanco andrei a letto", None),
    ("se sono stanco salto la palestra", None),
    ("non sono stanco", None),
    ("ieri ero stanco morto", None),
    ("mi fa male il ginocchio", None),
    ("va bene, grazie", None),
    ("ok perfetto", None),
    ("sei stanco?", None),
    ("ha scritto «sono stanco» nel messaggio", None),
    ("ricordami di comprare il latte", None),
    ("i bambini sono stanchi", None),
    ("non sono per niente stanco", None),
]


@pytest.mark.parametrize("text,label", BENCH)
def test_gate_bench(text, label):
    hits = mood_clauses(text)
    if label is None:
        assert hits == [], f"{text!r} must not be recorded: {hits}"
    else:
        assert hits, f"{text!r} must be recorded"
        g = guess(hits)
        assert 1 <= g["mood"] <= 5
        if label:
            assert label in g["labels"], (text, g)


def test_guess_lowest_mood_and_quote():
    g = guess(mood_clauses("sono felice ma stanco morto"))
    assert g["mood"] == 2 and g["energy"] == 1 and "stanco" in g["labels"] and "stanco morto" in g["quote"]
    assert guess([]) is None


def test_undo_phrases():
    for t in ("non segnarlo", "Non lo segnare per favore", "togli l'umore", "non è vero, sto bene"):
        assert is_undo(t), t
    for t in ("non sono stanco", "segna che sono stanco", "ciao"):
        assert not is_undo(t), t


def test_parse_answer():
    assert parse_answer("NONE") == "NONE" and parse_answer("`NONE`.") == "NONE"
    assert parse_answer("boh") is None and parse_answer("") is None and parse_answer("{rotto") is None
    out = parse_answer('Ecco: {"mood": 7, "energy": "2", "labels": ["Stanco", "felicione", "giu"], '
                       '"causes": ["lavoro", "x"]}')
    assert out == {"mood": 5, "energy": 2, "stress": None, "labels": ["stanco", "giù"], "causes": ["lavoro"]}
    assert parse_answer('{"energy": 2}') is None


class FakeHub:
    def __init__(self, registered=True):
        self.calls = []
        self.registered = registered

    def hub_get(self, path, default=None, timeout=6):
        if not self.registered:
            return {"services": [{"name": "hygieia", "capabilities": {}}]}
        return {"services": [{"name": "hygieia", "capabilities": {}},
                             {"name": "psyche", "capabilities": {"mood_capture_endpoint": "/api/mood/capture"}}]}

    def route_to_service(self, service, path, method, body=None, **kw):
        self.calls.append((service, path, method, body))
        if path.endswith("/undo"):
            return True, {"deleted": True, "id": "m-1"}
        return True, {"id": "m-1", "mood": body["mood"], "labels": body["labels"], "merged": False}


def test_run_uses_the_model_answer():
    hub = FakeHub()
    cap = MoodCapture(hub, lambda prompt: '{"mood": 2, "energy": 1, "stress": null, "labels": ["stanco"], '
                                          '"causes": ["lavoro"]}')
    sig = cap.run("oggi sono stanco morto, il lavoro mi ha ucciso")
    service, path, method, body = hub.calls[0]
    assert (service, path, method) == ("psyche", "/api/mood/capture", "POST")
    assert body["mood"] == 2 and body["causes"] == ["lavoro"] and "stanco morto" in body["quote"]
    assert sig[0]["event"] == "mood.logged" and "2/5" in sig[0]["data"]["detail"]


def test_run_falls_back_to_the_lexicon_when_the_model_is_dumb_or_offline():
    hub = FakeHub()
    MoodCapture(hub, lambda prompt: "Certo! L'utente sembra stanco.").run("sono stanco")
    assert hub.calls[-1][3]["labels"] == ["stanco"] and hub.calls[-1][3]["mood"] == 3

    def boom(prompt):
        raise RuntimeError("offline")
    MoodCapture(hub, boom).run("mi sento giù")
    assert hub.calls[-1][3]["labels"] == ["giù"]


def test_run_respects_model_none_and_skips_without_gate_or_module():
    hub = FakeHub()
    asked = []
    cap = MoodCapture(hub, lambda prompt: asked.append(prompt) or "NONE")
    assert cap.run("sono stanco") == [] and not hub.calls and asked
    asked.clear()
    assert cap.run("che tempo fa domani?") == [] and not asked          # gate: no model call at all
    nohub = FakeHub(registered=False)
    assert MoodCapture(nohub, lambda p: '{"mood": 2}').run("sono stanco") == [] and not nohub.calls


def test_undo_calls_the_module_and_notices():
    hub = FakeHub()
    sig = MoodCapture(hub, lambda p: "NONE").run("non segnarlo")
    assert hub.calls[0][1] == "/api/mood/capture/undo" and sig[0]["event"] == "mood.removed"


def test_notice_for_mood_signals():
    line = stream_emitter.emit_signal("mood.logged", "Umore segnato: 2/5 · stanco", {"detail": "2/5 · stanco"})
    assert '"kind": "mood.saved"' in line and "2/5" in line and '"icon": "smile"' in line
