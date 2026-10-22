"""«Mentre non c'ero» (docs/work/2026-10-19-oracle-offline v3 D): missed agenda runs redone, one message."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 10, 22, 9, 30, tzinfo=timezone.utc)


def _run(item, title, minutes_ago, status="failed", by="agenda", item_status="confirmed"):
    return {"item_id": item, "key": f"k.{item}", "title": title, "status": status, "by": by,
            "item_status": item_status, "at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


@pytest.fixture
def env(monkeypatch):
    from services import catchup
    sent, reran = [], []
    rows: list[dict] = []
    monkeypatch.setattr(catchup.agenda, "runs", lambda **kw: {"runs": rows})
    monkeypatch.setattr(catchup.agenda, "run_now", lambda ref, by="": reran.append((ref, by)) or {"ok": ref != 3})
    monkeypatch.setattr(catchup.hermes_client, "publish_event", lambda *a: sent.append(a) or True)
    monkeypatch.setattr(catchup, "_max_age_hours", lambda: 6)
    return catchup, rows, sent, reran


@pytest.mark.unit
def test_redo_recent_list_old_one_message(env):
    catchup, rows, sent, reran = env
    rows.extend([
        _run(1, "Recap del mattino", 90),
        _run(2, "Riflessione", 30, status="ok"),           # newest run fine → nothing to do
        _run(2, "Riflessione", 80),
        _run(3, "Spese dalle mail", 60),                    # redo fails again
        _run(4, "Pulizia vecchia", 8 * 60),                 # older than 6 h → only listed
        _run(5, "Manuale", 50, by="user"),                  # a user's manual run is not the agenda's miss
        _run(6, "In pausa", 40, item_status="paused"),      # a user decision
    ])
    out = catchup.run(NOW - timedelta(hours=9), NOW)
    assert reran == [(1, "catchup"), (3, "catchup")]
    assert out["redone"] == ["Recap del mattino"] and out["failed"] == ["Spese dalle mail"]
    assert out["too_old"] == ["Pulizia vecchia"]
    assert len(sent) == 1
    domain, event_type, entity, payload = sent[0]
    assert event_type == "service.action_required" and payload["_title"] == "Mentre non c'ero"
    assert "Recap del mattino" in payload["_message"] and "9 h" in payload["_message"]


@pytest.mark.unit
def test_nothing_missed_sends_nothing(env):
    catchup, rows, sent, reran = env
    rows.append(_run(1, "Recap", 30, status="ok"))
    out = catchup.run(NOW - timedelta(hours=1), NOW)
    assert sent == [] and reran == [] and out["redone"] == []
