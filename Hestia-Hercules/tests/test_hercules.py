"""Hercules: engines (e1RM, progression, adaptation, goals, import) and the service over a fake Archive store.

Markers: unit
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core import adapt, catalog, domain, goals, importer, progression, records
from app.core.service import Conflict, Hercules
from app.core.store import Store, StoreUnavailable, parse_dt

pytestmark = pytest.mark.unit


class FakeArchive:
    """In-memory /api/hercules-store with the same LWW + seq semantics as Archive."""

    def __init__(self):
        self.rows, self.seq, self.down = {}, 0, False

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        assert service == "archive" and path == "api/hercules-store/records"
        if self.down:
            raise OSError("archive down")
        if method == "PUT":
            applied, stale = [], []
            for r in body["rows"]:
                key = (r["kind"], r["id"])
                old = self.rows.get(key)
                if old and parse_dt(old["updated_at"]) > parse_dt(r["updated_at"]):
                    stale.append(old)
                    continue
                self.seq += 1
                self.rows[key] = {**r, "seq": self.seq}
                applied.append({"kind": r["kind"], "id": r["id"], "seq": self.seq})
            return {"applied": applied, "stale": stale, "cursor": self.seq}
        since = int((query or {}).get("since_seq") or 0)
        rows = sorted((r for r in self.rows.values() if r["seq"] > since), key=lambda r: r["seq"])
        return {"rows": rows, "cursor": self.seq}


@pytest.fixture
def hc():
    store = Store(FakeArchive(), min_refresh_seconds=0)
    h = Hercules(store, lambda key: None, tz_name="Europe/Rome")
    h.ensure_catalog()
    return h


def _ex(h, slug):
    return h.store.data("exercise", catalog.exercise_id(slug))


def _template(h):
    bench, squat = _ex(h, "bench_press"), _ex(h, "back_squat")
    return h.save_template({"name": "Push A", "favorite": True, "items": [
        {"exercise_id": bench["id"], "sets": [{"reps_min": 6, "reps_max": 8, "weight_kg": 80}] * 3},
        {"exercise_id": squat["id"], "progression": "linear", "sets": [{"reps_min": 5, "reps_max": 5, "weight_kg": 100}] * 3},
    ]})


# ── engines ─────────────────────────────────────────────────────────────────
def test_e1rm_formulas():
    assert records.e1rm(100, 1) == 100
    assert round(records.e1rm(80, 8), 2) == 101.33
    assert records.e1rm(100, 5, "brzycki") == pytest.approx(112.5, rel=1e-3)
    assert records.e1rm(None, 5) is None


def test_plates_and_rounding():
    assert progression.round_to(81.3, 2.5) in (80.0, 82.5)
    p = progression.plates(100, 20, [25, 20, 15, 10, 5, 2.5, 1.25])
    assert p and isinstance(p, dict)


def test_catalog_ids_are_stable_and_unique():
    seed = catalog.seed()
    assert len(seed) >= 100
    assert len({e["id"] for e in seed}) == len(seed)
    assert catalog.exercise_id("bench_press") == catalog.exercise_id("bench_press")


def test_domain_rejects_set_without_session():
    with pytest.raises(domain.Invalid):
        domain.normalize("set", {"reps": 5})


# ── service ─────────────────────────────────────────────────────────────────
def test_catalog_seed_is_idempotent(hc):
    assert hc.ensure_catalog() == 0
    names = [e["name"] for e in hc.exercises(q="panca")[:3]]
    assert any("Panca" in n for n in names)


def test_live_session_prs_and_double_progression(hc):
    t = _template(hc)
    s = hc.start_session(t["id"])
    with pytest.raises(Conflict):
        hc.start_session(t["id"])
    block = s["blocks"][0]
    for _ in range(3):
        hc.log_set(s["id"], {"session_exercise_id": block["id"], "weight_kg": 80, "reps": 8})
    hc.log_sets_text(s["id"], "squat 100x5x3")
    done = hc.finish_session(s["id"])
    assert done["prs"] == [] or all(p.get("first") for p in done["prs"])
    detail = hc.template_detail(t["id"])
    sug = {it["exercise_id"]: it["suggestion"] for it in detail["items"]}
    bench_sets = sug[catalog.exercise_id("bench_press")]["sets"]
    assert bench_sets[0]["weight_kg"] == 82.5            # top of the range on every set → +2.5 kg
    assert sug[catalog.exercise_id("back_squat")]["sets"][0]["weight_kg"] == 102.5


def test_adaptation_for_pain_removes_pressing(hc):
    t = _template(hc)
    a = hc.adapt_today({"energy": 2, "time_minutes": 30, "pain_areas": ["spalla"]}, template_id=t["id"])
    names = [e.get("exercise_id") for e in a["exercises"] if not e.get("skipped")]
    assert catalog.exercise_id("bench_press") not in names
    assert a["minutes_after"] <= a["minutes_before"]
    assert a["warnings"] or a["trace"]


def test_quick_done_and_goal_progress(hc):
    t = _template(hc)
    hc.save("goal", {"times": 3, "per": "week", "scope": "any"})
    out = hc.quick_done(t["id"])
    assert out
    g = hc.goals()[0]
    assert g["progress"]["done"] == 1 and g["progress"]["remaining"] == 2


def test_sync_is_idempotent_and_last_write_wins(hc):
    sid = domain.new_id()
    now = datetime.now(timezone.utc)
    op = {"op_id": "o1", "kind": "measurement", "id": sid, "action": "upsert",
          "fields": {"kind": "bodyweight", "value": 80, "taken_at": now.isoformat()},
          "updated_at": now.isoformat(), "device_id": "phone"}
    first = hc.sync("phone", 0, [op])
    assert "o1" in first["applied"]
    again = hc.sync("phone", first["cursor"], [op])
    assert "o1" in again["applied"] and not again["rejected"]
    old = {**op, "op_id": "o2", "fields": {**op["fields"], "value": 70},
           "updated_at": (now - timedelta(hours=1)).isoformat()}
    late = hc.sync("tablet", 0, [old])
    assert hc.store.data("measurement", sid)["value"] == 80
    assert late["stale"] or "o2" in late["applied"]
    bad = hc.sync("phone", 0, [{"op_id": "o3", "kind": "nope", "id": "x", "action": "upsert", "fields": {}}])
    assert bad["rejected"]


def test_store_unavailable_keeps_mirror(hc):
    hc.store.hub.down = True
    assert hc.store.refresh(force=True) is False
    assert hc.exercises(q="squat")
    with pytest.raises(StoreUnavailable):
        hc.log_measurement("bodyweight", 80)


def test_strong_import_is_idempotent(hc):
    csv = ("Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE\n"
           "2026-09-01 18:00:00,Push,1h 0m,Bench Press (Barbell),1,80,8,0,0,,,\n"
           "2026-09-01 18:00:00,Push,1h 0m,Bench Press (Barbell),2,80,7,0,0,,,\n")
    pv = hc.import_preview(csv)
    assert pv["format"] == "strong" and pv["workouts"] == 1 and pv["sets"] == 2
    first = hc.import_commit(csv, {})
    second = hc.import_commit(csv, {})
    assert len(hc.store.items("session")) == 1
    assert first and second


def test_reminder_off_by_default(hc):
    assert hc.reminder_decision()["send"] is False


def test_reminder_once_a_day():
    cfg = {"hercules.reminder.enabled": True, "hercules.reminder.max_per_week": 3}
    h = Hercules(Store(FakeArchive(), min_refresh_seconds=0), cfg.get, tz_name="Europe/Rome")
    h.save("goal", {"times": 5, "per": "week"})
    if h.reminder_decision().get("why") == "on_track":
        pytest.skip("goal not behind on this weekday")
    assert h.reminder_decision()["send"] is True
    h.mark_reminder_sent()
    assert h.reminder_decision()["why"] == "sent_today"
