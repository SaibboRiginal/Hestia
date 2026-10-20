"""Plutus as a coach of the weekly plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §7.3).

Needs (``hestia_common.coach`` contract):
- one ``target`` per budget (category or total): what is left this budget month, spread over the weeks still to go
  (``value`` = what fits this week, ``progress`` = spent / budget); no budget → no target;
- one ``block`` "Rivedi spese" (15') when the movements to review reach ``plutus.coach.review_threshold``.
``review`` = budgets kept or over in the budget month of that week.
"""
from __future__ import annotations

import math
from datetime import date

REVIEW_NEED = "finance.review"


class PlutusCoach:
    def __init__(self, plutus):
        self.p = plutus
        self.review_open = False                         # the "Rivedi spese" block is in the plan

    def check(self) -> str | None:
        """After movements change: ``done`` when the review is no longer needed, ``changed`` when it now is."""
        need = self.p.summary().get("to_review", 0) >= self._threshold()
        if self.review_open and not need:
            self.review_open = False
            return "done"
        if need and not self.review_open:
            self.review_open = True
            return "changed"
        return None

    def _threshold(self) -> int:
        try:
            return max(1, int(self.p.setting("plutus.coach.review_threshold", 10) or 10))
        except (TypeError, ValueError):
            return 10

    def needs(self, start: date, end: date) -> dict:
        s = self.p.summary()
        cur = s["currency"]
        weeks_left = max(1, math.ceil((s["days_total"] - s["days_gone"] + 1) / 7))
        items = [c for c in s["categories"] if c.get("budget")]
        if s.get("budget"):
            items.append({"id": "total", "label": "Totale", "spent": s["spent"], "budget": s["budget"]})
        out: list[dict] = []
        for c in items:
            left = round(c["budget"] - c["spent"], 2)
            week = round(max(0.0, left) / weeks_left, 2)
            out.append({"id": f"finance.budget.{c['id']}", "title": c["label"], "kind": "target", "count": 1,
                        "value": week, "unit": cur, "progress": round(c["spent"] / c["budget"], 2),
                        "tags": ["budget"], "priority": "could",
                        "reason": (f"restano {left:.2f} {cur} nel mese, circa {week:.2f} a settimana" if left >= 0
                                   else f"budget superato di {-left:.2f} {cur}")})
        self.review_open = s.get("to_review", 0) >= self._threshold()
        if self.review_open:
            out.append({"id": REVIEW_NEED, "title": "Rivedi spese", "kind": "block", "count": 1, "minutes": 15,
                        "time_of_day": "evening", "tags": ["admin"], "priority": "could",
                        "reason": f"{s['to_review']} movimenti da controllare", "link": "movimenti"})
        state = f"speso {s['spent']:.2f} {cur}" + (f" su {s['budget']:.2f}" if s.get("budget") else "")
        return {"state": state, "needs": out}

    def review(self, start: date, end: date) -> dict:
        s = self.p.summary(start.isoformat())
        with_budget = [c for c in s["categories"] if c.get("budget")]
        over = [c["label"] for c in with_budget if c["spent"] > c["budget"]]
        notes = [f"budget superato: {', '.join(over)}"] if over else []
        if s.get("budget"):
            notes.append(f"mese: {s['spent']:.2f} su {s['budget']:.2f} {s['currency']}")
        kept = len(with_budget) - len(over)
        return {"done": kept, "missed": len(over), "notes": notes,
                "adherence": round(kept / len(with_budget), 2) if with_budget else None}
