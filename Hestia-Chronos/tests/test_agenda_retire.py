"""Modules retire default rules they no longer declare (Scout's mail poll → push). Archive mocked in memory.
SPEC docs/work/2026-10-19-email-push-spese §3.3."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _row(key, owner, created_by, status="confirmed"):
    return {"id": key, "external_id": key, "title": key, "start_at": "2026-10-01T00:00:00+00:00",
            "recurrence": "RRULE:FREQ=MINUTELY;INTERVAL=30", "status": status, "kind": "job",
            "meta": {"type": "job", "owner": owner, "created_by": created_by, "params": {"interval_seconds": 1800},
                     "action": {"service": owner, "path": "/api/scout/cycle"}}}


@pytest.fixture
def agenda():
    from services import agenda as A
    rows = {r["external_id"]: r for r in [_row("scout.email_cycle", "scout", "scout"),
                                          _row("scout.mine", "scout", "user"),
                                          _row("hermes.retract", "hermes", "hermes")]}

    def route(method, path, body=None, query=None, timeout=10):
        if method == "GET":
            return list(rows.values())
        rows[body["external_id"]] = {**body, "id": body["external_id"]}
        return rows[body["external_id"]]

    with patch.object(A.archive_client, "_route_archive", side_effect=route):
        yield A, rows


@pytest.mark.unit
def test_retire_only_module_rules(agenda):
    A, rows = agenda
    assert A.retire_rules("scout", ["scout.email_cycle", "scout.mine", "hermes.retract"]) == ["scout.email_cycle"]
    assert rows["scout.email_cycle"]["status"] == "cancelled"
    assert rows["scout.email_cycle"]["meta"]["params"]["retired_by_module"] is True
    assert rows["scout.mine"]["status"] == "confirmed"          # the user's own item stays
    assert rows["hermes.retract"]["status"] == "confirmed"      # another module's rule stays
    assert A.retire_rules("scout", ["scout.email_cycle"]) == []  # idempotent


@pytest.mark.api
def test_retire_endpoint(agenda):
    from fastapi.testclient import TestClient
    import main
    r = TestClient(main.app).post("/api/agenda/retire", json={"owner": "scout", "keys": ["scout.email_cycle"]})
    assert r.status_code == 200 and r.json()["retired"] == ["scout.email_cycle"]
