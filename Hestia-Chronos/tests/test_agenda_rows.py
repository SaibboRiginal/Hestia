"""Agenda rows (core review 2026-11-27).

- Finished one-offs (history) are left out by the Archive query itself: ordered by start, they used to push new tasks
  past the row limit, so those tasks never fired.
- The hourly re-assert of an unchanged module rule writes nothing, and never puts back an old ``last_fired``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _row(key, *, status="confirmed", last_fired=None):
    return {"id": key, "external_id": key, "title": key, "start_at": "2026-01-01T00:00:00+00:00",
            "recurrence": "RRULE:FREQ=HOURLY", "status": status, "kind": "job",
            "meta": {"type": "job", "owner": "scout", "created_by": "scout", "params": {},
                     "action": {"service": "scout", "path": "/api/scout/cycle"}, "last_fired": last_fired}}


@pytest.fixture
def store():
    from services import agenda as A
    rows = {"scout.cycle": _row("scout.cycle", last_fired="2026-11-27T10:00:00+00:00"),
            "old.task": _row("old.task", status="completed")}
    calls: list = []

    def route(method, path, body=None, query=None, timeout=10):
        calls.append((method, path, dict(query or {}), body))
        if method == "GET":
            out = list(rows.values())
            skip = set(filter(None, str((query or {}).get("exclude_statuses") or "").split(",")))
            keys = set(filter(None, str((query or {}).get("external_ids") or "").split(",")))
            return [r for r in out if r["status"] not in skip and (not keys or r["external_id"] in keys)]
        rows[body["external_id"]] = {**body, "id": body["external_id"]}
        return rows[body["external_id"]]

    with patch.object(A.archive_client, "_route_archive", side_effect=route):
        yield A, rows, calls


@pytest.mark.unit
def test_live_items_exclude_finished_in_the_query(store):
    A, _rows, calls = store
    assert [i["key"] for i in A.list_items()] == ["scout.cycle"]
    query = calls[-1][2]
    assert query["exclude_statuses"] == "cancelled,completed" and query["limit"] >= 5000


@pytest.mark.unit
def test_get_finds_a_finished_item_by_key(store):
    A, _rows, _calls = store
    assert A.get("old.task")["status"] == "completed"


@pytest.mark.unit
def test_unchanged_rule_is_not_rewritten(store):
    A, rows, calls = store
    rule = {"key": "scout.cycle", "type": "job", "title": "scout.cycle", "start_at": "2026-01-01T00:00:00+00:00",
            "recurrence": "FREQ=HOURLY", "action": {"service": "scout", "path": "/api/scout/cycle"}, "params": {}}
    A.register_rules("scout", [rule])
    assert not [c for c in calls if c[0] == "POST"]
    assert rows["scout.cycle"]["meta"]["last_fired"] == "2026-11-27T10:00:00+00:00"
