"""Training dataset D1 «Registra» (docs/work/2026-10-30-dataset-allenamento). Markers: unit"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import Invalid, parse_dt

from app.core.traces import Traces, toolset_ref

pytestmark = pytest.mark.unit


class FakeDatasetArchive:
    """``dataset-store`` with the filters Metis uses (kind, parent_id, ref_id, at_to, order, limit) + chat meta."""

    def __init__(self, training_off=None):
        self.rows: dict = {}
        self.training_off = training_off or set()
        self.down = False

    def _live(self, q):
        kinds = set(str(q.get("kind") or "").split(",")) - {""}
        out = [r for r in self.rows.values() if not r.get("deleted")]
        if kinds:
            out = [r for r in out if r["kind"] in kinds]
        if q.get("parent_id"):
            out = [r for r in out if r.get("parent_id") == q["parent_id"]]
        if q.get("at_to"):
            out = [r for r in out if parse_dt(r["at"]) < parse_dt(q["at_to"])]
        if q.get("at_from"):
            out = [r for r in out if parse_dt(r["at"]) >= parse_dt(q["at_from"])]
        if q.get("order") == "-at":
            out.sort(key=lambda r: r["at"], reverse=True)
        return out[: int(q.get("limit") or 5000)]

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        assert service == "archive"
        if self.down:
            raise OSError("archive down")
        q = query or {}
        if path.startswith("api/chat/sessions/"):
            sid = path.split("/")[3]
            return {"session_id": sid, "training_off": sid in self.training_off}
        if path.endswith("/count"):
            return {"count": len(self._live({**q, "limit": 10**9}))}
        if method == "PUT":
            for r in body["rows"]:
                self.rows[(r["kind"], r["id"])] = dict(r)
            return {"applied": [], "stale": []}
        return {"rows": self._live(q)}


TOOLS = [{"name": "memory_save", "description": "Salva", "parameters": {"type": "object"}}]


def trace(tid="t1", sid="s1", user="Come si chiama mia mamma?", answer="Laura.", at=None, steps=None, tools=TOOLS):
    return {"trace_id": tid, "session_id": sid, "user": user, "answer": answer, "route": "agent",
            "at": (at or datetime.now(timezone.utc)).isoformat(), "system": "SYS", "history": "",
            "tools": tools, "steps": steps or [], "model": "m", "provider": "p"}


def test_trace_stored_with_toolset_once():
    arc = FakeDatasetArchive()
    t = Traces(arc)
    assert t.receive(trace("t1"))["stored"] is True
    t.receive(trace("t2", user="Altro"))
    kinds = [k for k, _ in arc.rows]
    assert kinds.count("toolset") == 1 and kinds.count("trace") == 2
    row = arc.rows[("trace", "t1")]
    assert row["parent_id"] == "s1"
    assert row["data"]["toolset_ref"] == toolset_ref(TOOLS) and "tools" not in row["data"]
    assert row["data"]["tool_names"] == ["memory_save"]


def test_missing_fields_rejected():
    with pytest.raises(Invalid):
        Traces(FakeDatasetArchive()).receive({"trace_id": "x", "session_id": "s"})


def test_training_off_session_is_never_stored():
    arc = FakeDatasetArchive(training_off={"s1"})
    out = Traces(arc).receive(trace())
    assert out == {"stored": False, "reason": "training_off"}
    assert not arc.rows


def test_meta_unknown_means_not_stored():
    arc = FakeDatasetArchive()
    arc.down = True
    t = Traces(arc)
    assert t.excluded("s1") is True


def test_rephrase_and_correction_signal_the_previous_turn():
    arc = FakeDatasetArchive()
    t = Traces(arc)
    now = datetime.now(timezone.utc)
    t.receive(trace("t1", user="Quanto ho speso questa settimana?", at=now))
    out = t.receive(trace("t2", user="no, quanto ho speso questa settimana in tutto?", at=now + timedelta(seconds=40)))
    assert set(out["signals"]) == {"rephrase", "correction"}
    sig = arc.rows[("signal", "t1:correction")]
    assert sig["ref_id"] == "t1" and sig["data"]["by_trace"] == "t2" and sig["data"]["weight"] < 0


def test_late_or_different_message_is_no_signal():
    arc = FakeDatasetArchive()
    t = Traces(arc)
    now = datetime.now(timezone.utc)
    t.receive(trace("t1", user="Che tempo fa domani?", at=now))
    assert t.receive(trace("t2", user="Segna una spesa di 10 euro", at=now + timedelta(seconds=30)))["signals"] == []
    assert t.receive(trace("t3", user="Segna una spesa di 10 euro!", at=now + timedelta(hours=2)))["signals"] == []


def test_failed_tool_is_a_signal_on_the_same_turn():
    arc = FakeDatasetArchive()
    out = Traces(arc).receive(trace(steps=[{"tool": "memory_save", "ok": False, "result": "errore"}]))
    assert out["signals"] == ["tool_failed"]
    assert arc.rows[("signal", "t1:tool_failed")]["data"]["tools"] == ["memory_save"]


def test_forget_session_wipes_traces_and_signals():
    arc = FakeDatasetArchive()
    t = Traces(arc)
    now = datetime.now(timezone.utc)
    t.receive(trace("t1", at=now, steps=[{"tool": "x", "ok": False}]))
    t.receive(trace("t9", sid="other"))
    assert t.forget_session("s1")["removed"] == 2
    gone = arc.rows[("trace", "t1")]
    assert gone["deleted"] is True and gone["data"] == {}
    assert not arc.rows[("trace", "t9")].get("deleted")


def test_prune_drops_old_rows_only():
    arc = FakeDatasetArchive()
    t = Traces(arc, keep_days=lambda: 30)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    t.receive(trace("old", at=old))
    t.receive(trace("new", user="altro"))
    assert t.prune() == 1
    assert arc.rows[("trace", "old")]["deleted"] and not arc.rows[("trace", "new")].get("deleted")


def test_status_and_recent_are_short():
    arc = FakeDatasetArchive()
    t = Traces(arc)
    t.receive(trace("t1", steps=[{"tool": "memory_save", "ok": True, "result": "x" * 500}]))
    st = t.status()
    assert st["traces"] == 1 and st["traces_7d"] == 1 and st["toolsets"] == 1 and st["last_at"]
    item = t.recent()[0]
    assert item["trace_id"] == "t1" and item["tools"] == ["memory_save"] and "system" not in item
