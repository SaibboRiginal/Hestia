"""Hygieia service: products, routines (versioned), logs, journal, planner, statistics, alerts, reminders.

Pure domain logic over the Store mirror; HTTP, tools, plugin and Hermes calls live in ``app.main``.
SPEC docs/work/2026-10-17-selfcare-module.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import catalog
from .catalog import LEVEL_VALUE
from .planner import DONE_STATUSES, Day, cadence_label, conflict_notes, goal_state, norm_cadence, period_next, period_start
from .store import Store, now_iso, parse_dt


class Invalid(ValueError):
    pass


class NotFound(LookupError):
    pass


WEEK_START_KEY = "themis.personal.week_start"   # personal settings shared by every module (owner Themis)
CURRENCY_KEY = "themis.personal.currency"


class Conflict(RuntimeError):
    def __init__(self, message: str, **detail):
        super().__init__(message)
        self.detail = detail


PRODUCT_FIELDS = ("name", "brand", "line", "areas", "category", "actives", "inci", "size", "unit", "price", "currency",
                  "shop", "url", "status", "purchased_at", "opened_at", "finished_at", "pao_months", "expires_at",
                  "level", "rating", "verdict", "favorite", "photo_id", "barcode", "tags", "notes", "replaces_id")
ROUTINE_FIELDS = ("name", "areas", "slot", "cadence", "max_per_day", "min_gap_hours", "not_same_day_as", "reminder",
                  "status", "order", "favorite", "icon", "color", "notes")
STEP_FIELDS = ("id", "order", "product_id", "label", "amount", "wait_seconds", "cadence", "not_same_day_as",
               "optional", "note", "paused_until")


def new_id() -> str:
    return uuid.uuid4().hex


def _day(value: Any) -> str | None:
    """'2026-10-18' from a date / ISO datetime / '' (None)."""
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    s = str(value)
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            pass
    raise Invalid(f"data non valida: {value!r}")


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        raise Invalid(f"numero non valido: {value!r}")


def _list(value: Any) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return list(value)


class Hygieia:
    def __init__(self, store: Store, setting: Callable[[str], Any], tz_name: str | None = None):
        self.store = store
        self._setting = setting
        self.tz = ZoneInfo(tz_name or "Europe/Rome")

    # ── basics ──────────────────────────────────────────────────────────────
    def setting(self, key: str, default: Any = None) -> Any:
        try:
            v = self._setting(key)
        except Exception:
            v = None
        return default if v is None else v

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def week_start(self) -> int:
        return 6 if self.setting(WEEK_START_KEY, "monday") == "sunday" else 0

    def local_date(self, value: Any) -> date | None:
        dt = parse_dt(value)
        return dt.astimezone(self.tz).date() if dt else None

    def get(self, kind: str, id: str) -> dict:
        self.store.refresh()
        row = self.store.data(kind, id)
        if not row:
            raise NotFound(f"{kind} {id} non trovato")
        return row

    def items(self, kind: str) -> list[dict]:
        self.store.refresh()
        return self.store.items(kind)

    # ── lists (seeds + custom options) ──────────────────────────────────────
    def options(self, name: str) -> list[dict]:
        custom = [o for o in self.items("option") if o.get("list") == name and not o.get("archived")]
        base = {"areas": catalog.AREAS, "categories": catalog.CATEGORIES, "actives": catalog.ACTIVES,
                "conflicts": catalog.CONFLICTS, "tags": [{"value": t, "label": t} for t in catalog.JOURNAL_TAGS]}.get(name, [])
        if name == "metrics":
            out = {area: list(ms) for area, ms in catalog.METRICS.items()}
            for o in custom:
                out.setdefault(o.get("area") or "*", []).append({"value": o["value"], "label": o.get("label") or o["value"],
                                                                 "lower_better": bool(o.get("lower_better")), "custom": True})
            return out  # type: ignore[return-value]
        seen = {b.get("value") for b in base}
        return list(base) + [{**o, "custom": True} for o in custom if o.get("value") not in seen or name == "conflicts"]

    def add_option(self, name: str, body: dict) -> dict:
        if name not in catalog.LISTS:
            raise Invalid(f"lista sconosciuta: {name}")
        label = str(body.get("label") or body.get("value") or "").strip()
        if name == "conflicts":
            if not body.get("a") or not body.get("b"):
                raise Invalid("servono due attivi (a, b)")
            data = {"list": name, "a": catalog.slug(body["a"]), "b": catalog.slug(body["b"]),
                    "note": body.get("note") or f"{body['a']} e {body['b']} non nello stesso giorno"}
        else:
            if not label:
                raise Invalid("nome mancante")
            data = {"list": name, "value": catalog.slug(body.get("value") or label), "label": label}
            for k in ("family", "area", "icon", "lower_better"):
                if body.get(k) not in (None, ""):
                    data[k] = body[k]
        return self.store.upsert("option", new_id(), data)

    def meta(self) -> dict:
        return {"areas": self.options("areas"), "categories": self.options("categories"), "actives": self.options("actives"),
                "metrics": self.options("metrics"), "conflicts": self.options("conflicts"), "tags": self.options("tags"),
                "slots": catalog.SLOTS, "statuses": catalog.STATUSES, "levels": catalog.LEVELS, "verdicts": catalog.VERDICTS,
                "units": catalog.UNITS, "cadence_modes": catalog.CADENCE_MODES, "periods": catalog.PERIODS,
                "currency": self.setting(CURRENCY_KEY, "EUR"), "week_start": self.week_start()}

    # ── products ────────────────────────────────────────────────────────────
    def _actives(self, value: Any) -> list[dict]:
        out = []
        for a in _list(value):
            if isinstance(a, dict):
                name = catalog.slug(a.get("name") or a.get("value") or "")
                if name:
                    out.append({"name": name, **({"percent": _num(a["percent"])} if a.get("percent") not in (None, "") else {})})
            elif str(a).strip():
                out.append({"name": catalog.slug(str(a))})
        return out

    def save_product(self, body: dict, id: str | None = None, source: str = "webui") -> dict:
        old = self.store.data("product", id) if id else None
        p = {k: body[k] for k in PRODUCT_FIELDS if k in body}
        merged = {**(old or {}), **p}
        name = str(merged.get("name") or "").strip()
        if not name:
            raise Invalid("il nome del prodotto è obbligatorio")
        merged["name"] = name
        merged["brand"] = str(merged.get("brand") or "").strip()
        merged["areas"] = [catalog.slug(a) for a in _list(merged.get("areas"))]
        merged["actives"] = self._actives(merged.get("actives"))
        merged["tags"] = [str(t) for t in _list(merged.get("tags"))]
        status = merged.get("status") or "in_use"
        if status not in catalog.STATUSES:
            raise Invalid(f"stato non valido: {status}")
        merged["status"] = status
        if merged.get("level") and merged["level"] not in catalog.LEVELS:
            raise Invalid(f"livello non valido: {merged['level']}")
        if merged.get("verdict") and merged["verdict"] not in catalog.VERDICTS:
            raise Invalid(f"giudizio non valido: {merged['verdict']}")
        for k in ("size", "price", "pao_months", "rating"):
            merged[k] = _num(merged.get(k))
        if merged.get("rating") is not None and not 1 <= merged["rating"] <= 5:
            raise Invalid("voto da 1 a 5")
        for k in ("purchased_at", "opened_at", "finished_at", "expires_at"):
            merged[k] = _day(merged.get(k))
        if status == "in_use" and not merged.get("opened_at"):
            merged["opened_at"] = self.today().isoformat()
        if status in ("finished", "discarded") and not merged.get("finished_at"):
            merged["finished_at"] = self.today().isoformat()
        if status in ("stock", "in_use") and not merged.get("purchased_at") and not old:
            merged["purchased_at"] = self.today().isoformat()
        merged["favorite"] = bool(merged.get("favorite"))
        merged["unit"] = merged.get("unit") or "ml"
        merged["currency"] = merged.get("currency") or self.setting(CURRENCY_KEY, "EUR")
        merged["product_key"] = catalog.product_key(merged["brand"], name)
        merged.pop("id", None)
        pid = id or new_id()
        events = self._product_events(old, merged)
        self.store.write([{"kind": "product", "id": pid, "ref_id": merged["product_key"],
                           "at": merged.get("purchased_at") or merged.get("opened_at"), "data": merged}]
                         + [{"kind": "event", "id": new_id(), "parent_id": pid, "ref_id": e["type"], "at": now_iso(),
                             "data": {**e, "product_id": pid, "source": source}} for e in events])
        return self.product_detail(pid)

    def _product_events(self, old: dict | None, new: dict) -> list[dict]:
        today = self.today().isoformat()
        if not old:
            ev = [{"type": "bought" if new["status"] != "wishlist" else "note", "date": new.get("purchased_at") or today,
                   "text": "aggiunto" if new["status"] != "wishlist" else "in lista desideri"}]
            if new["status"] == "in_use":
                ev.append({"type": "opened", "date": new.get("opened_at") or today, "text": "aperto"})
            if new.get("replaces_id"):
                ev.append({"type": "replaced", "date": today, "text": "sostituisce un altro prodotto",
                           "replaces_id": new["replaces_id"]})
            return ev
        ev = []
        if old.get("status") != new["status"]:
            kind = {"in_use": "opened", "finished": "finished", "discarded": "discarded"}.get(new["status"], "status")
            ev.append({"type": kind, "date": today, "from": old.get("status"), "to": new["status"],
                       "text": catalog.STATUSES.get(new["status"], new["status"]).lower()})
        if old.get("level") != new.get("level") and new.get("level"):
            ev.append({"type": "level_changed", "date": today, "to": new["level"],
                       "text": catalog.LEVELS.get(new["level"], new["level"]).lower()})
        if old.get("rating") != new.get("rating") and new.get("rating"):
            ev.append({"type": "rated", "date": today, "to": new["rating"], "text": f"voto {int(new['rating'])}/5"})
        if old.get("verdict") != new.get("verdict") and new.get("verdict"):
            ev.append({"type": "rated", "date": today, "to": new["verdict"],
                       "text": catalog.VERDICTS.get(new["verdict"], new["verdict"]).lower()})
        return ev

    def set_status(self, id: str, status: str, day: str | None = None, source: str = "webui") -> dict:
        p = self.get("product", id)
        body: dict = {"status": status}
        d = _day(day) or self.today().isoformat()
        if status == "in_use" and not p.get("opened_at"):
            body["opened_at"] = d
        if status in ("finished", "discarded"):
            body["finished_at"] = d
        return self.save_product(body, id=id, source=source)

    def repurchase(self, id: str, body: dict | None = None, source: str = "webui") -> dict:
        p = self.get("product", id)
        new = {k: p.get(k) for k in PRODUCT_FIELDS if k not in ("status", "purchased_at", "opened_at", "finished_at",
                                                                 "expires_at", "level", "rating", "verdict", "replaces_id")}
        new.update({"status": "stock", "purchased_at": self.today().isoformat(), "level": "full"})
        new.update({k: v for k, v in (body or {}).items() if k in PRODUCT_FIELDS})
        return self.save_product(new, source=source)

    def delete_product(self, id: str) -> dict:
        self.get("product", id)
        self.store.delete("product", id)
        return {"deleted": True, "id": id}

    def _uses(self) -> dict[str, list[str]]:
        """product id → local days it was used (routine steps done + ad-hoc uses)."""
        out: dict[str, list[str]] = {}
        for l in self.items("log"):
            if l.get("status") not in DONE_STATUSES:
                continue
            for s in l.get("steps") or []:
                if s.get("done") and s.get("product_id"):
                    out.setdefault(s["product_id"], []).append(l["date"])
        return out

    def product_view(self, p: dict, uses: dict[str, list[str]] | None = None, routines: list[dict] | None = None) -> dict:
        today = self.today()
        uses = self._uses() if uses is None else uses
        mine = sorted(uses.get(p["id"], []))
        opened = date.fromisoformat(p["opened_at"]) if p.get("opened_at") else None
        expiry_candidates = []
        if p.get("expires_at"):
            expiry_candidates.append(date.fromisoformat(p["expires_at"]))
        pao = p.get("pao_months")
        if opened and (pao or p.get("status") == "in_use"):
            months = pao or self.setting("hygieia.default_pao_months", 12)
            expiry_candidates.append(opened + timedelta(days=int(round(float(months) * 30.4))))
        expiry = min(expiry_candidates) if expiry_candidates else None
        days_open = (today - opened).days if opened else None
        if p.get("status") in ("finished", "discarded") and opened and p.get("finished_at"):
            days_open = (date.fromisoformat(p["finished_at"]) - opened).days
        routines = self.items("routine") if routines is None else routines
        in_routines = [{"id": r["id"], "name": r.get("name")} for r in routines if r.get("status") != "archived"
                       and any(s.get("product_id") == p["id"] for s in r.get("steps") or [])]
        return {**p, "uses": len(mine), "last_used": mine[-1] if mine else None, "days_open": days_open,
                "expiry": expiry.isoformat() if expiry else None,
                "expires_in": (expiry - today).days if expiry else None,
                "finish_estimate": self._finish_estimate(p, days_open), "routines": in_routines,
                "status_label": catalog.STATUSES.get(p.get("status"), p.get("status")),
                "price_per_use": round(p["price"] / len(mine), 2) if p.get("price") and mine else None}

    def _finish_estimate(self, p: dict, days_open: int | None) -> dict | None:
        if p.get("status") != "in_use" or days_open is None:
            return None
        lives = []
        for o in self.items("product"):
            if o["id"] != p["id"] and o.get("product_key") == p.get("product_key") and o.get("status") == "finished" \
                    and o.get("opened_at") and o.get("finished_at"):
                lives.append((date.fromisoformat(o["finished_at"]) - date.fromisoformat(o["opened_at"])).days)
        today = self.today()
        if lives:
            avg = sum(lives) / len(lives)
            left = max(0, round(avg - days_open))
            return {"days_left": left, "date": (today + timedelta(days=left)).isoformat(),
                    "basis": f"media di {len(lives)} confezioni ({round(avg)} giorni)"}
        level = LEVEL_VALUE.get(p.get("level") or "")
        if level is not None and level < 1 and days_open >= 7:
            rate = (1 - level) / days_open
            left = round(level / rate) if rate > 0 else None
            if left is not None:
                return {"days_left": left, "date": (today + timedelta(days=left)).isoformat(),
                        "basis": f"livello «{catalog.LEVELS[p['level']].lower()}» dopo {days_open} giorni"}
        return None

    def products(self, q: str = "", area: str = "", category: str = "", status: str = "", active: str = "",
                 sort: str = "") -> list[dict]:
        uses, routines = self._uses(), self.items("routine")
        items = [self.product_view(p, uses, routines) for p in self.items("product")]
        if status == "current":
            items = [p for p in items if p.get("status") in ("in_use", "stock", "paused")]
        elif status:
            wanted = set(status.split(","))
            items = [p for p in items if p.get("status") in wanted]
        if area:
            items = [p for p in items if area in (p.get("areas") or [])]
        if category:
            items = [p for p in items if p.get("category") == category]
        if active:
            a = catalog.slug(active)
            items = [p for p in items if any(x.get("name") == a for x in p.get("actives") or [])]
        if q:
            words = catalog.slug(q).split("_")
            items = [p for p in items if all(w in catalog.slug(f"{p.get('brand')} {p.get('name')} {p.get('line') or ''} "
                                                               f"{p.get('category') or ''} {' '.join(p.get('tags') or [])}")
                                             for w in words if w)]
        status_rank = {"in_use": 0, "paused": 1, "stock": 2, "wishlist": 3, "finished": 4, "discarded": 5}
        if sort == "expiry":
            items.sort(key=lambda p: (p.get("expires_in") is None, p.get("expires_in") or 0))
        elif sort == "last_used":
            items.sort(key=lambda p: p.get("last_used") or "", reverse=True)
        elif sort == "price":
            items.sort(key=lambda p: p.get("price") or 0, reverse=True)
        elif sort == "name":
            items.sort(key=lambda p: (p.get("name") or "").lower())
        else:
            items.sort(key=lambda p: (status_rank.get(p.get("status"), 9), not p.get("favorite"), -(p.get("uses") or 0),
                                      (p.get("name") or "").lower()))
        return items

    def find_product(self, text: str, statuses: tuple = ()) -> dict | None:
        """Best match by name/brand (assistant tools): exact id, then all words, current items first."""
        if not text:
            return None
        row = self.store.data("product", text)
        if row:
            return row
        words = [w for w in catalog.slug(text).split("_") if w]
        rank = {"in_use": 0, "paused": 1, "stock": 2, "wishlist": 3, "finished": 4, "discarded": 5}
        cands = [p for p in self.items("product") if (not statuses or p.get("status") in statuses)
                 and all(w in catalog.slug(f"{p.get('brand')} {p.get('name')} {p.get('line') or ''}") for w in words)]
        cands.sort(key=lambda p: (rank.get(p.get("status"), 9), -len(p.get("name") or "")))
        return cands[0] if cands else None

    def product_detail(self, id: str) -> dict:
        p = self.get("product", id)
        view = self.product_view(p)
        events = sorted((e for e in self.items("event") if e.get("product_id") == id),
                        key=lambda e: (e.get("date") or "", e.get("at") or ""), reverse=True)
        siblings = [self.product_view(o) for o in self.items("product") if o["id"] != id
                    and o.get("product_key") == p.get("product_key")]
        uses = sorted(self._uses().get(id, []))
        weeks: dict[str, int] = {}
        for d in uses:
            ws = period_start(date.fromisoformat(d), "week", self.week_start()).isoformat()
            weeks[ws] = weeks.get(ws, 0) + 1
        return {**view, "events": events, "siblings": sorted(siblings, key=lambda s: s.get("purchased_at") or "", reverse=True),
                "usage_weeks": [{"week": k, "uses": v} for k, v in sorted(weeks.items())][-16:]}

    # ── routines ────────────────────────────────────────────────────────────
    def _steps(self, steps: Any) -> list[dict]:
        out = []
        for i, s in enumerate(_list(steps)):
            if not isinstance(s, dict):
                s = {"label": str(s)}
            step = {k: s[k] for k in STEP_FIELDS if k in s}
            step["id"] = str(step.get("id") or new_id()[:12])
            step["order"] = i + 1
            if step.get("product_id"):
                if not self.store.data("product", step["product_id"]):
                    raise Invalid(f"prodotto {step['product_id']} non trovato")
            elif not str(step.get("label") or "").strip():
                raise Invalid(f"il passo {i + 1} non ha né prodotto né descrizione")
            step["wait_seconds"] = int(_num(step.get("wait_seconds")) or 0)
            step["cadence"] = norm_cadence(step["cadence"]) if step.get("cadence") else None
            step["not_same_day_as"] = [str(x) for x in _list(step.get("not_same_day_as"))]
            step["optional"] = bool(step.get("optional"))
            step["paused_until"] = _day(step.get("paused_until"))
            out.append(step)
        return out

    @staticmethod
    def _steps_signature(steps: list[dict]) -> list:
        return [(s.get("product_id"), s.get("label"), s.get("amount"), s.get("wait_seconds"), s.get("cadence"),
                 s.get("not_same_day_as"), s.get("optional"), s.get("note"), s.get("paused_until")) for s in steps]

    def save_routine(self, body: dict, id: str | None = None, reason: str = "", source: str = "webui") -> dict:
        old = self.store.data("routine", id) if id else None
        if id and not old:
            raise NotFound(f"routine {id} non trovata")
        r = {**(old or {}), **{k: body[k] for k in ROUTINE_FIELDS if k in body}}
        name = str(r.get("name") or "").strip()
        if not name:
            raise Invalid("il nome della routine è obbligatorio")
        r["name"] = name
        r["areas"] = [catalog.slug(a) for a in _list(r.get("areas"))]
        r["slot"] = r.get("slot") if r.get("slot") in catalog.SLOTS else (r.get("slot") or "anytime")
        r["cadence"] = norm_cadence(r.get("cadence"))
        r["max_per_day"] = max(1, int(_num(r.get("max_per_day")) or 1))
        r["min_gap_hours"] = _num(r.get("min_gap_hours"))
        r["not_same_day_as"] = [str(x) for x in _list(r.get("not_same_day_as")) if x != id]
        r["reminder"] = bool(r.get("reminder"))
        r["favorite"] = bool(r.get("favorite"))
        r["status"] = r.get("status") if r.get("status") in ("active", "paused", "archived") else "active"
        if r.get("order") is None:
            r["order"] = len(self.items("routine")) + 1
        rows = []
        steps_changed = "steps" in body or not old
        if steps_changed:
            steps = self._steps(body.get("steps") if "steps" in body else [])
            if old and self._steps_signature(steps) == self._steps_signature(old.get("steps") or []):
                steps_changed = False
            r["steps"] = steps
        rid = id or new_id()
        if steps_changed:
            version = int((old or {}).get("version") or 0) + 1
            r["version"] = version
            rows.append({"kind": "version", "id": f"{rid}:{version}", "parent_id": rid, "ref_id": str(version),
                         "at": now_iso(), "data": {"routine_id": rid, "version": version, "steps": r["steps"],
                                                   "reason": reason or ("creata" if not old else ""),
                                                   "valid_from": self.today().isoformat(), "by": source,
                                                   "diff": self._diff(old.get("steps") if old else [], r["steps"])}})
        r.pop("id", None)
        rows.insert(0, {"kind": "routine", "id": rid, "data": r})
        self.store.write(rows)
        return self.routine_detail(rid)

    def _diff(self, before: list[dict] | None, after: list[dict]) -> str:
        name = lambda s: s.get("label") or (self.store.data("product", s.get("product_id") or "") or {}).get("name") or "passo"
        b = {s.get("product_id") or s.get("label"): s for s in before or []}
        a = {s.get("product_id") or s.get("label"): s for s in after}
        parts = [f"+ {name(a[k])}" for k in a if k not in b] + [f"− {name(b[k])}" for k in b if k not in a]
        changed = [name(a[k]) for k in a if k in b and self._steps_signature([a[k]]) != self._steps_signature([b[k]])]
        parts += [f"~ {n}" for n in changed]
        if not parts and [s.get("product_id") or s.get("label") for s in before or []] != \
                [s.get("product_id") or s.get("label") for s in after]:
            parts.append("ordine cambiato")
        return ", ".join(parts) if before is not None else ""

    def routines(self, include_archived: bool = False) -> list[dict]:
        day = self.day()
        out = []
        for r in self.items("routine"):
            if r.get("status") == "archived" and not include_archived:
                continue
            plan = day.plan_routine(r)
            out.append({**r, "cadence_label": cadence_label(r.get("cadence")), "state": plan["state"], "hint": plan["hint"],
                        "reason": plan["reason"], "goal": plan["goal"], "step_count": len(r.get("steps") or [])})
        slot_order = {"morning": 0, "anytime": 1, "evening": 2}
        return sorted(out, key=lambda r: (r.get("status") != "active", slot_order.get(r.get("slot"), 1), r.get("order") or 0))

    def routine_detail(self, rid: str) -> dict:
        r = self.get("routine", rid)
        products = {p["id"]: p for p in self.items("product")}
        steps = [{**s, "product": products.get(s.get("product_id") or ""),
                  "cadence_label": cadence_label(s["cadence"]) if s.get("cadence") else ""} for s in r.get("steps") or []]
        return {**r, "steps": steps, "cadence_label": cadence_label(r.get("cadence")), "plan": self.day().plan_routine(r),
                "versions": self.versions(rid), "stats": self.routine_stats(r), "check": self.check(routine_id=rid)["notes"],
                "reminder_state": self._reminder_row(rid)}

    def versions(self, rid: str) -> list[dict]:
        return sorted((v for v in self.items("version") if v.get("routine_id") == rid), key=lambda v: v["version"],
                      reverse=True)

    def undo_routine(self, rid: str, source: str = "webui") -> dict:
        vs = self.versions(rid)
        if len(vs) < 2:
            raise Conflict("nessuna versione precedente")
        prev = vs[1]
        return self.save_routine({"steps": prev["steps"]}, id=rid, reason=f"ripristinata la versione {prev['version']}",
                                 source=source)

    def delete_routine(self, rid: str) -> dict:
        self.get("routine", rid)
        return self.save_routine({"status": "archived"}, id=rid)

    def find_routine(self, text: str) -> dict | None:
        if not text:
            return None
        row = self.store.data("routine", text)
        if row:
            return row
        words = [w for w in catalog.slug(text).split("_") if w]
        cands = [r for r in self.items("routine") if r.get("status") != "archived"
                 and all(w in catalog.slug(r.get("name") or "") for w in words)]
        return sorted(cands, key=lambda r: len(r.get("name") or ""))[0] if cands else None

    # ── planner ─────────────────────────────────────────────────────────────
    def day(self, d: date | None = None) -> Day:
        products = {p["id"]: p for p in self.items("product")}
        conflicts = [o for o in self.options("conflicts") if o.get("custom")]
        return Day(d or self.today(), self.items("routine"), self.items("log"), products, self.week_start(),
                   custom_actives=[o for o in self.options("actives") if o.get("custom")], custom_conflicts=conflicts,
                   now=self.now())

    def plan(self, d: str | None = None, include_paused: bool = False) -> dict:
        day = date.fromisoformat(d) if d else self.today()
        items = self.day(day).plan(include_inactive=include_paused)
        adhoc = [l for l in self.items("log") if l.get("date") == day.isoformat() and not l.get("routine_id")
                 and l.get("status") in DONE_STATUSES]
        products = {p["id"]: p for p in self.items("product")}
        return {"date": day.isoformat(), "routines": items,
                "adhoc": [{"log_id": l["id"], "product": (products.get((l.get("steps") or [{}])[0].get("product_id") or "")
                                                          or {}).get("name"), "note": l.get("note")} for l in adhoc],
                "next": next((p for p in items if p["state"] in ("due", "suggested")), None),
                "counts": {s: sum(1 for p in items if p["state"] == s) for s in
                           ("done", "due", "suggested", "wait", "ok", "blocked", "off", "rest")}}

    def routine_plan(self, rid: str, d: str | None = None) -> dict:
        r = self.get("routine", rid)
        day = date.fromisoformat(d) if d else self.today()
        return self.day(day).plan_routine(r)

    # ── logs ────────────────────────────────────────────────────────────────
    def log_routine(self, rid: str, day: str | None = None, status: str = "done", steps: list | None = None,
                    note: str = "", source: str = "webui") -> dict:
        r = self.get("routine", rid)
        if status not in ("done", "partial", "skipped"):
            raise Invalid("stato non valido (done, partial, skipped)")
        d = _day(day) or self.today().isoformat()
        plan = self.day(date.fromisoformat(d)).plan_routine(r)
        done_today = [l for l in self.items("log") if l.get("routine_id") == rid and l.get("date") == d
                      and l.get("status") in DONE_STATUSES]
        if status != "skipped" and len(done_today) >= int(r.get("max_per_day") or 1):
            raise Conflict(f"{r['name']} è già segnata {len(done_today)} volta/e il {d}", log_id=done_today[-1]["id"])
        if steps is None:
            chosen = {s["step_id"] for s in plan["steps"] if s["include"] and not s.get("optional")}
        else:
            chosen = {str(x.get("step_id") if isinstance(x, dict) else x) for x in steps
                      if not isinstance(x, dict) or x.get("done", True)}
        log_steps = [{"step_id": s["step_id"], "product_id": (s.get("product") or {}).get("id"),
                      "done": status != "skipped" and s["step_id"] in chosen} for s in plan["steps"]
                     if s["include"] or s["step_id"] in chosen]
        if status == "done" and steps is not None and any(not s["done"] for s in log_steps if s["step_id"] in
                                                           {x["step_id"] for x in plan["steps"] if x["include"] and not x.get("optional")}):
            status = "partial"
        lid = new_id()
        at = now_iso() if d == self.today().isoformat() else f"{d}T12:00:00+00:00"
        data = {"routine_id": rid, "version": r.get("version"), "date": d, "done_at": at, "status": status,
                "steps": log_steps, "note": note or "", "source": source}
        self.store.upsert("log", lid, data, parent_id=rid, ref_id=d, at=at)
        if status in DONE_STATUSES:
            self._mark_reminder(rid, resolved=True)
        g = self.day(date.fromisoformat(d)).plan_routine(self.get("routine", rid))
        return {**data, "id": lid, "name": r["name"], "hint": g["hint"], "goal": g["goal"]}

    def log_product(self, pid: str, day: str | None = None, note: str = "", source: str = "webui") -> dict:
        p = self.get("product", pid)
        d = _day(day) or self.today().isoformat()
        lid = new_id()
        at = now_iso() if d == self.today().isoformat() else f"{d}T12:00:00+00:00"
        data = {"routine_id": None, "date": d, "done_at": at, "status": "done", "note": note or "", "source": source,
                "steps": [{"step_id": "adhoc", "product_id": pid, "done": True}]}
        self.store.upsert("log", lid, data, parent_id=None, ref_id=d, at=at)
        if p.get("status") == "stock":
            self.set_status(pid, "in_use", d, source=source)
        return {**data, "id": lid, "name": p["name"]}

    def undo_log(self, *, routine_id: str | None = None, product_id: str | None = None, day: str | None = None) -> dict:
        d = _day(day) or self.today().isoformat()
        rows = [l for l in self.items("log") if l.get("date") == d and l.get("status") in DONE_STATUSES and (
            (routine_id and l.get("routine_id") == routine_id) or
            (product_id and not l.get("routine_id") and any(s.get("product_id") == product_id for s in l.get("steps") or [])))]
        if not rows:
            raise NotFound("niente da annullare")
        rows.sort(key=lambda l: l.get("done_at") or "")
        self.store.delete("log", rows[-1]["id"])
        return {"undone": True, "id": rows[-1]["id"]}

    def delete_log(self, lid: str) -> dict:
        self.get("log", lid)
        self.store.delete("log", lid)
        return {"deleted": True, "id": lid}

    def logs(self, days: int = 30, routine_id: str = "", product_id: str = "") -> list[dict]:
        since = (self.today() - timedelta(days=days)).isoformat()
        routines = {r["id"]: r for r in self.items("routine")}
        products = {p["id"]: p for p in self.items("product")}
        out = []
        for l in self.items("log"):
            if (l.get("date") or "") < since:
                continue
            if routine_id and l.get("routine_id") != routine_id:
                continue
            if product_id and not any(s.get("product_id") == product_id and s.get("done") for s in l.get("steps") or []):
                continue
            r = routines.get(l.get("routine_id") or "") or {}
            out.append({**l, "name": r.get("name") or ", ".join((products.get(s.get("product_id") or "") or {}).get("name", "")
                                                               for s in l.get("steps") or []) or "uso",
                        "products": [(products.get(s.get("product_id") or "") or {}).get("name") for s in l.get("steps") or []
                                     if s.get("done") and s.get("product_id")]})
        return sorted(out, key=lambda l: (l["date"], l.get("done_at") or ""), reverse=True)

    # ── journal ─────────────────────────────────────────────────────────────
    def journal_add(self, body: dict, source: str = "webui") -> list[dict]:
        d = _day(body.get("date")) or self.today().isoformat()
        entries = body.get("entries") or [body]
        rows = []
        for e in entries:
            area = catalog.slug(e.get("area") or "")
            if not area:
                raise Invalid("area mancante")
            scores = {}
            for k, v in (e.get("scores") or {}).items():
                n = _num(v)
                if n is None:
                    continue
                if not 1 <= n <= 5:
                    raise Invalid(f"{k}: voto da 1 a 5")
                scores[catalog.slug(k)] = n
            if not scores and not e.get("note") and not e.get("tags"):
                continue
            rows.append({"kind": "journal", "id": new_id(), "ref_id": area, "at": f"{d}T12:00:00+00:00",
                         "data": {"date": d, "area": area, "scores": scores, "tags": [str(t) for t in _list(e.get("tags") or body.get("tags"))],
                                  "note": e.get("note") or "", "photo_ids": _list(e.get("photo_ids")), "source": source}})
        if not rows:
            raise Invalid("niente da salvare")
        self.store.write(rows)
        return [{**r["data"], "id": r["id"]} for r in rows]

    def journal(self, area: str = "", days: int = 120) -> dict:
        since = (self.today() - timedelta(days=days)).isoformat()
        items = sorted((j for j in self.items("journal") if j.get("date", "") >= since and (not area or j.get("area") == area)),
                       key=lambda j: j["date"], reverse=True)
        series: dict[str, dict[str, list]] = {}
        for j in sorted(items, key=lambda j: j["date"]):
            for k, v in (j.get("scores") or {}).items():
                series.setdefault(j["area"], {}).setdefault(k, []).append({"date": j["date"], "value": v})
        markers = [t for t in self.timeline(days=days) if t["type"] in ("version", "opened", "finished", "replaced")
                   and (not area or area in (t.get("areas") or []) or not t.get("areas"))]
        return {"items": items, "series": series, "markers": markers}

    def delete_journal(self, jid: str) -> dict:
        self.get("journal", jid)
        self.store.delete("journal", jid)
        return {"deleted": True, "id": jid}

    # ── statistics, timeline, period ────────────────────────────────────────
    def routine_stats(self, r: dict, periods: int = 12) -> dict:
        c = norm_cadence(r.get("cadence"))
        per = c.get("per") if c["mode"] == "target" else "week"
        ws = self.week_start()
        days = [date.fromisoformat(l["date"]) for l in self.items("log") if l.get("routine_id") == r["id"]
                and l.get("status") in DONE_STATUSES]
        skipped = sum(1 for l in self.items("log") if l.get("routine_id") == r["id"] and l.get("status") == "skipped")
        today = self.today()
        start = period_start(today, per, ws)
        hist, streak, counting = [], 0, True
        for i in range(periods):
            if i:
                start = period_start(start - timedelta(days=1), per, ws)
            end = period_next(start, per)
            n = sum(1 for d in days if start <= d < end)
            if c["mode"] == "target":
                need = c["times"]
            elif c["mode"] == "daily":
                need = (min(end, today + timedelta(days=1)) - start).days
            elif c["mode"] == "fixed_days":
                need = sum(1 for k in range((min(end, today + timedelta(days=1)) - start).days)
                           if (start + timedelta(days=k)).weekday() in c["days"])
            else:
                need = 0
            met = n >= need if need else None
            hist.append({"start": start.isoformat(), "done": n, "need": need, "met": met})
            if i == 0 and not met:
                continue
            if counting and met:
                streak += 1
            elif i > 0:
                counting = False
        judged = [h for h in hist if h["met"] is not None]
        return {"routine_id": r["id"], "name": r.get("name"), "per": per, "cadence": cadence_label(c),
                "total": len(days), "skipped": skipped, "streak": streak, "last_done": max(days).isoformat() if days else None,
                "adherence": round(100 * sum(1 for h in judged if h["met"]) / len(judged)) if judged else None,
                "history": list(reversed(hist))}

    def stats(self, days: int = 90) -> dict:
        today = self.today()
        since = today - timedelta(days=days)
        logs = [l for l in self.items("log") if l.get("status") in DONE_STATUSES and l.get("date", "") >= since.isoformat()]
        heat: dict[str, int] = {}
        for l in logs:
            heat[l["date"]] = heat.get(l["date"], 0) + 1
        routines = [r for r in self.items("routine") if r.get("status") != "archived"]
        uses = self._uses()
        products = self.items("product")
        top = sorted(({"id": p["id"], "name": p["name"], "brand": p.get("brand"),
                       "uses": sum(1 for d in uses.get(p["id"], []) if d >= since.isoformat())} for p in products),
                     key=lambda x: -x["uses"])
        spend: dict[str, float] = {}
        for p in products:
            if p.get("price") and p.get("purchased_at") and p.get("status") != "wishlist":
                m = p["purchased_at"][:7]
                spend[m] = round(spend.get(m, 0) + float(p["price"]), 2)
        months = []
        m = today.replace(day=1)
        for _ in range(12):
            months.append(m.strftime("%Y-%m"))
            m = (m - timedelta(days=1)).replace(day=1)
        by_status: dict[str, int] = {}
        for p in products:
            by_status[p.get("status")] = by_status.get(p.get("status"), 0) + 1
        week = period_start(today, "week", self.week_start())
        return {"days": days, "heatmap": [{"date": (since + timedelta(days=i)).isoformat(),
                                          "count": heat.get((since + timedelta(days=i)).isoformat(), 0)} for i in range(days + 1)],
                "routines": [self.routine_stats(r) for r in routines],
                "top_products": [t for t in top if t["uses"]][:10],
                "spend": [{"month": k, "amount": spend.get(k, 0)} for k in reversed(months)],
                "products_by_status": by_status,
                "week": {"logs": sum(1 for l in logs if l["date"] >= week.isoformat()),
                         "goals_met": sum(1 for r in routines if r.get("status") == "active" and
                                          self.day().plan_routine(r)["goal"].get("state") in ("ok", "done")
                                          and norm_cadence(r.get("cadence"))["mode"] == "target"),
                         "goals": sum(1 for r in routines if r.get("status") == "active"
                                      and norm_cadence(r.get("cadence"))["mode"] == "target")}}

    def timeline(self, days: int = 365, since: str | None = None, until: str | None = None) -> list[dict]:
        start = since or (self.today() - timedelta(days=days)).isoformat()
        end = until or "9999"
        routines = {r["id"]: r for r in self.items("routine")}
        products = {p["id"]: p for p in self.items("product")}
        out = []
        for v in self.items("version"):
            if start <= v.get("valid_from", "") <= end:
                r = routines.get(v["routine_id"]) or {}
                out.append({"date": v["valid_from"], "type": "version", "title": f"{r.get('name', 'Routine')} v{v['version']}",
                            "text": v.get("reason") or v.get("diff") or "", "diff": v.get("diff") or "",
                            "routine_id": v["routine_id"], "areas": r.get("areas") or []})
        for e in self.items("event"):
            d = e.get("date") or (e.get("at") or "")[:10]
            if start <= d <= end:
                p = products.get(e.get("product_id")) or {}
                out.append({"date": d, "type": e.get("type"), "title": p.get("name") or "Prodotto",
                            "text": e.get("text") or "", "product_id": e.get("product_id"), "areas": p.get("areas") or []})
        for j in self.items("journal"):
            if start <= j.get("date", "") <= end:
                scores = ", ".join(f"{k} {int(v)}" for k, v in (j.get("scores") or {}).items())
                out.append({"date": j["date"], "type": "journal", "title": f"Diario · {j.get('area')}",
                            "text": "; ".join(x for x in (scores, j.get("note")) if x), "areas": [j.get("area")]})
        return list(reversed(sorted(out, key=lambda t: t["date"])))

    def period(self, d: str) -> dict:
        day = _day(d) or self.today().isoformat()
        routines = []
        for r in self.items("routine"):
            vs = [v for v in self.versions(r["id"]) if v.get("valid_from", "") <= day]
            if not vs:
                continue
            v = vs[0]
            products = {p["id"]: p for p in self.items("product")}
            routines.append({"id": r["id"], "name": r.get("name"), "version": v["version"],
                             "steps": [s.get("label") or (products.get(s.get("product_id") or "") or {}).get("name") or "passo"
                                       for s in v.get("steps") or []]})
        in_use = []
        for p in self.items("product"):
            opened = p.get("opened_at")
            if opened and opened <= day and (not p.get("finished_at") or p["finished_at"] >= day) \
                    and p.get("status") not in ("wishlist",):
                in_use.append({"id": p["id"], "name": p["name"], "brand": p.get("brand"), "opened_at": opened})
        journal = [j for j in self.items("journal") if abs((date.fromisoformat(j["date"]) - date.fromisoformat(day)).days) <= 7]
        return {"date": day, "routines": routines, "products": in_use, "journal": journal}

    # ── alerts and shopping ─────────────────────────────────────────────────
    def alerts(self) -> list[dict]:
        expiry_days = int(self.setting("hygieia.alerts.expiry_days", 30))
        restock_days = int(self.setting("hygieia.alerts.restock_days", 14))
        uses, routines = self._uses(), self.items("routine")
        views = [self.product_view(p, uses, routines) for p in self.items("product")]
        has_spare = {v.get("product_key") for v in views if v.get("status") == "stock"}
        current_keys = {v.get("product_key") for v in views if v.get("status") in ("in_use", "stock")}
        out = []
        for v in views:
            if v.get("status") in ("in_use", "stock") and v.get("expires_in") is not None and v["expires_in"] <= expiry_days:
                expired = v["expires_in"] < 0
                out.append({"key": f"expiry:{v['id']}", "type": "expiry", "product_id": v["id"], "name": v["name"],
                            "level": "warning" if expired else "info", "days": v["expires_in"],
                            "text": f"{v['name']} è scaduto" if expired else f"{v['name']} scade tra {v['expires_in']} giorni"})
            if v.get("status") == "in_use" and v.get("product_key") not in has_spare:
                fe = v.get("finish_estimate") or {}
                if v.get("level") == "almost_empty" or (fe.get("days_left") is not None and fe["days_left"] <= restock_days):
                    out.append({"key": f"restock:{v['id']}", "type": "restock", "product_id": v["id"], "name": v["name"],
                                "level": "info", "days": fe.get("days_left"),
                                "text": f"{v['name']} sta finendo" + (f" (≈{fe['days_left']} giorni)" if fe.get("days_left") is not None else "")})
            if v.get("status") in ("finished", "discarded") and v.get("routines") and v.get("product_key") not in current_keys:
                out.append({"key": f"missing:{v['id']}", "type": "missing", "product_id": v["id"], "name": v["name"],
                            "level": "info", "text": f"{v['name']} è finito ma è ancora in {v['routines'][0]['name']}"})
        return out

    def shopping(self) -> dict:
        views = {p["id"]: p for p in self.products()}
        wish = [p for p in views.values() if p.get("status") == "wishlist"]
        restock = [{**views[a["product_id"]], "why": a["text"]} for a in self.alerts() if a["type"] in ("restock", "missing")]
        keys = {p.get("product_key") for p in views.values() if p.get("status") in ("in_use", "stock")}
        again = []
        seen = set()
        for p in sorted(views.values(), key=lambda p: p.get("finished_at") or "", reverse=True):
            if p.get("status") == "finished" and p.get("verdict") == "repurchase" and p.get("product_key") not in keys \
                    and p.get("product_key") not in seen and not any(r["id"] == p["id"] for r in restock):
                seen.add(p.get("product_key"))
                again.append({**p, "why": "finito, da ricomprare"})
        return {"wishlist": wish, "restock": restock, "repurchase": again,
                "count": len(wish) + len(restock) + len(again)}

    # ── compatibility check ─────────────────────────────────────────────────
    def check(self, routine_id: str = "", product: str = "", actives: list | None = None) -> dict:
        day = self.day()
        notes: list[dict] = []
        if routine_id:
            r = self.get("routine", routine_id)
            steps = r.get("steps") or []
            for i, a in enumerate(steps):
                for b in steps[i + 1:]:
                    n = conflict_notes(day.step_families(a), day.step_families(b), day.custom_conflicts)
                    if n:
                        separated = bool(a.get("cadence") and b.get("cadence"))
                        notes.append({"level": "info" if separated else "warning", "steps": [day._step_name(a), day._step_name(b)],
                                      "text": n[0] + (" Il pianificatore li alterna già." if separated else
                                                      " Dai a uno dei due un obiettivo proprio così li alterno.")})
            if r.get("slot") == "morning" and "viso" in (r.get("areas") or []) and not any(
                    "spf" in day.step_families(s) or (self.store.data("product", s.get("product_id") or "") or {}).get("category") == "spf"
                    for s in steps):
                notes.append({"level": "info", "steps": [], "text": "Manca una protezione solare nella routine viso del mattino."})
            for oid, why in day.implicit_partners(r).items():
                notes.append({"level": "info", "steps": [], "text": f"Con «{(day.routines.get(oid) or {}).get('name')}»: {why}"})
            return {"routine": r["name"], "notes": notes, "ok": not any(n["level"] == "warning" for n in notes)}
        fam: set[str] = set()
        label = product
        if product:
            p = self.find_product(product)
            if p:
                fam = day.product_families(p["id"])
                label = p["name"]
        if actives:
            fam |= catalog.families([catalog.slug(a) for a in actives], [o for o in self.options("actives") if o.get("custom")])
        if not fam:
            return {"product": label, "notes": [], "ok": True, "text": "nessun attivo noto da confrontare"}
        for p in self.items("product"):
            if p.get("status") != "in_use" or p.get("name") == label:
                continue
            n = conflict_notes(fam, day.product_families(p["id"]), day.custom_conflicts)
            if n:
                notes.append({"level": "info", "steps": [p["name"]], "text": n[0]})
        return {"product": label, "notes": notes, "ok": True}

    # ── quick actions (WebUI Home) ──────────────────────────────────────────
    def quick_routines(self) -> list[dict]:
        out = []
        for p in self.plan()["routines"]:
            if p["state"] in ("blocked", "off", "paused") and not p["favorite"]:
                continue
            if not p["favorite"] and p["state"] not in ("due", "suggested", "done"):
                continue
            st = "done" if p["state"] == "done" else ("late" if p["state"] == "due" and p["goal"].get("behind") else "todo")
            hint = p["hint"] if p["state"] != "blocked" else p["reason"]
            out.append({"id": p["routine_id"], "label": p["name"], "icon": p.get("icon") or "sparkle", "state": st,
                        "hint": hint, "favorite": p["favorite"]})
        return out

    def quick_products(self) -> list[dict]:
        uses = self._uses()
        today = self.today().isoformat()
        return [{"id": p["id"], "label": p["name"], "icon": "drop", "favorite": True,
                 "state": "done" if today in uses.get(p["id"], []) else "todo",
                 "hint": f"{len(uses.get(p['id'], []))} usi"}
                for p in self.items("product") if p.get("favorite") and p.get("status") in ("in_use", "stock")]

    # ── reminders (SPEC §7) ─────────────────────────────────────────────────
    def _reminder_row(self, rid: str) -> dict:
        return self.store.data("reminder", rid) or {}

    def _mark_reminder(self, rid: str, resolved: bool = False, sent: bool = False, silenced_until: str | None = None) -> None:
        row = self._reminder_row(rid)
        if not row and not sent and not silenced_until:
            return
        row.pop("id", None)
        if sent:
            week = period_start(self.today(), "week", self.week_start()).isoformat()
            counts = row.get("sent_weeks") or {}
            counts[week] = counts.get(week, 0) + 1
            row["sent_weeks"] = dict(sorted(counts.items())[-8:])
            row["last_sent"] = self.today().isoformat()
            row["open"] = True
        if resolved:
            row["open"] = False
        if silenced_until is not None:
            row["silenced_until"] = silenced_until
            row["open"] = False
        self.store.upsert("reminder", rid, row)

    def snooze_routine(self, rid: str) -> dict:
        r = self.get("routine", rid)
        c = norm_cadence(r.get("cadence"))
        per = c.get("per") if c["mode"] == "target" else "week"
        until = period_next(period_start(self.today(), per, self.week_start()), per).isoformat()
        self._mark_reminder(rid, silenced_until=until)
        return {"routine_id": rid, "silenced_until": until, "label": f"{r['name']}: niente promemoria fino al {until}"}

    def reminder_decisions(self) -> list[dict]:
        if not self.setting("hygieia.reminder.enabled", False):   # common reminder switch, off by default
            return []
        max_week = int(self.setting("hygieia.reminder.max_per_week", 2))
        today = self.today().isoformat()
        week = period_start(self.today(), "week", self.week_start()).isoformat()
        out = []
        for p in self.plan()["routines"]:
            rid = p["routine_id"]
            r = self.store.data("routine", rid) or {}
            if not r.get("reminder") or r.get("status") != "active":
                continue
            row = self._reminder_row(rid)
            why = ""
            if p["state"] != "due":
                why = f"state_{p['state']}"
            elif (row.get("silenced_until") or "") > today:
                why = "silenced"
            elif row.get("last_sent") == today:
                why = "sent_today"
            elif (row.get("sent_weeks") or {}).get(week, 0) >= max_week:
                why = "weekly_limit"
            out.append({"send": not why, "why": why or "due", "routine_id": rid, "plan": p})
        return out

    def reminder_text(self, p: dict) -> str:
        steps = [s["label"] for s in p["steps"] if s["include"]]
        text = f"{p['name']}"
        if p["goal"].get("mode") == "target":
            text += f": {p['hint']}"
        if steps:
            text += " · " + " › ".join(steps[:6])
        return text

    def mark_reminder_sent(self, rid: str) -> None:
        self._mark_reminder(rid, sent=True)

    # ── summary / assistant context ─────────────────────────────────────────
    def summary(self) -> dict:
        plan = self.plan()
        in_use = [p for p in self.items("product") if p.get("status") == "in_use"]
        alerts = self.alerts()
        parts = []
        today_bits = []
        for p in plan["routines"]:
            mark = {"done": "✓", "due": "da fare", "suggested": "consigliata", "blocked": "non oggi", "wait": "fatta da poco",
                    "ok": "obiettivo ok", "off": "", "rest": ""}.get(p["state"], p["state"])
            if p["state"] in ("off", "rest"):
                continue
            bit = f"{p['name']} {mark}".strip()
            if p["goal"].get("mode") == "target":
                bit += f" ({p['hint']})"
            today_bits.append(bit)
        if today_bits:
            parts.append("oggi: " + "; ".join(today_bits))
        if in_use:
            parts.append(f"in uso {len(in_use)} prodotti")
        for a in alerts[:3]:
            parts.append(a["text"])
        text = " · ".join(parts) or "nessuna routine ancora"
        return {"text": text, "plan": plan, "alerts": alerts, "in_use": len(in_use)}

    def overview(self) -> dict:
        products = {p["id"]: p for p in self.items("product")}
        routines = []
        for r in sorted(self.items("routine"), key=lambda r: r.get("order") or 0):
            if r.get("status") == "archived":
                continue
            routines.append({"id": r["id"], "name": r["name"], "slot": catalog.SLOTS.get(r.get("slot"), r.get("slot")),
                             "cadence": cadence_label(r.get("cadence")), "status": r.get("status"),
                             "steps": [(s.get("label") or (products.get(s.get("product_id") or "") or {}).get("name") or "passo")
                                       + (f" [{cadence_label(s['cadence'])}]" if s.get("cadence") else "")
                                       for s in r.get("steps") or []]})
        in_use = [f"{p.get('brand') + ' ' if p.get('brand') else ''}{p['name']}" for p in products.values()
                  if p.get("status") == "in_use"]
        s = self.summary()
        return {"text": s["text"], "routines": routines, "in_use": in_use, "alerts": [a["text"] for a in s["alerts"]],
                "today": [{"name": p["name"], "state": p["state"], "hint": p["hint"], "reason": p["reason"],
                           "steps": [x["label"] for x in p["steps"] if x["include"]]} for p in s["plan"]["routines"]]}

    # ── reflection signals (docs/work/2026-10-20-riflessione-a-livelli) ──────
    def signals(self) -> tuple[list[dict], list[dict]]:
        """Deterministic signals + weekly metrics for the reflection layer (``signals_client.Signals.run``)."""
        from . import signals as signals_engine
        return signals_engine.evaluate(self)

    def signal_detail(self, topic: str) -> str | None:
        """Facts behind one signal key, for ``/api/module/context?topic=`` (``None`` = unknown topic)."""
        from . import signals as signals_engine
        return signals_engine.detail(self, topic)

    def context_text(self, budget: int = 400, topic: str = "") -> str:
        detail = self.signal_detail(topic) if topic else None
        if detail:
            return detail if len(detail) <= budget else detail[: max(40, budget - 1)].rsplit("; ", 1)[0] + "…"
        s = self.summary()
        text = "Self care: " + s["text"]
        if len(text) > budget:
            text = text[: max(40, budget - 1)].rsplit(" · ", 1)[0] + "…"
        return text

    def export(self) -> dict:
        return {kind: self.items(kind) for kind in ("product", "event", "routine", "version", "log", "journal", "option")}
