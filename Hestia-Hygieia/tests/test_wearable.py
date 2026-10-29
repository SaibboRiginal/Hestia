"""Feed wearable.daily (Garmin via Hecate, W4 B10): the night's sleep in the diary, once per night. Markers: unit"""
import pytest

from .test_hygieia import hy  # noqa: F401 — fixture

pytestmark = pytest.mark.unit


def test_sleep_entry_per_night(hy):  # noqa: F811
    item = {"date": "2026-10-29", "sleep": {"minutes": 435, "deep_minutes": 90, "score": 82}}
    row = hy.sleep_from_wearable(item)
    assert row["area"] == "sonno" and row["scores"] == {"qualita": 5} and row["note"] == "7 h 15 min, profondo 90 min"
    hy.sleep_from_wearable({**item, "sleep": {"minutes": 400, "score": 50}})
    nights = [j for j in hy.items("journal") if j.get("area") == "sonno"]
    assert len(nights) == 1 and nights[0]["scores"] == {"qualita": 3}
    hy.delete_journal(row["id"])
    assert hy.sleep_from_wearable(item) is None                 # removed by the owner: never back
    assert hy.sleep_from_wearable({"date": "2026-10-30"}) is None
