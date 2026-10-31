"""«Annulla riparazione» does something real: stops a repair that never ran, asks the target module
to restore what it changed, and says so when there is nothing to restore (docs/work/2026-10-30-cose-aperte)."""
from __future__ import annotations

import logging

import pytest


@pytest.fixture
def svc(monkeypatch):
    from app.core import remediation_service as rs

    monkeypatch.setattr(rs.fs, "get_bool", lambda *_a, **_k: False)  # no approval gate in these tests
    s = rs.RemediationService(logger=logging.getLogger("t"), hub_api_url="http://hub/api", notify_target="owner",
                              baseline_ref="main", maintenance_paths=["/api/module/maintenance/reconcile"])
    s.calls = []
    s.replies = {}

    def _route(*, service, path, body):
        s.calls.append((service, path, body))
        return s.replies.get(path, (True, {}))

    monkeypatch.setattr(s, "_route_through_hub", _route)
    monkeypatch.setattr(s, "_notify_change", lambda **_k: None)
    return s


def _run(svc, *, dry_run=False, undo_available=True):
    from app.core.models import RemediationRequest
    from app.core.runbooks import RUNBOOKS

    svc.replies["/api/module/maintenance/reconcile"] = (
        True, {"mutation_count": 2, "details": {"undo_available": undo_available}})
    req = RemediationRequest(service="archive", issue="entita incomplete", dry_run=dry_run)
    return svc.create_task(req, RUNBOOKS["rbk_service_health_triage"])


def _undo(svc, task_id):
    from app.core.models import RemediationRollbackRequest
    return svc.rollback_task(task_id, RemediationRollbackRequest(requested_by="marko"))


@pytest.mark.unit
def test_undo_asks_the_module_to_restore(svc):
    task = _run(svc)
    assert task["state"] == "succeeded" and task["undoable"] is True
    out = _undo(svc, task["task_id"])
    assert out["state"] == "rolled_back" and out["rollback_result"]["status"] == "restored"
    service, path, body = svc.calls[-1]
    assert (service, path, body["task_id"]) == ("archive", "/api/module/maintenance/undo", task["task_id"])
    # a second «annulla» does not restore twice
    assert _undo(svc, task["task_id"]) is out and len(svc.calls) == 2


@pytest.mark.unit
def test_nothing_restorable_is_said_not_faked(svc):
    task = _run(svc, undo_available=False)
    out = _undo(svc, task["task_id"])
    assert out["state"] == "succeeded" and out["rollback_result"]["status"] == "nothing_to_undo"
    assert len(svc.calls) == 1  # only the reconcile, no undo call


@pytest.mark.unit
def test_dry_run_is_never_undoable(svc):
    task = _run(svc, dry_run=True)
    assert task["undoable"] is False
    assert _undo(svc, task["task_id"])["rollback_result"]["status"] == "nothing_to_undo"


@pytest.mark.unit
def test_failed_restore_keeps_the_repair_undoable(svc):
    task = _run(svc)
    svc.replies["/api/module/maintenance/undo"] = (False, {"error": "service_status_500"})
    out = _undo(svc, task["task_id"])
    assert out["state"] == "succeeded" and out["undoable"] is True
    assert out["rollback_result"]["status"] == "failed"


@pytest.mark.unit
def test_failed_repair_is_stopped(svc):
    task = _run(svc)
    task["state"] = "failed"
    out = _undo(svc, task["task_id"])
    assert out["state"] == "rolled_back" and out["rollback_result"]["status"] == "cancelled"
