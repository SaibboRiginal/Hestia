"""Wardrobe service: everything the REST API, the UI and the MCP tools do (SPEC docs/work/2026-10-17-modulo-guardaroba).

Reads come from the in-memory mirror (instant stats/suggestions), writes go to Archive first (``Store``).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import domain, photos, stats as stats_mod
from .domain import Invalid
from .hub import Hub
from .store import Store, now_iso
from .suggest import Suggester, season_of

logger = logging.getLogger("hestia_wardrobe.service")

PER_LABEL = {"day": "oggi", "week": "questa settimana", "month": "questo mese"}
# Personal settings shared by every module (owner Themis): never a wardrobe.* copy.
WEEK_START_KEY = "themis.personal.week_start"
CURRENCY_KEY = "themis.personal.currency"


class NotFound(LookupError):
    pass


def _norm(text: Any) -> str:
    s = str(text or "").lower()
    for a, b in (("à", "a"), ("è", "e"), ("é", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


class Wardrobe:
    def __init__(self, store: Store, hub: Hub, cfg: Callable[[str, Any], Any], tz: str = "Europe/Rome"):
        self.store = store
        self.hub = hub
        self._cfg = cfg
        try:
            self.tz = ZoneInfo(tz)
        except Exception:
            self.tz = ZoneInfo("UTC")

    def cfg(self, key: str, default: Any = None) -> Any:
        try:
            value = self._cfg(f"wardrobe.{key}", default)
        except Exception:
            return default
        return default if value is None else value

    def personal(self, key: str, default: Any = None) -> Any:
        try:
            value = self._cfg(key, default)
        except Exception:
            return default
        return default if value is None else value

    def currency(self) -> str:
        return str(self.personal(CURRENCY_KEY, "EUR"))

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def _local_day(self, iso: Any) -> str:
        """Local date (YYYY-MM-DD) of a stored UTC timestamp: near midnight the UTC date is another day."""
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            return str(iso or "")[:10]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(self.tz).date().isoformat()

    # ── vocabularies ───────────────────────────────────────────────────────
    def ensure_vocabularies(self) -> None:
        """Seed the default vocabularies once (idempotent: existing rows are the user's and stay)."""
        missing = [n for n in domain.DEFAULT_VOCABULARIES if not self.store.get("taxonomy", n)]
        if missing:
            self.store.write([{"kind": "taxonomy", "id": n, "data": {"values": domain.vocabulary(n, domain.DEFAULT_VOCABULARIES[n])}}
                              for n in missing])
            logger.info("event=wardrobe_vocabularies_seeded names=%s", ",".join(missing))

    def vocab(self, name: str, *, hidden: bool = True) -> list[dict]:
        row = self.store.data("taxonomy", name)
        values = (row or {}).get("values") or domain.vocabulary(name, domain.DEFAULT_VOCABULARIES.get(name, []))
        return [v for v in sorted(values, key=lambda v: v.get("order", 0)) if hidden or not v.get("hidden")]

    def vocab_map(self, name: str) -> dict[str, dict]:
        return {v["key"]: v for v in self.vocab(name)}

    def vocab_keys(self, name: str, values: Any) -> list[str] | Any:
        """Labels typed by people or the assistant ("Ufficio") → the vocabulary key ("office"); unknown words stay
        free tags. Without this a piece tagged in chat never matched one tagged from the UI, nor the suggester."""
        if values is None:
            return values
        items = re.split(r"[,;]", values) if isinstance(values, str) else list(values)
        by_label = {domain.slug(v.get("label")): v["key"] for v in self.vocab(name)}
        keys = {v["key"] for v in self.vocab(name)}
        out = []
        for v in items:
            k = domain.slug(v)
            k = k if k in keys else by_label.get(k, k)
            if k and k not in out:
                out.append(k)
        return out

    def _tag_keys(self, data: dict) -> dict:
        return {**data, **{f: self.vocab_keys(n, data[f]) for f, n in (("occasions", "occasion"), ("styles", "style"))
                           if data.get(f) is not None}}

    def vocabularies(self) -> dict:
        return {n: self.vocab(n) for n in domain.DEFAULT_VOCABULARIES}

    def set_vocabulary(self, name: str, values: list[dict]) -> list[dict]:
        clean = domain.vocabulary(name, values)
        if name == "category":
            used = {p.get("category") for p in self.store.items("piece")} | {p.get("subcategory") for p in self.store.items("piece")}
            keys = {v["key"] for v in clean}
            lost = sorted(k for k in used - keys if k)
            if lost:
                raise Invalid(f"categorie ancora usate da alcuni capi: {', '.join(lost)} (nascondile invece di toglierle)")
        self.store.upsert("taxonomy", name, {"values": clean})
        return clean

    def meta(self) -> dict:
        return {"kinds": domain.KINDS, "seasons": domain.SEASONS, "statuses": domain.STATUSES, "conditions": domain.CONDITIONS,
                "slots": domain.SLOTS, "collection_types": domain.COLLECTION_TYPES, "vocabularies": self.vocabularies(),
                "today": self.today().isoformat(), "season": season_of(self.today()),
                "currency": self.currency(), "goal": self.goal_progress()}

    # ── shared lookups ─────────────────────────────────────────────────────
    def _pieces_raw(self) -> list[dict]:
        cats = self.vocab_map("category")
        out = []
        for p in self.store.items("piece"):
            cat = cats.get(p.get("subcategory") or "") or cats.get(p.get("category") or "") or {}
            out.append({**p, "_slot": cat.get("slot") or "top"})
        return out

    def _wears(self) -> list[dict]:
        return sorted(self.store.items("wear"), key=lambda w: (w.get("date") or "", w.get("created_at") or ""))

    def get(self, kind: str, id: str) -> dict:
        row = self.store.data(kind, id)
        if not row:
            raise NotFound({"piece": "capo", "outfit": "outfit", "wear": "segno", "collection": "lista",
                            "photo": "foto"}.get(kind, kind) + " non trovato")
        return row

    def _decorate(self, p: dict, use: dict[str, dict], cats: dict[str, dict]) -> dict:
        u = use.get(p["id"], {})
        cat = cats.get(p.get("category") or "") or {}
        sub = cats.get(p.get("subcategory") or "") or {}
        price = (p.get("purchase") or {}).get("price")
        n = u.get("wear_count", 0)
        return {**{k: v for k, v in p.items() if k != "_slot"}, "wear_count": n, "last_worn": u.get("last_worn"),
                "category_label": cat.get("label") or p.get("category"), "subcategory_label": sub.get("label") or "",
                "slot": p.get("_slot") or sub.get("slot") or cat.get("slot") or "top",
                "cost_per_wear": round(price / n, 2) if price and n else None,
                "status_label": domain.STATUSES.get(p.get("status") or "", p.get("status"))}

    # ── pieces ─────────────────────────────────────────────────────────────
    def pieces(self, *, kind: str = "", category: str = "", status: str = "", season: str = "", style: str = "",
               occasion: str = "", color: str = "", q: str = "", favorite: bool | None = None,
               not_worn_days: int | None = None, sort: str = "recent", include_archived: bool = False,
               limit: int = 500, offset: int = 0) -> dict:
        cats = self.vocab_map("category")
        raw = self._pieces_raw()
        use = stats_mod.usage(raw, self._wears())
        items = []
        kinds = set(k for k in kind.split(",") if k)
        statuses = set(s for s in status.split(",") if s)
        cut = (self.today() - timedelta(days=not_worn_days)).isoformat() if not_worn_days else None
        terms = [t for t in _norm(q).split(" ") if t]
        for p in raw:
            if kinds and p.get("kind") not in kinds:
                continue
            st = p.get("status") or "active"
            if statuses:
                if st not in statuses:
                    continue
            elif not include_archived and st in ("archived", "donated", "sold"):
                continue
            if category and category not in (p.get("category"), p.get("subcategory")):
                continue
            if season and season not in (p.get("seasons") or []):
                continue
            if style and style not in (p.get("styles") or []):
                continue
            if occasion and occasion not in (p.get("occasions") or []):
                continue
            if color and color not in [c.get("key") for c in p.get("colors") or []]:
                continue
            if favorite is not None and bool(p.get("favorite")) != favorite:
                continue
            if cut:
                last = use[p["id"]]["last_worn"]
                if last and last >= cut:
                    continue
            score = 0
            if terms:
                hay = self._haystack(p, cats)
                if not all(t in hay for t in terms):
                    continue
                score = sum(3 if t in _norm(p["name"]) else 1 for t in terms)
            items.append((score, self._decorate(p, use, cats)))
        # secondary order first, then the search score (stable sort keeps the secondary inside equal scores)
        orders = {"recent": (lambda p: p.get("created_at") or "", True), "name": (lambda p: _norm(p["name"]), False),
                  "worn": (lambda p: p["wear_count"] or 0, True),
                  "least_worn": (lambda p: (p["wear_count"] or 0, p["last_worn"] or ""), False),
                  "last_worn": (lambda p: p["last_worn"] or "", True)}
        keyfn, rev = orders.get(sort, orders["recent"])
        items.sort(key=lambda x: keyfn(x[1]), reverse=rev)
        items.sort(key=lambda x: -x[0])
        total = len(items)
        rows = [i for _, i in items][max(0, offset): max(0, offset) + max(1, min(limit, 2000))]
        return {"total": total, "items": rows}

    def _haystack(self, p: dict, cats: dict[str, dict]) -> str:
        colors = self.vocab_map("color")
        parts = [p.get("name"), p.get("brand"), p.get("model"), p.get("size"), p.get("notes"),
                 (cats.get(p.get("category") or "") or {}).get("label"), (cats.get(p.get("subcategory") or "") or {}).get("label"),
                 *[c.get("name") for c in p.get("colors") or []],
                 *[(colors.get(c.get("key") or "") or {}).get("label") for c in p.get("colors") or []],
                 *[m.get("name") for m in p.get("materials") or []], *(p.get("styles") or []), *(p.get("occasions") or []),
                 *(p.get("tags") or []), *[domain.SEASONS.get(s, s) for s in p.get("seasons") or []],
                 domain.STATUSES.get(p.get("status") or ""), p.get("pattern")]
        return _norm(" ".join(str(x) for x in parts if x))

    def piece_detail(self, id: str) -> dict:
        cats = self.vocab_map("category")
        raw = {p["id"]: p for p in self._pieces_raw()}
        if id not in raw:
            raise NotFound("capo non trovato")
        wears = self._wears()
        use = stats_mod.usage(list(raw.values()), wears)
        out = self._decorate(raw[id], use, cats)
        out["outfits"] = [{"id": o["id"], "name": o["name"], "favorite": o.get("favorite"), "photo": self._outfit_cover(o, raw)}
                          for o in self.store.items("outfit") if o.get("status") != "archived"
                          and id in [s["piece_id"] for s in o.get("slots") or []]]
        out["wears"] = [{"id": w["id"], "date": w["date"], "outfit_id": w.get("outfit_id")}
                        for w in reversed(wears) if id in (w.get("piece_ids") or [])][:20]
        return out

    def save_piece(self, data: dict, id: str | None = None, *, partial: bool = False) -> dict:
        cats = self.vocab_map("category")
        current = self.store.data("piece", id) if id else None
        if id and partial and not current:
            raise NotFound("capo non trovato")
        data = self._tag_keys(data)
        merged = {**(current or {}), **{k: v for k, v in data.items() if v is not None}} if partial else data
        if partial and "purchase" in data and isinstance(data["purchase"], dict):
            merged["purchase"] = {**(current or {}).get("purchase", {}), **data["purchase"]}
        clean = domain.piece(merged, cats, self.vocab_map("color"))
        pid = id or domain.new_id()
        clean["created_at"] = (current or {}).get("created_at") or now_iso()
        clean["updated_at"] = now_iso()
        clean["photos"] = [p for p in clean["photos"] if self.store.get("photo", p)]
        at = clean["purchase"].get("date")
        self.store.upsert("piece", pid, clean, at=f"{at}T00:00:00+00:00" if at else None)
        return self.piece_detail(pid)

    def delete_piece(self, id: str, *, hard: bool = False) -> dict:
        p = self.get("piece", id)
        if not hard:
            self.save_piece({"status": "archived"}, id, partial=True)
            return {"id": id, "archived": True, "name": p["name"]}
        for ph in p.get("photos") or []:
            self._drop_photo(ph)
        self.store.delete("piece", id)
        return {"id": id, "deleted": True, "name": p["name"]}

    def bulk(self, ids: list[str], changes: dict) -> dict:
        allowed = {k: v for k, v in changes.items() if k in ("status", "location", "favorite", "condition")}
        if not allowed:
            raise Invalid("niente da cambiare (status, location, favorite, condition)")
        done = []
        for pid in ids:
            if self.store.get("piece", pid):
                self.save_piece(allowed, pid, partial=True)
                done.append(pid)
        return {"updated": len(done), "ids": done}

    def find_piece(self, text: str) -> dict | None:
        """Best match for a name the assistant or the user typed ("camicia azzurra")."""
        if not text:
            return None
        if self.store.get("piece", text):
            return self.store.data("piece", text)
        found = self.pieces(q=text, sort="recent", limit=5)["items"]
        exact = [p for p in found if _norm(p["name"]) == _norm(text)]
        return (exact or found or [None])[0]

    # ── outfits ────────────────────────────────────────────────────────────
    def _outfit_cover(self, o: dict, pieces: dict[str, dict]) -> str | None:
        if o.get("photos"):
            return o["photos"][0]
        for s in o.get("slots") or []:
            ph = (pieces.get(s["piece_id"]) or {}).get("photos") or []
            if ph and s["slot"] in ("top", "onepiece", "outer"):
                return ph[0]
        for s in o.get("slots") or []:
            ph = (pieces.get(s["piece_id"]) or {}).get("photos") or []
            if ph:
                return ph[0]
        return None

    def _outfit_view(self, o: dict, pieces: dict[str, dict], last: dict[str, str], counts: dict[str, int]) -> dict:
        slot_rows = []
        review = False
        for s in o.get("slots") or []:
            p = pieces.get(s["piece_id"])
            if not p:
                review = True
                continue
            if p.get("status") in ("donated", "sold", "archived"):
                review = True
            slot_rows.append({"slot": s["slot"], "slot_label": domain.SLOTS.get(s["slot"], s["slot"]), "id": p["id"],
                              "name": p["name"], "photo": (p.get("photos") or [None])[0], "colors": p.get("colors") or [],
                              "status": p.get("status"), "available": p.get("status") == "active"})
        return {**o, "pieces": slot_rows, "cover": self._outfit_cover(o, pieces), "last_worn": last.get(o["id"]),
                "wear_count": counts.get(o["id"], 0), "complete": not review,
                "available": all(r["available"] for r in slot_rows if r["slot"] != "accessory")}

    def outfits(self, *, q: str = "", season: str = "", occasion: str = "", style: str = "", favorite: bool | None = None,
                include_archived: bool = False, sort: str = "recent", limit: int = 300, offset: int = 0) -> dict:
        pieces = {p["id"]: p for p in self.store.items("piece")}
        last, counts = self._outfit_usage()
        terms = [t for t in _norm(q).split(" ") if t]
        rows = []
        for o in self.store.items("outfit"):
            if not include_archived and o.get("status") == "archived":
                continue
            if season and season not in (o.get("seasons") or []):
                continue
            if occasion and occasion not in (o.get("occasions") or []):
                continue
            if style and style not in (o.get("styles") or []):
                continue
            if favorite is not None and bool(o.get("favorite")) != favorite:
                continue
            if terms:
                hay = _norm(" ".join([o.get("name") or "", o.get("notes") or "", *(o.get("occasions") or []), *(o.get("styles") or []),
                                      *[(pieces.get(s["piece_id"]) or {}).get("name", "") for s in o.get("slots") or []]]))
                if not all(t in hay for t in terms):
                    continue
            rows.append(self._outfit_view(o, pieces, last, counts))
        keys = {"recent": lambda o: o.get("created_at") or "", "name": lambda o: _norm(o["name"]),
                "worn": lambda o: o["wear_count"], "least_recent": lambda o: o["last_worn"] or "",
                "rating": lambda o: o.get("rating") or 0}
        rows.sort(key=keys.get(sort, keys["recent"]), reverse=sort in ("recent", "worn", "rating"))
        if sort == "favorites":
            rows.sort(key=lambda o: not o.get("favorite"))
        return {"total": len(rows), "items": rows[offset: offset + max(1, min(limit, 1000))]}

    def _outfit_usage(self) -> tuple[dict[str, str], dict[str, int]]:
        last: dict[str, str] = {}
        counts: dict[str, int] = {}
        for w in self._wears():
            oid = w.get("outfit_id")
            if oid:
                counts[oid] = counts.get(oid, 0) + 1
                if w["date"] > last.get(oid, ""):
                    last[oid] = w["date"]
        return last, counts

    def outfit_detail(self, id: str) -> dict:
        o = self.get("outfit", id)
        pieces = {p["id"]: p for p in self.store.items("piece")}
        last, counts = self._outfit_usage()
        out = self._outfit_view(o, pieces, last, counts)
        out["wears"] = [{"id": w["id"], "date": w["date"]} for w in reversed(self._wears()) if w.get("outfit_id") == id][:20]
        return out

    def save_outfit(self, data: dict, id: str | None = None, *, partial: bool = False) -> dict:
        current = self.store.data("outfit", id) if id else None
        if id and partial and not current:
            raise NotFound("outfit non trovato")
        data = self._tag_keys(data)
        merged = {**(current or {}), **{k: v for k, v in data.items() if v is not None}} if partial else data
        pieces = {p["id"]: p for p in self._pieces_raw()}
        clean = domain.outfit(merged, pieces)
        clean["photos"] = [p for p in clean["photos"] if self.store.get("photo", p)]
        oid = id or domain.new_id()
        clean["created_at"] = (current or {}).get("created_at") or now_iso()
        clean["updated_at"] = now_iso()
        self.store.upsert("outfit", oid, clean)
        return self.outfit_detail(oid)

    def delete_outfit(self, id: str, *, hard: bool = False) -> dict:
        o = self.get("outfit", id)
        if not hard:
            self.save_outfit({"status": "archived"}, id, partial=True)
            return {"id": id, "archived": True, "name": o["name"]}
        self.store.delete("outfit", id)
        return {"id": id, "deleted": True, "name": o["name"]}

    def find_outfit(self, text: str) -> dict | None:
        if not text:
            return None
        if self.store.get("outfit", text):
            return self.store.data("outfit", text)
        found = self.outfits(q=text, limit=5)["items"]
        exact = [o for o in found if _norm(o["name"]) == _norm(text)]
        return (exact or found or [None])[0]

    # ── wears ("Indossato") ────────────────────────────────────────────────
    def wears(self, *, date_from: str = "", date_to: str = "", limit: int = 200) -> dict:
        pieces = {p["id"]: p for p in self.store.items("piece")}
        outfits = {o["id"]: o for o in self.store.items("outfit")}
        rows = [w for w in reversed(self._wears()) if (not date_from or w["date"] >= date_from) and (not date_to or w["date"] <= date_to)]
        return {"total": len(rows), "items": [{**w, "outfit_name": (outfits.get(w.get("outfit_id") or "") or {}).get("name"),
                                               "pieces": [{"id": pid, "name": (pieces.get(pid) or {}).get("name", "?"),
                                                           "photo": ((pieces.get(pid) or {}).get("photos") or [None])[0]}
                                                          for pid in w.get("piece_ids") or []]} for w in rows[:limit]]}

    def mark_worn(self, data: dict) -> dict:
        pieces = {p["id"]: p for p in self.store.items("piece")}
        outfits = {o["id"]: o for o in self.store.items("outfit")}
        clean = domain.wear(data, pieces, outfits, self.today())
        dup = next((w for w in self._wears() if w["date"] == clean["date"] and clean["outfit_id"]
                    and w.get("outfit_id") == clean["outfit_id"]), None)
        if dup:                                       # tapping twice the same day is one mark
            return {**dup, "already": True, "label": self._wear_label(dup, outfits, pieces)}
        clean["created_at"] = now_iso()
        wid = domain.new_id()
        self.store.upsert("wear", wid, clean, parent_id=clean["outfit_id"], at=f"{clean['date']}T12:00:00+00:00")
        self._close_reminder()
        return {**clean, "id": wid, "label": self._wear_label(clean, outfits, pieces)}

    def _wear_label(self, w: dict, outfits: dict, pieces: dict) -> str:
        name = (outfits.get(w.get("outfit_id") or "") or {}).get("name") or \
            " + ".join((pieces.get(p) or {}).get("name", "?") for p in (w.get("piece_ids") or [])[:3])
        return f"{name} indossato" + ("" if w["date"] == self.today().isoformat() else f" il {w['date']}")

    def delete_wear(self, id: str) -> dict:
        self.get("wear", id)
        self.store.delete("wear", id)
        return {"id": id, "deleted": True}

    def unmark_outfit(self, outfit_id: str, day: str = "") -> dict:
        day = domain.iso_date(day) or self.today().isoformat()
        rows = [w for w in self._wears() if w.get("outfit_id") == outfit_id and w["date"] == day]
        if not rows:
            raise NotFound("niente da annullare")
        self.store.delete("wear", rows[-1]["id"])
        return {"id": rows[-1]["id"], "deleted": True}

    # ── goal (optional, SPEC §4.3 v1.5) ────────────────────────────────────
    def goal(self) -> dict | None:
        times = int(self.cfg("tracking.goal_times", 0) or 0)
        per = str(self.cfg("tracking.goal_per", "week") or "week")
        if times <= 0 or per not in PER_LABEL:
            return None
        return {"times": times, "per": per}

    def _period_start(self, d: date, per: str) -> date:
        if per == "day":
            return d
        if per == "month":
            return d.replace(day=1)
        first = 6 if self.personal(WEEK_START_KEY, "monday") == "sunday" else 0
        return d - timedelta(days=(d.weekday() - first) % 7)

    def _period_next(self, start: date, per: str) -> date:
        if per == "day":
            return start + timedelta(days=1)
        if per == "month":
            return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start + timedelta(days=7)

    def goal_progress(self) -> dict | None:
        g = self.goal()
        if not g:
            return None
        today = self.today()
        start = self._period_start(today, g["per"])
        days = {w["date"] for w in self._wears() if w["date"] >= start.isoformat()}
        done = len(days)                               # one mark per day counts once
        remaining = max(0, g["times"] - done)
        days_left = (self._period_next(start, g["per"]) - today).days
        return {**g, "done": done, "remaining": remaining, "met": done >= g["times"], "days_left": days_left,
                "behind": remaining > 0 and remaining >= days_left, "marked_today": today.isoformat() in days,
                "hint": f"{done}/{g['times']} {PER_LABEL[g['per']]}"}

    # ── suggestions ────────────────────────────────────────────────────────
    def suggester(self) -> Suggester:
        return Suggester(self._pieces_raw(), self.store.items("outfit"), self._wears(), today=self.today(),
                         forgotten_days=int(self.cfg("forgotten_days", 180)))

    def suggest(self, *, day: str = "", occasion: str = "", styles: list[str] | str | None = None,
                temp_c: float | None = None, rain: bool = False, count: int | None = None,
                exclude_recent_days: int | None = None) -> dict:
        d = date.fromisoformat(domain.iso_date(day)) if day else self.today()
        styles = self.vocab_keys("style", styles) or []
        occasion = (self.vocab_keys("occasion", [occasion]) or [""])[0] if occasion else ""
        out = self.suggester().suggest(day=d, occasion=occasion, styles=styles, temp_c=temp_c,
                                       rain=bool(rain), count=int(count or self.cfg("suggest.count", 3)),
                                       recent_days=int(exclude_recent_days if exclude_recent_days is not None
                                                       else self.cfg("suggest.exclude_recent_days", 4)))
        if not out["items"]:
            out["hint"] = ("Aggiungi qualche capo (almeno uno sopra, uno sotto e delle scarpe) per avere suggerimenti"
                           if out["available_pieces"] < 3 else "Nessuna combinazione adatta: prova senza occasione o con un'altra temperatura")
        return out

    def save_suggestion(self, slots: list[dict], name: str = "", source: str = "user") -> dict:
        return self.save_outfit({"name": name, "slots": slots, "source": source})

    # ── stats & summary ────────────────────────────────────────────────────
    def stats(self) -> dict:
        return stats_mod.compute(self._pieces_raw(), self.store.items("outfit"), self._wears(), self.vocab_map("category"),
                                 self.vocab_map("color"), self.today(), int(self.cfg("forgotten_days", 180)),
                                 self.currency())

    def summary(self) -> dict:
        s = self.stats()
        t = s["totals"]
        laundry = [p for p in self.store.items("piece") if p.get("status") == "laundry"]
        styles = s["by_style"][:2]
        last = (self.wears(limit=1)["items"] or [None])[0]
        parts = [f"{t['garments']} capi, {t['shoes']} scarpe, {t['accessories']} accessori, {t['outfits']} outfit"]
        if styles:
            parts.append("stile " + "/".join(x["key"].replace("_", " ") for x in styles))
        if laundry:
            parts.append(f"in lavanderia {len(laundry)}")
        if s["forgotten"]:
            parts.append(f"dimenticati >{int(self.cfg('forgotten_days', 180))}g: {len(s['forgotten'])}")
        if last:
            parts.append(f"ultimo indossato {last['date'][8:10]}/{last['date'][5:7]} {last.get('outfit_name') or ''}".strip())
        g = self.goal_progress()
        if g:
            parts.append(f"obiettivo {g['hint']}")
        if t["wishlist"]:
            parts.append(f"wishlist {t['wishlist']}")
        return {"text": " · ".join(parts), "totals": t, "laundry": [p["name"] for p in laundry][:10],
                "forgotten": [f["name"] for f in s["forgotten"][:8]], "gaps": s["gaps"], "goal": g,
                "favorite_outfits": [o["name"] for o in self.outfits(favorite=True, limit=8)["items"]]}

    def context(self, budget: int = 400) -> dict:
        text = "Guardaroba: " + self.summary()["text"]
        if len(text) > budget:
            text = text[: max(40, budget - 1)].rsplit(" · ", 1)[0] + "…"
        return {"module": "wardrobe", "domain": "wardrobe", "updated_at": now_iso(), "text": text}

    # ── quick actions (WebUI Home) ─────────────────────────────────────────
    def quick_chips(self, limit: int = 6) -> list[dict]:
        """Favourite outfits first (least recently marked first), then today's best suggestion."""
        today = self.today().isoformat()
        g = self.goal_progress()
        marked = {w.get("outfit_id") for w in self._wears() if w["date"] == today}
        favs = [o for o in self.outfits(favorite=True, sort="least_recent", limit=limit)["items"] if o["available"]]
        chips = [{"id": o["id"], "label": o["name"], "icon": "check" if o["id"] in marked else "star",
                  "state": "done" if o["id"] in marked else "todo", "favorite": True,
                  **({"hint": g["hint"]} if g else {})} for o in favs]
        if len(chips) < limit:
            try:
                sugg = self.suggest(count=1)["items"]
            except Exception:
                sugg = []
            for s in sugg:
                if s.get("outfit_id") and s["outfit_id"] in {c["id"] for c in chips}:
                    continue
                cid = s["outfit_id"] or "s:" + ",".join(x["piece_id"] for x in s["slots"])
                chips.append({"id": cid, "label": s["name"], "icon": "sparkle", "state": "done" if cid in marked else "todo",
                              "hint": "suggerito oggi" + (f" · {g['hint']}" if g else "")})
        return chips[:limit]

    def quick_mark(self, chip_id: str, day: str | None = None, note: str = "", source: str = "webui") -> dict:
        if chip_id.startswith("s:"):                    # a generated suggestion: mark its pieces
            return self.mark_worn({"piece_ids": chip_id[2:].split(","), "date": day, "note": note, "source": source})
        return self.mark_worn({"outfit_id": chip_id, "date": day, "note": note, "source": source})

    def quick_undo(self, chip_id: str, day: str = "") -> dict:
        day = domain.iso_date(day) or self.today().isoformat()
        if chip_id.startswith("s:"):
            ids = set(chip_id[2:].split(","))
            rows = [w for w in self._wears() if w["date"] == day and set(w.get("piece_ids") or []) == ids]
            if not rows:
                raise NotFound("niente da annullare")
            self.store.delete("wear", rows[-1]["id"])
            return {"deleted": True}
        return self.unmark_outfit(chip_id, day)

    # ── reminder (agenda job; off by default) ──────────────────────────────
    def reminder_decision(self) -> dict:
        if not self.cfg("reminder.enabled", False):
            return {"send": False, "why": "disabled"}
        g = self.goal_progress()
        if not g:
            return {"send": False, "why": "no_goal"}
        if g["marked_today"]:
            return {"send": False, "why": "done_today"}
        if g["met"]:
            return {"send": False, "why": "on_track"}
        if g["per"] != "day" and not g["behind"]:
            return {"send": False, "why": "not_behind"}
        week0 = self._period_start(self.today(), "week").isoformat()
        sent = [r for r in self.store.items("reminder") if self._local_day(r.get("at")) >= week0]
        if any(self._local_day(r.get("at")) == self.today().isoformat() for r in sent):
            return {"send": False, "why": "sent_today"}       # one nudge a day, like every module
        if len(sent) >= int(self.cfg("reminder.max_per_week", 2)):
            return {"send": False, "why": "weekly_cap"}
        return {"send": True, "goal": g, "chips": [c for c in self.quick_chips(3)]}

    def mark_reminder_sent(self) -> None:
        self.store.write([{"kind": "reminder", "id": domain.new_id(), "at": now_iso(), "data": {"at": now_iso()}}])

    def _close_reminder(self) -> None:
        """Marking from anywhere closes the live reminder (Hermes ``closes``)."""
        week_ago = (self.today() - timedelta(days=7)).isoformat()
        if not any(self._local_day(r.get("at")) >= week_ago for r in self.store.items("reminder")):
            return                                    # no live reminder to close
        try:
            self.hub.call("hermes", "POST", "api/events/ingest", body={
                "event_type": "service.action_required", "domain": "wardrobe", "entity_id": "wardrobe.reminder",
                "payload": {"closes": "wardrobe.reminder", "decision": "done", "outcome_text": "Outfit segnato",
                            "_source": "wardrobe"}}, timeout=5)
        except Exception as exc:
            logger.warning("[🔄] event=wardrobe_reminder_close_failed error=%s fallback=expires_on_its_own", exc)

    # ── photos ─────────────────────────────────────────────────────────────
    def add_photo(self, owner_kind: str, owner_id: str, upload: dict, *, cover: bool = False) -> dict:
        if owner_kind not in ("piece", "outfit"):
            raise Invalid("le foto vanno su un capo o un outfit")
        owner = self.get(owner_kind, owner_id)
        raw, _mime = photos.decode(upload, float(self.cfg("photo.max_mb", 10)))
        try:
            parts = photos.process(raw)
        except photos.PhotoError as exc:
            raise Invalid(str(exc))
        ids = {}
        for size in ("original", "medium", "thumb"):
            data, mime = parts[size]
            r = self.hub.ok("archive", "POST", "api/blobs", body={
                "owner_module": "wardrobe", "content_type": mime, "data_base64": base64.b64encode(data).decode(),
                "meta": {"size": size, "owner": f"{owner_kind}:{owner_id}"}}, timeout=30)
            ids[size] = r["blob_id"]
        pid = domain.new_id()
        self.store.upsert("photo", pid, {**ids, "owner": f"{owner_kind}:{owner_id}", "width": parts.get("width"),
                                         "height": parts.get("height"), "name": str(upload.get("name") or "")[:80],
                                         "created_at": now_iso()}, ref_id=owner_id)
        photos_list = [p for p in owner.get("photos") or [] if p != pid]
        photos_list = [pid, *photos_list] if cover or not photos_list else [*photos_list, pid]
        saver = self.save_piece if owner_kind == "piece" else self.save_outfit
        return {"photo_id": pid, "item": saver({"photos": photos_list}, owner_id, partial=True)}

    def remove_photo(self, owner_kind: str, owner_id: str, photo_id: str) -> dict:
        owner = self.get(owner_kind, owner_id)
        saver = self.save_piece if owner_kind == "piece" else self.save_outfit
        item = saver({"photos": [p for p in owner.get("photos") or [] if p != photo_id]}, owner_id, partial=True)
        self._drop_photo(photo_id)
        return {"removed": photo_id, "item": item}

    def set_cover(self, owner_kind: str, owner_id: str, photo_id: str) -> dict:
        owner = self.get(owner_kind, owner_id)
        if photo_id not in (owner.get("photos") or []):
            raise NotFound("foto non trovata")
        saver = self.save_piece if owner_kind == "piece" else self.save_outfit
        return saver({"photos": [photo_id] + [p for p in owner["photos"] if p != photo_id]}, owner_id, partial=True)

    def _drop_photo(self, photo_id: str) -> None:
        ph = self.store.data("photo", photo_id)
        if not ph:
            return
        others = [p for p in self.store.items("photo") if p["id"] != photo_id]
        for size in ("original", "medium", "thumb"):
            bid = ph.get(size)
            if bid and not any(bid in (o.get("original"), o.get("medium"), o.get("thumb")) for o in others):
                try:
                    self.hub.call("archive", "DELETE", f"api/blobs/{bid}", timeout=10)
                except Exception as exc:
                    logger.warning("[🔄] event=wardrobe_blob_delete_failed blob=%s error=%s fallback=orphan_kept", bid, exc)
        self.store.delete("photo", photo_id)

    def photo_file(self, photo_id: str, size: str = "thumb") -> dict:
        ph = self.get("photo", photo_id)
        bid = ph.get(size if size in ("original", "medium", "thumb") else "thumb") or ph.get("original")
        r = self.hub.ok("archive", "GET", f"api/blobs/{bid}/base64", timeout=20)
        return {"mime": r["mime"], "data_b64": r["data_b64"]}

    # ── AI description of a photo (through Oracle only) ────────────────────
    def describe_photo(self, upload: dict) -> dict:
        """Photo → proposed piece fields. Never saves: the user reviews them in the add form."""
        raw, mime = photos.decode(upload, float(self.cfg("photo.max_mb", 10)))
        try:
            medium = photos.process(raw)["medium"]
            raw, mime = medium
        except photos.PhotoError as exc:
            raise Invalid(str(exc))
        cats = [c for c in self.vocab("category", hidden=False)]
        catalog = {
            "category": [f"{c['key']}" + (f"<{c['parent']}" if c.get("parent") else "") for c in cats],
            "color": [c["key"] for c in self.vocab("color", hidden=False)],
            "pattern": [c["key"] for c in self.vocab("pattern", hidden=False)],
            "style": [c["key"] for c in self.vocab("style", hidden=False)],
            "fit": [c["key"] for c in self.vocab("fit", hidden=False)],
        }
        prompt = ("Capo d'abbigliamento in foto. Rispondi SOLO JSON: {\"name\": nome breve italiano (es. \"Camicia Oxford azzurra\"), "
                  "\"kind\": garment|shoes|accessory, \"category\": chiave (sottocategoria se c'è), \"colors\": [chiavi, principale prima], "
                  "\"pattern\", \"materials\": [nomi], \"styles\": [chiavi], \"seasons\": [spring|summer|autumn|winter], "
                  "\"warmth\": 1-5, \"formality\": 1-5, \"fit\", \"brand\": se leggibile o \"\"}. Valori ammessi: "
                  + json.dumps(catalog, ensure_ascii=False))
        body = {"use_case": "wardrobe.foto", "temperature": 0.1, "max_tokens": 500,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}}]}]}
        try:
            out = self.hub.ok("oracle", "POST", "api/llm/chat", body=body, timeout=90)
            text = ((out or {}).get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if isinstance(text, list):
                text = " ".join(str(t.get("text", "")) for t in text if isinstance(t, dict))
            m = re.search(r"\{.*\}", text, re.S)
            guess = json.loads(m.group(0)) if m else {}
        except Exception as exc:
            logger.warning("[🔄] event=wardrobe_describe_failed error=%s fallback=manual_form", exc)
            return {"ok": False, "fields": {}, "message": "L'AI non è disponibile ora: compila a mano"}
        fields: dict[str, Any] = {}
        catmap = self.vocab_map("category")
        for k in ("name", "brand"):
            if isinstance(guess.get(k), str) and guess[k].strip():
                fields[k] = guess[k].strip()[:120]
        key = domain.slug(guess.get("category"))
        if key in catmap:
            c = catmap[key]
            fields["category"], fields["subcategory"] = (c["parent"], key) if c.get("parent") else (key, "")
            fields["kind"] = c.get("kind") or "garment"
        for k, vocab in (("pattern", "pattern"), ("fit", "fit")):
            if domain.slug(guess.get(k)) in self.vocab_map(vocab):
                fields[k] = domain.slug(guess[k])
        colors = [domain.slug(c) for c in guess.get("colors") or [] if isinstance(c, str)]
        fields["colors"] = [c for c in colors if c in self.vocab_map("color")][:3]
        fields["styles"] = [s for s in (domain.slug(x) for x in guess.get("styles") or []) if s in self.vocab_map("style")][:3]
        fields["seasons"] = [s for s in guess.get("seasons") or [] if s in domain.SEASONS]
        fields["materials"] = [{"name": str(m).lower()[:40]} for m in guess.get("materials") or [] if isinstance(m, str)][:4]
        for k in ("warmth", "formality"):
            try:
                fields[k] = max(1, min(5, int(guess.get(k))))
            except (TypeError, ValueError):
                pass
        return {"ok": True, "fields": {k: v for k, v in fields.items() if v not in (None, [], "")},
                "message": "Controlla i campi proposti e salva"}

    # ── collections (capsule, packing lists, shopping) ─────────────────────
    def collections(self, *, type: str = "", include_archived: bool = False) -> dict:
        pieces = {p["id"]: p for p in self.store.items("piece")}
        outfits = {o["id"]: o for o in self.store.items("outfit")}
        rows = []
        for c in self.store.items("collection"):
            if type and c.get("type") != type:
                continue
            if c.get("archived") and not include_archived:
                continue
            rows.append(self._collection_view(c, pieces, outfits))
        rows.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
        return {"total": len(rows), "items": rows}

    def _collection_view(self, c: dict, pieces: dict, outfits: dict) -> dict:
        total = len(c.get("piece_ids") or []) + len(c.get("outfit_ids") or []) + len(c.get("items") or [])
        return {**c, "type_label": domain.COLLECTION_TYPES.get(c.get("type") or "", ""),
                "pieces": [{"id": p, "name": pieces[p]["name"], "photo": (pieces[p].get("photos") or [None])[0],
                            "checked": p in (c.get("checked") or [])} for p in c.get("piece_ids") or [] if p in pieces],
                "outfits": [{"id": o, "name": outfits[o]["name"], "checked": o in (c.get("checked") or [])}
                            for o in c.get("outfit_ids") or [] if o in outfits],
                "progress": {"checked": len(c.get("checked") or []), "total": total}}

    def collection_detail(self, id: str) -> dict:
        c = self.get("collection", id)
        return self._collection_view(c, {p["id"]: p for p in self.store.items("piece")},
                                     {o["id"]: o for o in self.store.items("outfit")})

    def save_collection(self, data: dict, id: str | None = None, *, partial: bool = False) -> dict:
        current = self.store.data("collection", id) if id else None
        if id and partial and not current:
            raise NotFound("lista non trovata")
        merged = {**(current or {}), **{k: v for k, v in data.items() if v is not None}} if partial else data
        clean = domain.collection(merged, {p["id"]: p for p in self.store.items("piece")},
                                  {o["id"]: o for o in self.store.items("outfit")})
        cid = id or domain.new_id()
        clean["created_at"] = (current or {}).get("created_at") or now_iso()
        clean["updated_at"] = now_iso()
        self.store.upsert("collection", cid, clean)
        return self.collection_detail(cid)

    def toggle_check(self, id: str, item_id: str, checked: bool | None = None) -> dict:
        c = self.get("collection", id)
        cur = list(c.get("checked") or [])
        on = (item_id not in cur) if checked is None else checked
        cur = [x for x in cur if x != item_id] + ([item_id] if on else [])
        return self.save_collection({"checked": cur}, id, partial=True)

    def delete_collection(self, id: str) -> dict:
        c = self.get("collection", id)
        self.store.delete("collection", id)
        return {"id": id, "deleted": True, "name": c["name"]}

    def packing(self, *, name: str = "", date_from: str = "", date_to: str = "", place: str = "", occasion: str = "",
                temp_c: float | None = None, rain: bool = False) -> dict:
        """Proposed packing list for a trip: one outfit per day (max 7, then repeat), shoes and outerwear once."""
        d0 = date.fromisoformat(domain.iso_date(date_from) or self.today().isoformat())
        d1 = date.fromisoformat(domain.iso_date(date_to) or d0.isoformat())
        if d1 < d0:
            raise Invalid("la fine viaggio è prima dell'inizio")
        days = min(7, (d1 - d0).days + 1)
        occasion = (self.vocab_keys("occasion", [occasion]) or [""])[0] if occasion else ""
        sug = self.suggester().suggest(day=d0, occasion=occasion, temp_c=temp_c, rain=rain, count=days,
                                       recent_days=0)
        outfit_ids, piece_ids = [], []
        for s in sug["items"]:
            if s.get("outfit_id"):
                outfit_ids.append(s["outfit_id"])
            for x in s["slots"]:
                if x["piece_id"] not in piece_ids:
                    piece_ids.append(x["piece_id"])
        return self.save_collection({"name": name or f"Valigia {place or d0.strftime('%d/%m')}".strip(), "type": "packing",
                                     "piece_ids": piece_ids, "outfit_ids": outfit_ids,
                                     "trip": {"from": d0.isoformat(), "to": d1.isoformat(), "place": place}})

    # ── export / import ────────────────────────────────────────────────────
    def export(self) -> dict:
        data = {k: self.store.items(k) for k in ("piece", "outfit", "wear", "collection", "photo")}
        data["taxonomy"] = self.vocabularies()
        return {"filename": f"guardaroba-{self.today().isoformat()}.json", "mime": "application/json",
                "text": json.dumps({"module": "wardrobe", "version": 1, "exported_at": now_iso(), "data": data},
                                   ensure_ascii=False, indent=1)}

    def import_json(self, text: str) -> dict:
        """Merge an export (same ids replace, new ids are added). Photos keep only their metadata rows."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise Invalid(f"JSON non valido: {exc}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise Invalid("file di esportazione non riconosciuto")
        counts = {}
        for name, values in (data.get("taxonomy") or {}).items():
            if name in domain.DEFAULT_VOCABULARIES:
                self.store.upsert("taxonomy", name, {"values": domain.vocabulary(name, values)})
        for kind in ("photo", "piece", "outfit", "collection", "wear"):
            rows = []
            for item in data.get(kind) or []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                rows.append({"kind": kind, "id": str(item["id"]), "data": {k: v for k, v in item.items() if k != "id"}})
            if rows:
                self.store.write(rows)
            counts[kind] = len(rows)
        return {"imported": counts}
