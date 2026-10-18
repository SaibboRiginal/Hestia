"""Wardrobe statistics (SPEC §5): composition, value, forgotten pieces, gaps; usage only as hints when marks exist."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from .domain import KINDS, OWNED, SEASONS, STATUSES


def usage(pieces: list[dict], wears: list[dict]) -> dict[str, dict]:
    """Per piece: ``wear_count`` and ``last_worn`` from the marks (and the hand-set last worn)."""
    out = {p["id"]: {"wear_count": 0, "last_worn": p.get("last_worn_manual")} for p in pieces}
    for w in wears:
        for pid in w.get("piece_ids") or []:
            u = out.get(pid)
            if u is None:
                continue
            u["wear_count"] += 1
            if not u["last_worn"] or w["date"] > u["last_worn"]:
                u["last_worn"] = w["date"]
    return out


def forgotten(pieces: list[dict], use: dict[str, dict], today: date, days: int) -> list[dict]:
    """Owned, wearable pieces not worn for ``days`` (or never marked and added more than ``days`` ago)."""
    cut = (today - timedelta(days=days)).isoformat()
    out = []
    for p in pieces:
        if p.get("status") != "active" or p.get("kind") == "accessory":
            continue
        last = use.get(p["id"], {}).get("last_worn")
        added = str(p.get("created_at") or "")[:10]
        if (last and last < cut) or (not last and added and added < cut):
            out.append({"id": p["id"], "name": p["name"], "last_worn": last,
                        "days": (today - date.fromisoformat(last)).days if last else None,
                        "photo": (p.get("photos") or [None])[0]})
    out.sort(key=lambda x: (x["last_worn"] or "", x["name"]))
    return out


def gaps(pieces: list[dict], categories: dict[str, dict]) -> list[str]:
    """Simple holes in the wardrobe, in plain words."""
    owned = [p for p in pieces if p.get("status") in OWNED]
    msgs = []

    def has(pred) -> bool:
        return any(pred(p) for p in owned)
    if owned and not has(lambda p: p.get("category") == "outerwear" and int(p.get("warmth") or 3) >= 4):
        msgs.append("Nessun capospalla pesante per l'inverno")
    if owned and not has(lambda p: p.get("kind") == "shoes" and "winter" in (p.get("seasons") or [])):
        msgs.append("Nessuna scarpa per l'inverno")
    if owned and not has(lambda p: p.get("kind") == "shoes" and int(p.get("formality") or 3) >= 4):
        if has(lambda p: int(p.get("formality") or 3) >= 4 and p.get("kind") == "garment"):
            msgs.append("Hai capi eleganti ma nessuna scarpa elegante")
    if owned and not has(lambda p: (p.get("weather") or {}).get("rain_ok") or p.get("subcategory") == "raincoat"):
        msgs.append("Niente di adatto alla pioggia")
    for season, label in SEASONS.items():
        tops = [p for p in owned if p.get("category") == "top" and season in (p.get("seasons") or [])]
        bottoms = [p for p in owned if p.get("category") == "bottom" and season in (p.get("seasons") or [])]
        if owned and (len(tops) < 2 or len(bottoms) < 1):
            msgs.append(f"Pochi capi per {label.lower()} ({len(tops)} sopra, {len(bottoms)} sotto)")
    return msgs


def compute(pieces: list[dict], outfits: list[dict], wears: list[dict], categories: dict[str, dict],
            colors: dict[str, dict], today: date, forgotten_days: int, currency: str = "EUR") -> dict:
    use = usage(pieces, wears)
    owned = [p for p in pieces if p.get("status") in OWNED]
    by_kind = Counter(p["kind"] for p in owned)
    by_cat = Counter(p["category"] for p in owned)
    by_color = Counter((p.get("colors") or [{}])[0].get("key") for p in owned if p.get("colors"))
    by_season = Counter(s for p in owned for s in p.get("seasons") or [])
    by_style = Counter(s for p in owned for s in p.get("styles") or [])
    by_status = Counter(p.get("status") for p in pieces)
    value = sum((p.get("purchase") or {}).get("price") or 0 for p in owned)
    marks = len(wears)
    worn = sorted(((use[p["id"]]["wear_count"], p) for p in owned if use[p["id"]]["wear_count"]), key=lambda x: -x[0])
    cpw = []
    for n, p in worn:
        price = (p.get("purchase") or {}).get("price")
        if price:
            cpw.append({"id": p["id"], "name": p["name"], "price": price, "wears": n, "cost_per_wear": round(price / n, 2)})
    cpw.sort(key=lambda x: -x["cost_per_wear"])
    months: list[str] = []
    d = today.replace(day=1)
    for _ in range(12):
        months.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    months.reverse()
    per_month = Counter(w["date"][:7] for w in wears)
    label = lambda vocab, k: (vocab.get(k) or {}).get("label") or k  # noqa: E731
    return {
        "totals": {"pieces": len(owned), "garments": by_kind.get("garment", 0), "shoes": by_kind.get("shoes", 0),
                   "accessories": by_kind.get("accessory", 0), "outfits": len([o for o in outfits if o.get("status") != "archived"]),
                   "value": round(value, 2), "currency": currency, "wishlist": by_status.get("wishlist", 0),
                   "marks": marks},
        "kpi": {"items": [
            {"label": "Capi", "value": by_kind.get("garment", 0)}, {"label": "Scarpe", "value": by_kind.get("shoes", 0)},
            {"label": "Accessori", "value": by_kind.get("accessory", 0)},
            {"label": "Outfit", "value": len([o for o in outfits if o.get("status") != "archived"])},
            *([{"label": "Valore", "value": round(value), "unit": "€" if currency == "EUR" else currency}] if value else [])]},
        "by_kind": [{"key": k, "label": KINDS[k], "count": by_kind.get(k, 0)} for k in KINDS],
        "by_category": [{"key": k, "label": label(categories, k), "count": n} for k, n in by_cat.most_common()],
        "by_color": [{"key": k, "label": label(colors, k), "hex": (colors.get(k) or {}).get("hex"), "count": n}
                     for k, n in by_color.most_common()],
        "by_season": [{"key": k, "label": SEASONS[k], "count": by_season.get(k, 0)} for k in SEASONS],
        "by_style": [{"key": k, "label": k, "count": n} for k, n in by_style.most_common(10)],
        "by_status": [{"key": k, "label": STATUSES[k], "count": n} for k, n in by_status.items()],
        "forgotten": forgotten(pieces, use, today, forgotten_days),
        "gaps": gaps(pieces, categories),
        # usage = hints only: marks are occasional (SPEC §4.3)
        "usage": {"has_marks": marks > 0,
                  "most_worn": [{"id": p["id"], "name": p["name"], "wears": n} for n, p in worn[:8]],
                  "never_marked": len([p for p in owned if not use[p["id"]]["wear_count"] and p.get("kind") != "accessory"]),
                  "cost_per_wear": cpw[:10],
                  "per_month": {"labels": months, "values": [per_month.get(m, 0) for m in months]}},
    }
