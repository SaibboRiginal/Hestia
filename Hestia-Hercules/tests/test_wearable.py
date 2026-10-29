"""Feed wearable.daily (Garmin via Hecate, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4 B10): outdoor
activities logged once (also after a delete), morning check-in from the watch only without a hand-made one.
Markers: unit
"""
import pytest

from tests.test_activities import env  # noqa: F401 — fixture

pytestmark = pytest.mark.unit


def _item(h, **kw):
    return {"date": h.today().isoformat(), "source": "garmin", "sleep": {"score": 82}, "body_battery": {"morning": 45},
            "readiness": 64, "activities": [
                {"id": "991", "kind": "corsa", "start": f"{h.today().isoformat()} 07:10:00", "minutes": 30, "km": 5.1,
                 "name": "Corsa mattutina"},
                {"id": "992", "kind": "forza", "start": f"{h.today().isoformat()} 18:00:00", "minutes": 50}], **kw}


def test_activities_logged_once(env):  # noqa: F811
    h, _, _, acts = env
    assert len(acts.from_wearable(_item(h))) == 1              # strength stays with the gym sessions
    assert acts.from_wearable(_item(h)) == []
    row = next(a for a in h.store.items("activity") if a.get("ext") == "garmin:991")
    assert row["km"] == 5.1 and row["source"] == "device"
    acts.unlog(row["id"])
    assert acts.from_wearable(_item(h)) == []                  # removed by the owner: never back


def test_checkin_from_watch_yields_to_the_owner(env):  # noqa: F811
    h, _, _, _ = env
    row = h.checkin_from_wearable(_item(h))
    assert row["sleep"] == 5 and row["energy"] == 3 and row["source"] == "device"
    h.checkin({"energy": 2, "sleep": 2})
    assert h.checkin_from_wearable(_item(h)) is None
    assert h.checkin_from_wearable({**_item(h), "date": "2020-01-01"}) is None
