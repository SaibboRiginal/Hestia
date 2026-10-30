"""Training dataset D2 «Correggi» (docs/work/2026-10-30-dataset-allenamento §3.3). Markers: unit"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import Invalid

from app.core.review import Masker, Review, parse_verdict
from app.core.traces import Traces
from tests.test_traces import FakeDatasetArchive, trace

pytestmark = pytest.mark.unit


class Archive(FakeDatasetArchive):
    """Adds ``ids`` / ``ref_id`` filters, Archive feedback and Hera people."""

    def __init__(self, votes=None, people=("Laura Rossi",)):
        super().__init__()
        self.votes = votes or []
        self.people = list(people)

    def _live(self, q):
        out = super()._live(q)
        if q.get("ids"):
            ids = set(q["ids"].split(","))
            out = [r for r in out if r["id"] in ids]
        if q.get("ref_id"):
            out = [r for r in out if r.get("ref_id") == q["ref_id"]]
        if q.get("order") == "at":
            out.sort(key=lambda r: r["at"] or "")
        return out

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        if service == "hera":
            return {"items": [{"name": n} for n in self.people]}
        if path == "api/feedback":
            return [v for v in self.votes if v.get("session_id") == (query or {}).get("session_id")]
        return super().ok(service, method, path, body=body, query=query, timeout=timeout)


class Teacher:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def __call__(self, prompt, **kw):
        self.prompts.append((prompt, kw))
        return self.answer if isinstance(self.answer, str) or self.answer is None else json.dumps(self.answer)


OLD = datetime.now(timezone.utc) - timedelta(hours=2)


def seed(arc, **kw):
    Traces(arc).receive(trace(at=OLD, **kw))


def test_masker_hides_people_contacts_and_puts_them_back():
    m = Masker(["Laura Rossi"])
    text = m.mask("Laura vive in via Roma 12, scrivile a laura@x.it o +39 333 123 4567; IBAN IT60X0542811101000000123456")
    for real in ("Laura", "via Roma 12", "laura@x.it", "333 123 4567", "IT60X0542811101000000123456"):
        assert real not in text
    assert "<PERSONA_1>" in text and "<EMAIL_1>" in text and "<TEL_1>" in text and "<IBAN_1>" in text
    assert m.unmask("Ciao <PERSONA_1>") == "Ciao Laura"
    assert m.mask({"a": ["Laura"]}) == {"a": ["<PERSONA_1>"]}       # same value, same placeholder


@pytest.mark.parametrize("raw,ok", [
    ('{"verdict":"keep","confidence":0.9}', True),
    ('```json\n{"verdict":"fix","confidence":0.8,"answer":"Sì."}\n```', True),
    ('{"verdict":"maybe"}', False), ("non json", False), (None, False),
])
def test_parse_verdict(raw, ok):
    assert (parse_verdict(raw, 2) is not None) is ok


def test_fix_without_anything_to_apply_goes_to_the_owner():
    v = parse_verdict('{"verdict":"fix","confidence":0.99,"remove_steps":[7]}', 2)
    assert v["remove_steps"] == [] and v["needs_owner"] is True


def test_nothing_personal_leaves_and_sure_fix_is_accepted():
    arc = Archive()
    seed(arc, user="Mia mamma si chiama Laura Rossi", answer="Ho salvato Laura in Persone e in memoria.",
         steps=[{"tool": "people_save", "params": {"name": "Laura Rossi"}, "ok": True, "result": "ok"},
                {"tool": "memory_save", "params": {"fact": "mamma Laura Rossi"}, "ok": True, "result": "ok"}])
    teacher = Teacher({"verdict": "fix", "confidence": 0.95, "answer": "Ho salvato <PERSONA_1> in Persone.",
                       "remove_steps": [1], "reasons": ["R3"]})
    out = Review(arc, llm=teacher).run()
    assert out["reviewed"] == 1 and out["accepted"] == 1
    prompt, kw = teacher.prompts[0]
    assert "Laura" not in prompt and "<PERSONA_1>" in prompt and kw["use_case"] == "metis.dataset.review"
    rev = arc.rows[("review", "t1")]
    assert rev["ref_id"] == "accepted" and rev["data"]["answer"] == "Ho salvato Laura Rossi in Persone."
    assert rev["data"]["remove_steps"] == [1]


def test_unsure_or_voted_down_waits_for_owner_then_owner_wins():
    arc = Archive(votes=[{"session_id": "s1", "interaction_id": "t1", "quality_label": "poor",
                          "feedback_text": "troppo lunga"}])
    seed(arc)
    Review(arc, llm=Teacher({"verdict": "keep", "confidence": 0.99})).run()
    rev = arc.rows[("review", "t1")]
    assert rev["ref_id"] == "pending"
    assert {"type": "vote", "label": "poor", "text": "troppo lunga"} in rev["data"]["signals"]
    r = Review(arc, llm=Teacher(None))
    item = r.pending()["items"][0]
    assert item["trace_id"] == "t1" and item["user"]
    assert r.decide("t1", "edit", "Laura.")["status"] == "edited"
    assert arc.rows[("review", "t1")]["data"]["answer"] == "Laura." and r.pending()["items"] == []
    with pytest.raises(Invalid):
        r.decide("t1", "boh")


def test_teacher_away_stops_and_next_run_resumes():
    arc = Archive()
    seed(arc)
    assert Review(arc, llm=Teacher(None)).run() == {"reviewed": 0, "failed": 1, "accepted": 0, "pending": 0,
                                                     "rejected": 0, "edited": 0}
    assert ("review", "t1") not in arc.rows
    assert Review(arc, llm=Teacher({"verdict": "keep", "confidence": 0.9})).run()["accepted"] == 1
    assert Review(arc, llm=Teacher({"verdict": "keep", "confidence": 0.9})).run()["reviewed"] == 0


def test_fresh_turns_wait_and_no_people_means_no_run():
    arc = Archive()
    Traces(arc).receive(trace())            # just now: the next turns may still signal it
    assert Review(arc, llm=Teacher({"verdict": "keep", "confidence": 1})).run()["reviewed"] == 0

    class Down(Archive):
        def ok(self, service, *a, **kw):
            if service == "hera":
                raise OSError("hera down")
            return super().ok(service, *a, **kw)
    arc2 = Down()
    seed(arc2)
    teacher = Teacher({"verdict": "keep", "confidence": 1})
    assert Review(arc2, llm=teacher).run()["skipped"] == "people_unavailable" and not teacher.prompts
