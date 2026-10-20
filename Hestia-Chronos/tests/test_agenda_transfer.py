"""Export / import of the user's agenda: own items and edited module rules travel, defaults and run state don't.
Archive mocked in memory. SPEC docs/work/2026-10-20-import-export."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


def _row(key, owner, created_by, *, modified=False, status="confirmed", at="2026-10-10T10:00:00+00:00", title=None):
    return {"id": key, "external_id": key, "title": title or key, "start_at": "2026-10-01T08:00:00+00:00",
            "recurrence": "RRULE:FREQ=DAILY", "status": status, "kind": "job", "updated_at": at,
            "meta": {"type": "job", "owner": owner, "created_by": created_by, "user_modified": modified,
                     "runs": [{"at": "x"}], "attempts": 2, "action": {"service": owner, "path": "/api/x"}}}


def _agenda(rows):
    from services import agenda as A
    store = {r["external_id"]: r for r in rows}

    def route(method, path, body=None, query=None, timeout=10):
        if method == "GET":
            return list(store.values())
        store[body["external_id"]] = {**body, "id": body["external_id"], "updated_at": "2026-10-20T10:00:00+00:00"}
        return store[body["external_id"]]

    return patch.object(A.archive_client, "_route_archive", side_effect=route), store


@pytest.mark.unit
def test_agenda_export_and_import():
    from hestia_common.transfer import Transfer
    from services.agenda_transfer import AgendaSection
    cloud_rows = [_row("scout.email_cycle", "scout", "scout"),                       # module default: stays home
                  _row("hercules.reminder", "hercules", "hercules", modified=True),  # user moved it
                  _row("user:abc", "user", "user", title="Palestra")]
    p, _ = _agenda(cloud_rows)
    with p:
        t = Transfer("chronos", sections=[AgendaSection()])
        data = json.loads(json.dumps(t.export()))
    recs = data["sections"]["agenda"]["records"]
    assert sorted(r["key"] for r in recs) == ["hercules.reminder", "user:abc"]
    assert all("runs" not in r and "attempts" not in r for r in recs)

    home_rows = [_row("hercules.reminder", "hercules", "hercules", at="2026-10-01T10:00:00+00:00"),
                 _row("user:old", "user", "user", at="2026-10-01T10:00:00+00:00")]
    p, home = _agenda(home_rows)
    with p:
        t = Transfer("chronos", sections=[AgendaSection()])
        r = t.import_(data, mode="replace", dry_run=False)["sections"]["agenda"]
    assert (r["added"], r["deleted"]) == (2, 1)        # hercules rule is not «mine» at home yet → added as mine
    assert home["hercules.reminder"]["meta"]["user_modified"] is True
    assert home["hercules.reminder"]["meta"]["attempts"] == 2          # run state of home kept
    assert home["user:abc"]["title"] == "Palestra"
    assert home["user:old"]["status"] == "cancelled"
