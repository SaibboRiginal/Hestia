"""Export / import of long-term memory: matched by class + fact, chats never travel.
SPEC docs/work/2026-10-20-import-export."""
from __future__ import annotations

import json

import pytest

from core.services.memory_transfer import MemorySection, memory_key
from hestia_common.transfer import Transfer


class FakeArchive:
    def __init__(self, rows):
        self.rows = {r["id"]: r for r in rows}

    def route(self, method, endpoint, body=None, query=None, timeout=6):
        if method == "GET":
            return [r for r in self.rows.values() if r["is_active"]]
        if method == "POST":
            rid = max(self.rows or [0]) + 1
            self.rows[rid] = {"id": rid, "is_active": True, "updated_at": "2026-10-20T10:00:00+00:00", **body}
            return self.rows[rid]
        rid = int(endpoint.rsplit("/", 1)[1])
        self.rows[rid].update({k: v for k, v in body.items() if v is not None})
        return self.rows[rid]


def _mem(id, fact, cls="durable_user_preference", at="2026-10-10T10:00:00+00:00", weight=1.0):
    return {"id": id, "fact": fact, "memory_class": cls, "domain": "general", "weight": weight, "is_active": True,
            "updated_at": at, "embedding": [0.1] * 4}


@pytest.mark.unit
def test_memory_roundtrip_by_fact():
    cloud = FakeArchive([_mem(1, "Preferisce il caffè amaro"), _mem(2, "ciao", cls="conversational_history"),
                         _mem(3, "Si allena il lunedì", weight=2.0)])
    data = json.loads(json.dumps(Transfer("oracle", sections=[MemorySection(cloud.route)]).export()))
    recs = data["sections"]["memorie"]["records"]
    assert len(recs) == 2 and all("embedding" not in r for r in recs)     # no chats, no vectors
    home = FakeArchive([_mem(7, "preferisce  il caffè AMARO"),            # same fact, other id and spacing
                        _mem(8, "Vive a Torino", at="2026-10-01T10:00:00+00:00")])
    t = Transfer("oracle", sections=[MemorySection(home.route)])
    r = t.import_(data, mode="replace", dry_run=False)["sections"]["memorie"]
    assert (r["added"], r["unchanged"], r["deleted"]) == (1, 1, 1)
    assert home.rows[8]["is_active"] is False
    assert any(x["fact"] == "Si allena il lunedì" and x["extra_data"]["imported"] for x in home.rows.values())
    assert memory_key("x", "A  b") == memory_key("x", "a b")
