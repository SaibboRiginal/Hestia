"""Learning log with undo and memory review proposals (docs/work/2026-10-24-tutto-brainstorm-cindy W3,
Cindy 8 + 18). Archive and Oracle are an in-memory fake behind ``Learning._route``."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).parents[1] / "app"
_SHARED = Path(__file__).parents[2] / "Hestia-Shared"
for _p in (str(_APP), str(_SHARED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.learning import Learning  # noqa: E402


class _Fake:
    def __init__(self, memories, model_answer=""):
        self.store: dict = {}
        self.memories = {m["id"]: dict(m) for m in memories}
        self.model_answer = model_answer
        self.next_id = 100

    def __call__(self, service, method, path, body=None, query=None, timeout=10):
        if path.startswith("api/athena-store"):
            if method == "PUT":
                for r in body["rows"]:
                    self.store[(r["kind"], r["id"])] = r
                return 200, {}
            rows = [r for (k, _), r in self.store.items() if k == query["kind"]]
            return 200, {"rows": sorted(rows, key=lambda r: r["at"], reverse=True)}
        if path == "api/memory/active":
            return 200, [m for m in self.memories.values() if m["is_active"]]
        if path.startswith("api/memory/") and method == "GET":
            m = self.memories.get(int(path.rsplit("/", 1)[1]))
            return (200, m) if m else (404, None)
        if path.startswith("api/memory/") and method == "PATCH":
            self.memories[int(path.rsplit("/", 1)[1])].update(body)
            return 200, {}
        if path == "api/memory" and method == "POST":
            self.next_id += 1
            self.memories[self.next_id] = {"id": self.next_id, "fact": body["fact"], "is_active": True, "weight": 1.0}
            return 200, self.memories[self.next_id]
        if path == "api/llm/generate":
            return 200, {"response": self.model_answer}
        raise AssertionError(path)


def _learning(fake) -> Learning:
    learning = Learning("http://hub/api")
    learning._route = fake
    return learning


@pytest.mark.unit
def test_undo_restores_before_unless_the_owner_changed_it():
    fake = _Fake([{"id": 1, "fact": "Ama il caffè", "is_active": False, "weight": 1.0}])
    learning = _learning(fake)
    entry = learning.record("retire", 1, before={"is_active": True}, after={"is_active": False}, fact="x")
    status, _ = learning.undo(entry)
    assert status == 200 and fake.memories[1]["is_active"] is True
    assert learning.undo(entry)[0] == 409                     # already undone

    fake.memories[1]["weight"] = 0.3                          # the owner edited it meanwhile
    second = learning.record("decay", 1, before={"weight": 1.0}, after={"weight": 0.7})
    status, body = learning.undo(second)
    assert status == 409 and body["status"] == "changed_since" and fake.memories[1]["weight"] == 0.3


@pytest.mark.unit
def test_review_proposes_and_changes_nothing_until_applied():
    fake = _Fake([{"id": 1, "fact": "Vive a Torino", "is_active": True, "created_at": "2026-01-01"},
                  {"id": 2, "fact": "vive a Torino.", "is_active": True, "created_at": "2026-02-01"},
                  {"id": 3, "fact": "Vive a Milano", "is_active": True, "created_at": "2026-03-01"}],
                 model_answer='{"findings": [{"kind": "contraddizione", "keep": 3, "retire": [1], "why": "Città diverse"}]}')
    learning = _learning(fake)
    cards = []
    out = learning.review(lambda event, entity, payload: cards.append(payload))
    assert out["proposals"] >= 1 and all(m["is_active"] for m in fake.memories.values())
    assert cards[0]["_title"] == "Memoria · Doppione"
    pid = cards[0]["_actions"][0]["path"].split("/")[-2]
    assert pid in {p["id"] for p in learning.pending_proposals()}        # page «Cosa ho imparato»
    assert learning.apply(pid)[0] == 200 and fake.memories[2]["is_active"] is False
    assert learning.apply(pid)[0] == 409
    assert pid not in {p["id"] for p in learning.pending_proposals()}
    assert any(e["action"] == "retire" and e["memory_id"] == 2 for e in learning.log())
