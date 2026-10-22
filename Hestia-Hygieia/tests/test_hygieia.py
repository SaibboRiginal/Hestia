"""Hygieia: planner (goals, conflicts, pauses), products lifecycle, routine versions, logs, alerts, reminders.

Service over a fake Archive store (same LWW + seq semantics as /api/selfcare-store). Markers: unit
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core import catalog
from app.core.planner import goal_state, norm_cadence, period_start
from app.core.service import Conflict, Hygieia, Invalid, NotFound
from app.core.store import Store, StoreUnavailable, parse_dt

pytestmark = pytest.mark.unit


class FakeArchive:
    def __init__(self):
        self.rows, self.seq, self.down = {}, 0, False

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        assert service == "archive" and path == "api/selfcare-store/records"
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


SETTINGS: dict = {}


@pytest.fixture
def hy():
    return Hygieia(Store(FakeArchive(), min_refresh_seconds=0), SETTINGS.get, tz_name="Europe/Rome")


def _evening(h):
    cl = h.save_product({"name": "Detergente", "brand": "CeraVe", "category": "detergente"})
    ret = h.save_product({"name": "Retinolo 0.3", "brand": "TO", "actives": ["retinolo"]})
    aha = h.save_product({"name": "Tonico glicolico", "actives": [{"name": "aha_glicolico", "percent": 7}]})
    r = h.save_routine({"name": "Viso sera", "slot": "evening", "cadence": {"mode": "daily"}, "steps": [
        {"product_id": cl["id"]},
        {"product_id": ret["id"], "cadence": {"mode": "target", "times": 3, "per": "week"}},
        {"product_id": aha["id"], "cadence": {"mode": "target", "times": 1, "per": "week"}}]})
    return r, cl, ret, aha


# ── planner ───────────────────────────────────────────────────────────────────
def test_goal_state_target_behind_and_spacing():
    monday = date(2026, 10, 12)
    g = goal_state({"mode": "target", "times": 2, "per": "week"}, [], monday)
    assert g["state"] == "suggested" and g["hint"] == "0/2 sett." and not g["behind"]
    sunday = monday + timedelta(days=6)
    assert goal_state({"mode": "target", "times": 1}, [], sunday)["state"] == "due"
    # 3/week done yesterday → wait (every other day)
    assert goal_state({"mode": "target", "times": 3}, [monday], monday + timedelta(days=1))["state"] == "wait"
    assert goal_state({"mode": "target", "times": 1}, [monday], monday + timedelta(days=2))["state"] == "ok"


def test_goal_state_modes():
    d = date(2026, 10, 14)  # Wednesday
    assert goal_state({"mode": "daily"}, [], d)["state"] == "due"
    assert goal_state({"mode": "fixed_days", "days": [2]}, [], d)["state"] == "due"
    assert goal_state({"mode": "fixed_days", "days": [0]}, [], d)["state"] == "off"
    assert goal_state({"mode": "as_needed"}, [], d)["state"] == "rest"
    assert norm_cadence({"mode": "bogus"})["mode"] == "target"
    assert period_start(d, "week") == date(2026, 10, 12) and period_start(d, "month") == date(2026, 10, 1)


def test_conflicting_steps_alternate(hy):
    r, _, ret, aha = _evening(hy)
    steps = {s["label"]: s for s in r["plan"]["steps"]}
    assert steps["Retinolo 0.3"]["include"] is not steps["Tonico glicolico"]["include"]
    excluded = steps["Tonico glicolico"] if steps["Retinolo 0.3"]["include"] else steps["Retinolo 0.3"]
    assert excluded["reason"].startswith("non oggi")
    assert any("alterna" in n["text"] for n in r["check"])


def test_after_a_retinol_evening_the_aha_says_not_today(hy):
    """Bench run 2026-10-19: once the retinol step was done, the AHA step went back to «suggested» the same evening."""
    r, _, ret, aha = _evening(hy)
    hy.log_routine(r["id"], None, "done", None, "")
    plan = hy.routine_plan(r["id"])
    steps = {s["label"]: s for s in plan["steps"]}
    done = "Retinolo 0.3" if steps["Retinolo 0.3"]["done"] else "Tonico glicolico"
    other = "Tonico glicolico" if done == "Retinolo 0.3" else "Retinolo 0.3"
    assert steps[done]["include"] and steps[done]["done"]
    assert not steps[other]["include"] and steps[other]["reason"] == f"non oggi: {done}"
    # another evening routine the same day names the product that clashes, not a generic «conflitto»
    r2 = hy.save_routine({"name": "Viso sera bis", "cadence": {"mode": "daily"}, "steps": [
        {"product_id": ret["id"] if done == "Tonico glicolico" else aha["id"], "cadence": {"mode": "target", "times": 3}}]})
    assert hy.routine_plan(r2["id"])["steps"][0]["reason"] == f"non oggi: {done}"


def test_step_pause(hy):
    r, _, ret, _ = _evening(hy)
    steps = [dict(s) for s in hy.get("routine", r["id"])["steps"]]
    steps[1]["paused_until"] = (hy.today() + timedelta(days=7)).isoformat()
    d = hy.save_routine({"steps": steps}, id=r["id"], reason="irritazione")
    st = next(s for s in d["plan"]["steps"] if s["label"] == "Retinolo 0.3")
    assert not st["include"] and st["state"] == "paused"
    assert d["version"] == 2 and d["versions"][0]["reason"] == "irritazione"


def test_routines_not_same_day_from_actives(hy):
    ret = hy.save_product({"name": "Retinale", "actives": ["retinale"]})
    bha = hy.save_product({"name": "BHA 2%", "actives": ["bha_salicilico"]})
    a = hy.save_routine({"name": "Notte retinoide", "cadence": {"mode": "target", "times": 3}, "steps": [{"product_id": ret["id"]}]})
    b = hy.save_routine({"name": "Notte esfoliante", "cadence": {"mode": "target", "times": 1}, "steps": [{"product_id": bha["id"]}]})
    hy.log_routine(a["id"])
    plan = {p["name"]: p for p in hy.plan()["routines"]}
    assert plan["Notte esfoliante"]["state"] == "blocked" and "Notte retinoide" in plan["Notte esfoliante"]["reason"]


# ── logs ──────────────────────────────────────────────────────────────────────
def test_log_once_per_day_and_undo(hy):
    r, *_ = _evening(hy)
    out = hy.log_routine(r["id"])
    assert out["status"] == "done" and all(s["done"] for s in out["steps"])
    with pytest.raises(Conflict):
        hy.log_routine(r["id"])
    assert hy.plan()["routines"][0]["state"] == "done"
    hy.undo_log(routine_id=r["id"])
    assert hy.plan()["routines"][0]["state"] == "due"
    with pytest.raises(NotFound):
        hy.undo_log(routine_id=r["id"])


def test_partial_log_and_product_uses(hy):
    r, cl, ret, aha = _evening(hy)
    included = [s["step_id"] for s in r["plan"]["steps"] if s["include"]]
    out = hy.log_routine(r["id"], steps=included[:1])
    assert out["status"] == "partial"
    assert hy.product_detail(cl["id"])["uses"] == 1
    hy.log_product(aha["id"])
    assert hy.product_detail(aha["id"])["uses"] == 1


def test_skipped_does_not_count(hy):
    r = hy.save_routine({"name": "Maschera", "cadence": {"mode": "target", "times": 1}, "steps": [{"label": "maschera"}]})
    hy.log_routine(r["id"], status="skipped")
    assert hy.routine_stats(hy.get("routine", r["id"]))["total"] == 0


# ── products ──────────────────────────────────────────────────────────────────
def test_product_lifecycle_events_and_expiry(hy):
    p = hy.save_product({"name": "Siero", "status": "stock", "pao_months": 6})
    assert p["opened_at"] is None and p["expiry"] is None
    p = hy.set_status(p["id"], "in_use")
    assert p["opened_at"] == hy.today().isoformat() and 175 <= p["expires_in"] <= 190
    p = hy.set_status(p["id"], "finished")
    types = [e["type"] for e in hy.product_detail(p["id"])["events"]]
    assert "opened" in types and "finished" in types and "bought" in types
    with pytest.raises(Invalid):
        hy.save_product({"name": ""})
    with pytest.raises(Invalid):
        hy.save_product({"name": "x", "status": "boh"})


def test_repurchase_and_finish_estimate(hy):
    old = hy.save_product({"name": "Crema", "brand": "CeraVe", "opened_at": (hy.today() - timedelta(days=100)).isoformat()})
    hy.save_product({"status": "finished", "finished_at": (hy.today() - timedelta(days=10)).isoformat()}, id=old["id"])
    new = hy.save_product({"name": "Crema", "brand": "CeraVe", "opened_at": (hy.today() - timedelta(days=80)).isoformat()})
    fe = hy.product_detail(new["id"])["finish_estimate"]
    assert fe and fe["days_left"] == 10
    again = hy.repurchase(new["id"])
    assert again["status"] == "stock" and again["product_key"] == new["product_key"]


def test_alerts_and_shopping(hy):
    p = hy.save_product({"name": "Shampoo", "level": "almost_empty"})
    exp = hy.save_product({"name": "SPF", "opened_at": (hy.today() - timedelta(days=360)).isoformat(), "pao_months": 12})
    types = {(a["type"], a["product_id"]) for a in hy.alerts()}
    assert ("restock", p["id"]) in types and ("expiry", exp["id"]) in types
    assert hy.shopping()["count"] >= 1
    hy.repurchase(p["id"])
    assert not any(a["type"] == "restock" and a["product_id"] == p["id"] for a in hy.alerts())


# ── versions, history, assistant ──────────────────────────────────────────────
def test_versions_undo_timeline_period(hy):
    r, cl, ret, aha = _evening(hy)
    hy.save_routine({"steps": [{"product_id": cl["id"]}]}, id=r["id"], reason="pausa attivi")
    assert hy.get("routine", r["id"])["version"] == 2
    hy.save_routine({"name": "Viso sera!"}, id=r["id"])          # no step change → no new version
    assert hy.get("routine", r["id"])["version"] == 2
    d = hy.undo_routine(r["id"])
    assert d["version"] == 3 and len(d["steps"]) == 3
    assert any(t["type"] == "version" and "pausa attivi" in t["text"] for t in hy.timeline())
    assert hy.period(hy.today().isoformat())["routines"][0]["version"] == 3


def test_summary_and_context(hy):
    _evening(hy)
    assert "Viso sera" in hy.summary()["text"]
    assert hy.context_text(60).endswith("…") or len(hy.context_text(60)) <= 60
    ov = hy.overview()
    assert ov["routines"][0]["steps"][1].startswith("Retinolo") and "[Almeno 3" in ov["routines"][0]["steps"][1]


def test_journal(hy):
    hy.journal_add({"entries": [{"area": "viso", "scores": {"brufoli": 2}}, {"area": "capelli", "scores": {"caduta": 3}}]})
    j = hy.journal()
    assert len(j["items"]) == 2 and j["series"]["viso"]["brufoli"][0]["value"] == 2
    with pytest.raises(Invalid):
        hy.journal_add({"area": "viso", "scores": {"brufoli": 9}})


# ── reminders, quick ──────────────────────────────────────────────────────────
def test_reminders_weekly_limit_and_snooze(hy, monkeypatch):
    monkeypatch.setitem(SETTINGS, "hygieia.reminder.enabled", True)   # common switch, off by default
    r = hy.save_routine({"name": "Maschera", "cadence": {"mode": "daily"}, "reminder": True, "steps": [{"label": "maschera"}]})
    d = hy.reminder_decisions()
    assert d[0]["send"]
    hy.mark_reminder_sent(r["id"])
    assert hy.reminder_decisions()[0]["why"] == "sent_today"
    hy.snooze_routine(r["id"])
    row = hy.store.data("reminder", r["id"])
    assert row["silenced_until"] > hy.today().isoformat()


def test_reminder_off_by_default(hy):
    hy.save_routine({"name": "Corpo", "cadence": {"mode": "daily"}, "steps": [{"label": "crema"}]})
    assert hy.reminder_decisions() == []


def test_quick_chips(hy):
    r = hy.save_routine({"name": "Viso mattina", "favorite": True, "cadence": {"mode": "daily"}, "steps": [{"label": "acqua"}]})
    chips = hy.quick_routines()
    assert chips[0]["id"] == r["id"] and chips[0]["state"] in ("todo", "late")
    hy.log_routine(r["id"])
    assert hy.quick_routines()[0]["state"] == "done"


def test_options_and_find(hy):
    hy.add_option("actives", {"label": "Acido tranexamico", "family": ""})
    assert any(a["value"] == "acido_tranexamico" for a in hy.options("actives"))
    hy.save_product({"name": "Siero Vitamina C", "brand": "Garnier"})
    assert hy.find_product("vitamina c")["name"] == "Siero Vitamina C"
    assert catalog.product_key("CeraVe", "Crème") == "cerave_creme"


def test_store_unavailable(hy):
    hy.store.hub.down = True
    with pytest.raises(StoreUnavailable):
        hy.save_product({"name": "x"})


# ── weekly plan coach (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §7.2) ──────
def test_coach_needs_slots_conflicts_and_supplements(hy):
    from hestia_common.coach import validate_need
    from app.core.coach import HygieiaCoach
    events = []
    hy.on_event = lambda e, d: events.append((e, d.get("need_id")))
    ret = hy.save_product({"name": "Retinale", "actives": ["retinale"]})
    bha = hy.save_product({"name": "BHA 2%", "actives": ["bha_salicilico"]})
    a = hy.save_routine({"name": "Notte retinoide", "slot": "evening", "cadence": {"mode": "target", "times": 3},
                         "steps": [{"product_id": ret["id"]}]})
    b = hy.save_routine({"name": "Notte esfoliante", "slot": "evening", "cadence": {"mode": "target", "times": 1},
                         "steps": [{"product_id": bha["id"]}]})
    vit = hy.save_product({"name": "Creatina", "category": "integratore", "status": "in_use"})
    c = hy.save_routine({"name": "Creatina", "cadence": {"mode": "daily"}, "steps": [{"product_id": vit["id"]}],
                         "plan_with": "workout"})
    assert events and events[-1][0] == "changed"
    start = hy.today()
    needs = {n["id"]: validate_need(n) for n in HygieiaCoach(hy).needs(start, start + timedelta(days=7))["needs"]}
    na, nb = needs[f"routine.{a['id']}"], needs[f"routine.{b['id']}"]
    assert na["kind"] == "slot" and na["time_of_day"] == "evening" and na["count"] == 3 and na["min_gap_days"] == 2
    assert f"routine.{b['id']}" in na["not_same_day"] and f"routine.{a['id']}" in nb["not_same_day"]
    assert needs[f"routine.{c['id']}"]["with"] == {"tag": "workout", "relation": "same_day"}
    assert "integratori: Creatina" in hy.summary()["text"]
    hy.log_routine(a["id"])
    assert events[-1] == ("done", f"routine.{a['id']}")
    review = HygieiaCoach(hy).review(start, start + timedelta(days=1))
    assert review["done"] == 1
