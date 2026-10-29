"""Demeter — nutrition («Alimentazione», dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A5).

The diet (daily kcal and protein targets, rules in plain words), the meals Marko logs (text; kcal and protein when they are
known, otherwise an estimate the assistant writes later through Oracle use case ``demeter.stima``, marked as
such) and the supplements taken (dose, part of the day, weekdays, only on training days) with the intakes.
Demeter is a coach of the weekly plan: every active supplement is a ``slot`` need; the plan puts it in the right
part of the day (and next to the workout when it is taken only on training days). Hygieia keeps the products in the
cabinet (stock, purchases); Demeter decides what is taken and when.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso

logger = logging.getLogger("hestia_demeter.service")

SLOTS = {"colazione": "Colazione", "pranzo": "Pranzo", "cena": "Cena", "spuntino": "Spuntino"}
TIMES = {"morning": "mattina", "midday": "pranzo", "afternoon": "pomeriggio", "evening": "sera", "any": "quando vuoi"}
ESTIMATE_USE = "demeter.stima"


def guess_slot(at: datetime) -> str:
    h = at.hour
    return "colazione" if h < 11 else "pranzo" if h < 15 else "spuntino" if h < 18 else "cena"


def parse_estimate(text: str | None) -> dict | None:
    """``{"kcal": 520, "protein": 30}`` from the model's answer (first JSON object); None when unusable."""
    m = re.search(r"\{.*?\}", text or "", re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
        kcal = int(round(float(raw.get("kcal"))))
        protein = raw.get("protein")
        protein = int(round(float(protein))) if protein not in (None, "") else None
    except (ValueError, TypeError, AttributeError):
        return None
    return {"kcal": kcal, "protein": protein} if 0 < kcal < 5000 else None


class Nutrition:
    def __init__(self, store, get: Callable[[str, Any], Any], *, tz_name: str = "Europe/Rome", hub=None,
                 on_event: Callable[[str, dict], Any] | None = None):
        self.store = store
        self.get = get
        self.tz = ZoneInfo(tz_name)
        self.hub = hub
        self.on_event = on_event or (lambda *_: None)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    # ── diet ────────────────────────────────────────────────────────────────
    def diet(self) -> dict:
        self.store.refresh()
        return {"kcal": None, "protein": None, "rules": [], "notes": "", **(self.store.data("diet", "current") or {})}

    def set_diet(self, body: dict) -> dict:
        old = self.diet()
        rules = body.get("rules", old["rules"])
        if isinstance(rules, str):
            rules = [r.strip() for r in re.split(r"[\n;]", rules) if r.strip()]
        data = {"kcal": int(body["kcal"]) if body.get("kcal") not in (None, "") else old["kcal"],
                "protein": int(body["protein"]) if body.get("protein") not in (None, "") else old["protein"],
                "rules": [str(r)[:200] for r in rules][:30], "notes": str(body.get("notes", old["notes"]))[:2000],
                "updated_at": now_iso()}
        if data["kcal"] is not None and not 800 <= data["kcal"] <= 6000:
            raise Invalid("kcal al giorno tra 800 e 6000")
        self.store.upsert("diet", "current", data)
        self.on_event("changed", {})
        return data

    # ── meals ───────────────────────────────────────────────────────────────
    def add_meal(self, text: str, *, slot: str = "", day: str = "", kcal: Any = None, protein: Any = None,
                 source: str = "manual") -> dict:
        text = str(text or "").strip()[:500]
        if not text:
            raise Invalid("cosa hai mangiato?")
        now = self.now()
        try:
            d = date.fromisoformat(day[:10]) if day else now.date()
        except ValueError:
            raise Invalid("data AAAA-MM-GG") from None
        slot = slot if slot in SLOTS else guess_slot(now)
        meal = {"date": d.isoformat(), "slot": slot, "text": text,
                "kcal": int(kcal) if kcal not in (None, "") else None,
                "protein": int(protein) if protein not in (None, "") else None,
                "estimated": False, "source": source, "at": now_iso()}
        mid = new_id("m")
        self.store.upsert("meal", mid, meal, at=f"{d.isoformat()}T12:00:00+00:00")
        logger.info("event=meal_logged slot=%s has_kcal=%s", slot, meal["kcal"] is not None)
        return {**meal, "id": mid}

    def estimate(self, mid: str) -> dict:
        """Oracle writes kcal/protein of a meal without numbers (marked ``estimated``); the owner's numbers win."""
        meal = self.store.data("meal", mid)
        if not meal:
            raise NotFound("pasto non trovato")
        if meal.get("kcal") is not None or not self.hub:
            return {**meal, "id": mid}
        out = parse_estimate(self.hub.llm(
            f"Pasto: {meal['text']}. Stima porzioni normali. Rispondi SOLO JSON {{\"kcal\": n, \"protein\": g}}.",
            use_case=ESTIMATE_USE, max_tokens=60, temperature=0))
        if not out:
            return {**meal, "id": mid}
        meal = {**meal, **out, "estimated": True}
        self.store.upsert("meal", mid, meal, at=f"{meal['date']}T12:00:00+00:00")
        return {**meal, "id": mid}

    def update_meal(self, mid: str, body: dict) -> dict:
        meal = self.store.data("meal", mid)
        if not meal:
            raise NotFound("pasto non trovato")
        for k in ("text", "slot"):
            if body.get(k):
                meal[k] = str(body[k])[:500]
        for k in ("kcal", "protein"):
            if k in body:
                meal[k] = int(body[k]) if body[k] not in (None, "") else None
                meal["estimated"] = False
        self.store.upsert("meal", mid, meal, at=f"{meal['date']}T12:00:00+00:00")
        return {**meal, "id": mid}

    def delete_meal(self, mid: str) -> dict:
        if not self.store.delete("meal", mid):
            raise NotFound("pasto non trovato")
        return {"deleted": True}

    def meals(self, day: str = "", days: int = 1) -> list[dict]:
        self.store.refresh()
        end = date.fromisoformat(day[:10]) if day else self.today()
        start = (end - timedelta(days=max(1, days) - 1)).isoformat()
        rows = [{**r["data"], "id": r["id"]} for r in self.store.all("meal")
                if start <= r["data"].get("date", "") <= end.isoformat()]
        order = list(SLOTS)
        return sorted(rows, key=lambda m: (m["date"], order.index(m["slot"]) if m["slot"] in order else 9))

    def day_summary(self, day: date | None = None) -> dict:
        day = day or self.today()
        meals = self.meals(day.isoformat())
        diet = self.diet()
        kcal = sum(m["kcal"] or 0 for m in meals)
        protein = sum(m["protein"] or 0 for m in meals)
        return {"date": day.isoformat(), "meals": meals, "kcal": kcal, "protein": protein,
                "kcal_target": diet["kcal"], "protein_target": diet["protein"],
                "unknown": sum(1 for m in meals if m["kcal"] is None),
                "supplements": self.supplements_today(day)}

    # ── supplements ─────────────────────────────────────────────────────────
    def supplements(self, include_paused: bool = False) -> list[dict]:
        self.store.refresh()
        return sorted([s for s in self.store.items("supplement") if include_paused or s.get("status") == "active"],
                      key=lambda s: s["name"].casefold())

    def find_supplement(self, ref: str) -> dict:
        s = self.store.data("supplement", ref)
        if s:
            return s
        q = str(ref or "").strip().casefold()
        hits = [s for s in self.store.items("supplement") if q and q in s["name"].casefold()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise NotFound(f"nessun integratore «{ref}»")
        raise Invalid("più integratori corrispondono: " + ", ".join(h["name"] for h in hits[:5]))

    def save_supplement(self, body: dict, sid: str | None = None) -> dict:
        old = self.find_supplement(sid) if sid else {}
        name = str(body.get("name") or old.get("name") or "").strip()[:80]
        if not name:
            raise Invalid("serve il nome")
        tod = body.get("time_of_day") or old.get("time_of_day") or "morning"
        if tod not in TIMES:
            raise Invalid("momento: " + ", ".join(TIMES))
        days = body.get("days", old.get("days") or [])
        data = {"name": name, "dose": str(body.get("dose", old.get("dose") or ""))[:60], "time_of_day": tod,
                "days": sorted({int(d) for d in days if 0 <= int(d) <= 6}),
                "training_days_only": bool(body.get("training_days_only", old.get("training_days_only", False))),
                "with_food": bool(body.get("with_food", old.get("with_food", False))),
                "status": body.get("status") if body.get("status") in ("active", "paused") else
                old.get("status") or "active", "notes": str(body.get("notes", old.get("notes") or ""))[:500],
                "updated_at": now_iso()}
        sid = old.get("id") or new_id("s")
        self.store.upsert("supplement", sid, data, ref_id=name.casefold())
        self.on_event("changed", {})
        return {**data, "id": sid}

    def delete_supplement(self, ref: str) -> dict:
        s = self.find_supplement(ref)
        self.store.delete("supplement", s["id"])
        self.on_event("changed", {})
        return {"deleted": True, "name": s["name"]}

    def _due_on(self, s: dict, day: date) -> bool:
        return not s.get("days") or day.weekday() in s["days"]

    def supplements_today(self, day: date | None = None) -> list[dict]:
        day = day or self.today()
        taken = {r["data"]["supplement_id"] for r in self.store.all("intake") if r["data"].get("date") == day.isoformat()}
        return [{"id": s["id"], "name": s["name"], "dose": s.get("dose"), "time_of_day": s["time_of_day"],
                 "taken": s["id"] in taken} for s in self.supplements() if self._due_on(s, day)]

    def take(self, ref: str, day: str = "") -> dict:
        s = self.find_supplement(ref)
        d = day[:10] if day else self.today().isoformat()
        iid = f"{s['id']}-{d}"
        self.store.upsert("intake", iid, {"supplement_id": s["id"], "date": d, "at": now_iso()}, parent_id=s["id"],
                          at=f"{d}T12:00:00+00:00")
        self.on_event("done", {"need_id": f"supplement.{s['id']}", "at": now_iso()})
        return {"taken": True, "name": s["name"], "date": d}

    # ── coach of the weekly plan ────────────────────────────────────────────
    def needs(self, start: date, end: date) -> dict:
        out = []
        for s in self.supplements():
            n = {"id": f"supplement.{s['id']}", "title": s["name"] + (f" ({s['dose']})" if s.get("dose") else ""),
                 "kind": "slot", "per": "day", "count": 1, "time_of_day": s["time_of_day"], "days": s.get("days") or [],
                 "tags": [f"supplement.{s['id']}"], "priority": "should", "link": "integratori",
                 "reason": "a stomaco pieno" if s.get("with_food") else ""}
            if s.get("training_days_only"):
                n["with"] = {"tag": "workout", "relation": "same_day"}
            out.append(n)
        t = self.day_summary()
        state = f"oggi {t['kcal']}" + (f"/{t['kcal_target']}" if t["kcal_target"] else "") + " kcal"
        return {"state": state, "needs": out}

    def review(self, start: date, end: date) -> dict:
        days = [start + timedelta(days=i) for i in range((end - start).days)]
        due = sum(1 for d in days for s in self.supplements() if self._due_on(s, d) and not s.get("training_days_only"))
        done = sum(1 for r in self.store.all("intake") if start.isoformat() <= r["data"].get("date", "") < end.isoformat())
        diet, notes = self.diet(), []
        if diet["kcal"]:
            logged = [self.day_summary(d) for d in days]
            logged = [x for x in logged if x["meals"] and not x["unknown"]]
            if logged:
                avg = sum(x["kcal"] for x in logged) / len(logged)
                notes.append(f"media {avg:.0f} kcal su {len(logged)} giorni (obiettivo {diet['kcal']})")
        return {"done": done, "missed": max(0, due - done), "adherence": round(done / due, 2) if due else None,
                "notes": notes}

    def recap(self, day: date, nxt: date) -> dict:
        y = self.day_summary(day)
        done = []
        if y["meals"]:
            text = f"{len(y['meals'])} pasti, {y['kcal']} kcal" + (f" su {y['kcal_target']}" if y["kcal_target"] else "")
            if y["unknown"]:
                text += f" ({y['unknown']} senza numeri)"
            done.append({"text": text})
        todo = [s for s in self.supplements_today(nxt)]
        return {"done": done, "next": [{"text": "Integratori: " + ", ".join(s["name"] for s in todo[:6])}] if todo else []}
