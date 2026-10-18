"""«Cosa mi metto» — deterministic outfit suggestions (SPEC §5): no LLM, every result explains itself.

Candidates = saved outfits + combinations generated from available pieces. Hard filters: piece available
(status active), season, weather vs warmth/rain. Score: occasion/style, formality spread, colour harmony,
pattern clash, recency penalty, rotation bonus for forgotten pieces, favourites and rating.
"""
from __future__ import annotations

import itertools
from datetime import date, timedelta
from typing import Any

from .domain import NEUTRAL_COLORS, SEASONS, SLOT_ORDER

OCCASION_FORMALITY = {"work": (3, 4), "office": (3, 4), "business": (4, 5), "ceremony": (4, 5), "evening": (3, 4),
                      "date": (3, 4), "party": (2, 4), "weekend": (1, 3), "travel": (1, 3), "home": (1, 2), "sport": (1, 1)}
# total warmth of the upper layers (top + mid + outer) that fits a temperature
_WARMTH_BANDS = [(26, (1, 2)), (20, (2, 3)), (15, (3, 5)), (9, (5, 8)), (-99, (7, 12))]


def season_of(day: date) -> str:
    m = day.month
    return "spring" if m in (3, 4, 5) else "summer" if m in (6, 7, 8) else "autumn" if m in (9, 10, 11) else "winter"


def warmth_band(temp_c: float | None, season: str) -> tuple[int, int]:
    if temp_c is None:
        temp_c = {"summer": 27, "spring": 17, "autumn": 14, "winter": 5}[season]
    for limit, band in _WARMTH_BANDS:
        if temp_c >= limit:
            return band
    return _WARMTH_BANDS[-1][1]


class Suggester:
    """Built per request from the current wardrobe (mirror) and the "Indossato" marks."""

    def __init__(self, pieces: list[dict], outfits: list[dict], wears: list[dict], *, today: date,
                 forgotten_days: int = 180):
        self.today = today
        self.pieces = {p["id"]: p for p in pieces}
        self.outfits = outfits
        self.last_worn: dict[str, str] = {}
        self.outfit_last: dict[str, str] = {}
        for w in wears:
            for pid in w.get("piece_ids") or []:
                if w["date"] > self.last_worn.get(pid, ""):
                    self.last_worn[pid] = w["date"]
            if w.get("outfit_id") and w["date"] > self.outfit_last.get(w["outfit_id"], ""):
                self.outfit_last[w["outfit_id"]] = w["date"]
        for p in pieces:
            manual = p.get("last_worn_manual")
            if manual and manual > self.last_worn.get(p["id"], ""):
                self.last_worn[p["id"]] = manual
        self.forgotten_before = (today - timedelta(days=forgotten_days)).isoformat()

    # ── filters ────────────────────────────────────────────────────────────
    def available(self, p: dict, season: str, rain: bool) -> bool:
        if p.get("status") != "active" or p.get("kind") not in ("garment", "shoes", "accessory"):
            return False
        if season not in (p.get("seasons") or SEASONS):
            return False
        if rain and p.get("weather", {}).get("rain_ok") is False:
            return False
        return True

    def _days_since(self, pid: str) -> int | None:
        last = self.last_worn.get(pid)
        return (self.today - date.fromisoformat(last)).days if last else None

    # ── scoring ────────────────────────────────────────────────────────────
    def score(self, slots: list[dict], *, occasion: str, styles: list[str], temp_c: float | None, season: str,
              rain: bool, recent_days: int, saved: dict | None = None) -> tuple[float, list[str]]:
        ps = [self.pieces[s["piece_id"]] for s in slots]
        score, reasons = 50.0, []
        # weather: upper layers' warmth inside the band
        upper = [p for s, p in zip(slots, ps) if s["slot"] in ("base", "top", "mid", "outer", "onepiece")]
        total = sum(int(p.get("warmth") or 3) for p in upper)
        lo, hi = warmth_band(temp_c, season)
        if lo <= total <= hi:
            score += 12
            reasons.append(f"adatto a {round(temp_c)}°" if temp_c is not None else f"adatto alla stagione ({SEASONS[season].lower()})")
        else:
            score -= 6 * (lo - total if total < lo else total - hi)
        explicit = [p.get("weather") or {} for p in ps]
        if temp_c is not None and any((w.get("min_c") is not None and temp_c < w["min_c"]) or
                                      (w.get("max_c") is not None and temp_c > w["max_c"]) for w in explicit):
            score -= 15
        if rain and any((p.get("weather") or {}).get("rain_ok") for p in ps):
            score += 6
            reasons.append("va bene con la pioggia")
        # occasion & style
        if occasion:
            lo_f, hi_f = OCCASION_FORMALITY.get(occasion, (1, 5))
            forms = [int(p.get("formality") or 3) for p in ps if p.get("kind") != "accessory"]
            avg = sum(forms) / max(1, len(forms))
            if lo_f - 0.5 <= avg <= hi_f + 0.5:
                score += 10
                reasons.append("giusto per l'occasione")
            else:
                score -= 5 * min(abs(avg - lo_f), abs(avg - hi_f))
            tagged = [p for p in ps if occasion in (p.get("occasions") or [])]
            if saved and occasion in (saved.get("occasions") or []):
                score += 8
            elif tagged:
                score += 3 * len(tagged)
        if styles:
            hits = sum(1 for p in ps if set(styles) & set(p.get("styles") or []))
            if saved and set(styles) & set(saved.get("styles") or []):
                hits += 2
            if hits:
                score += 3 * hits
                reasons.append("nel tuo stile")
        forms = [int(p.get("formality") or 3) for p in ps if p.get("kind") != "accessory"]
        if forms and max(forms) - min(forms) > 2:
            score -= 8 * (max(forms) - min(forms) - 2)
        # colours and patterns
        accents = {c["key"] for p in ps for c in (p.get("colors") or [])[:1] if c.get("key") not in NEUTRAL_COLORS}
        if len(accents) <= 1:
            score += 6
            reasons.append("colori che stanno bene insieme" if accents else "colori neutri, facile")
        elif len(accents) > 2:
            score -= 7 * (len(accents) - 2)
        patterned = [p for p in ps if p.get("pattern") not in ("", "plain", None)]
        if len(patterned) > 1:
            score -= 8 * (len(patterned) - 1)
        # recency, rotation, favourites
        recent = [p for p in ps if (d := self._days_since(p["id"])) is not None and d < recent_days and p.get("kind") != "accessory"]
        score -= 9 * len(recent)
        forgotten = [p for p in ps if self.last_worn.get(p["id"], "") < self.forgotten_before and p.get("kind") != "accessory"
                     and self.last_worn.get(p["id"])]
        if forgotten:
            score += 4 * len(forgotten)
            reasons.append(f"rimette in giro {forgotten[0]['name']}")
        if saved:
            if saved.get("favorite"):
                score += 8
                reasons.append("tra i preferiti")
            if saved.get("rating"):
                score += 2 * (int(saved["rating"]) - 3)
        else:
            score += 2 * sum(1 for p in ps if p.get("favorite"))
        return round(score, 1), reasons[:4]

    # ── candidates ─────────────────────────────────────────────────────────
    def suggest(self, *, day: date | None = None, occasion: str = "", styles: list[str] | None = None,
                temp_c: float | None = None, rain: bool = False, recent_days: int = 4, count: int = 3,
                exclude_outfits: set[str] | None = None) -> dict:
        day = day or self.today
        season = season_of(day)
        styles = styles or []
        ok = {pid: p for pid, p in self.pieces.items() if self.available(p, season, rain)}
        out: list[dict] = []
        seen: set[frozenset] = set()
        recent_cut = (day - timedelta(days=recent_days)).isoformat()
        for o in self.outfits:
            if o.get("status") == "archived" or o["id"] in (exclude_outfits or set()):
                continue
            slots = [s for s in o.get("slots") or [] if s["piece_id"] in self.pieces]
            if not slots or any(s["piece_id"] not in ok for s in slots if self.pieces[s["piece_id"]].get("kind") != "accessory"):
                continue
            if season not in (o.get("seasons") or SEASONS):
                continue
            if self.outfit_last.get(o["id"], "") > recent_cut:
                continue
            sc, why = self.score(slots, occasion=occasion, styles=styles, temp_c=temp_c, season=season, rain=rain,
                                 recent_days=recent_days, saved=o)
            seen.add(frozenset(s["piece_id"] for s in slots))
            out.append({"outfit_id": o["id"], "name": o["name"], "slots": slots, "score": sc, "reasons": why, "saved": True})
        out += self._generated(ok, seen, occasion=occasion, styles=styles, temp_c=temp_c, season=season, rain=rain,
                               recent_days=recent_days)
        out.sort(key=lambda c: -c["score"])
        picked, used_tops = [], set()
        for c in out:                               # variety: not three times the same top
            top = next((s["piece_id"] for s in c["slots"] if s["slot"] in ("top", "onepiece")), None)
            if top in used_tops and len(out) > count:
                continue
            used_tops.add(top)
            picked.append(c)
            if len(picked) >= count:
                break
        return {"date": day.isoformat(), "season": season, "temp_c": temp_c, "rain": rain, "occasion": occasion,
                "available_pieces": len(ok), "items": [self._view(c) for c in picked]}

    def _generated(self, ok: dict[str, dict], seen: set[frozenset], **kw) -> list[dict]:
        by_slot: dict[str, list[dict]] = {}
        for p in ok.values():
            by_slot.setdefault(p.get("_slot") or "top", []).append(p)

        def best(slot: str, n: int) -> list[dict]:
            items = by_slot.get(slot, [])
            occ, sty = kw["occasion"], kw["styles"]

            def rank(p: dict) -> float:
                r = 0.0
                if occ and occ in (p.get("occasions") or []):
                    r += 3
                if sty and set(sty) & set(p.get("styles") or []):
                    r += 2
                if occ:
                    lo, hi = OCCASION_FORMALITY.get(occ, (1, 5))
                    f = int(p.get("formality") or 3)
                    r -= 0 if lo <= f <= hi else min(abs(f - lo), abs(f - hi))
                d = self._days_since(p["id"])
                r -= 2 if d is not None and d < kw["recent_days"] else 0
                return r + (0.5 if p.get("favorite") else 0)
            return sorted(items, key=rank, reverse=True)[:n]

        lo, hi = warmth_band(kw["temp_c"], kw["season"])
        tops, bottoms, ones, shoes = best("top", 6), best("bottom", 5), best("onepiece", 3), best("shoes", 3)
        mids, outers = best("mid", 3), best("outer", 3)
        bases: list[list[tuple[str, dict]]] = [[("top", t), ("bottom", b)] for t, b in itertools.product(tops, bottoms)]
        bases += [[("onepiece", o)] for o in ones]
        out = []
        for base in bases:
            layers_options: list[list[tuple[str, dict]]] = [[]]
            warm = sum(int(p.get("warmth") or 3) for s, p in base if s != "bottom")
            if warm < lo:
                layers_options = [[("mid", m)] for m in mids] + [[("outer", o)] for o in outers] + \
                                 [[("mid", m), ("outer", o)] for m in mids[:2] for o in outers[:2]] or [[]]
            for layers in layers_options:
                for sh in (shoes or [None]):
                    combo = base + layers + ([("shoes", sh)] if sh else [])
                    key = frozenset(p["id"] for _, p in combo)
                    if key in seen:
                        continue
                    seen.add(key)
                    slots = sorted(({"slot": s, "piece_id": p["id"]} for s, p in combo), key=lambda x: SLOT_ORDER.index(x["slot"]))
                    sc, why = self.score(slots, **kw)
                    out.append({"outfit_id": None, "name": " + ".join(p["name"] for _, p in combo[:3]), "slots": slots,
                                "score": sc, "reasons": why, "saved": False})
        return out

    def _view(self, c: dict) -> dict[str, Any]:
        return {**c, "pieces": [{"slot": s["slot"], "id": s["piece_id"], "name": self.pieces[s["piece_id"]]["name"],
                                 "photo": (self.pieces[s["piece_id"]].get("photos") or [None])[0],
                                 "colors": self.pieces[s["piece_id"]].get("colors") or []} for s in c["slots"]]}
