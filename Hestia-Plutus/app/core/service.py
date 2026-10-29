"""Plutus domain logic: transactions, categories and learned rules, budgets, accounts, recurring payments,
PayPal↔bank linking, summaries and statistics. Storage = ``Store`` (Archive ``/api/finance-store``).

Money is signed: expense < 0, income/refund > 0. Totals never count ``linked_to`` rows (the same payment seen twice,
e.g. PayPal mail + the card row «PAYPAL *X» in the bank statement) nor transfers between own accounts.
SPEC docs/work/2026-10-19-email-push-spese §4.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.signals_client import iso_week, last_weeks, metric, signal

from . import catalog, paypal, phone
from .store import Store, now_iso

logger = logging.getLogger("hestia_plutus.service")

CURRENCY_KEY = "themis.personal.currency"
TX_FIELDS = ("date", "amount", "currency", "merchant", "description", "category", "account", "source",
             "external_ref", "linked_to", "notes", "tags", "status", "import_id", "mail_ref")
SOURCES = ("manual", "chat", "email", "statement", "quick", "phone")


class Invalid(ValueError):
    pass


class NotFound(KeyError):
    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "not found"


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _d(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19].replace("Z", "")).date() if "T" in str(value) \
            else date.fromisoformat(str(value)[:10])
    except ValueError:
        m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", str(value))
        if m:
            y = int(m.group(3))
            return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
        return None


def _month_add(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def _json_from(text: str | None) -> Any:
    if not text:
        return None
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


class Plutus:
    def __init__(self, store: Store, cfg: Callable[[str, Any], Any], *, tz_name: str = "Europe/Rome",
                 llm: Callable[[str], str | None] | None = None):
        self.store = store
        self.cfg = cfg
        self.tz = ZoneInfo(tz_name)
        self.llm = llm

    # ── basics ───────────────────────────────────────────────────────────────
    def setting(self, key: str, default: Any = None) -> Any:
        try:
            value = self.cfg(key, default)
        except TypeError:
            value = self.cfg(key)
        return default if value is None else value

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def currency(self) -> str:
        return str(self.setting(CURRENCY_KEY, "EUR") or "EUR")

    def get(self, kind: str, id: str) -> dict:
        self.store.refresh()
        row = self.store.data(kind, id)
        if not row:
            raise NotFound(f"{kind} '{id}' non trovato")
        return row

    def month_range(self, ref: date | str | None = None) -> tuple[date, date]:
        """[start, end) of the budget month containing ``ref`` (month starts on ``plutus.month_start_day``)."""
        ref = _d(ref) or self.today()
        start_day = max(1, min(28, int(self.setting("plutus.month_start_day", 1) or 1)))
        start = ref.replace(day=start_day) if ref.day >= start_day else _month_add(ref, -1).replace(day=start_day)
        return start, _month_add(start, 1).replace(day=start_day)

    def month_label(self, start: date) -> str:
        names = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
                 "ottobre", "novembre", "dicembre"]
        ref = start if start.day <= 15 else _month_add(start, 1)
        return f"{names[ref.month - 1]} {ref.year}"

    # ── seed (categories + default rules), once ──────────────────────────────
    def ensure_seed(self) -> int:
        self.store.refresh(force=True)
        if self.store.all("category", deleted=True):
            return 0
        rows = []
        for i, (cid, label, icon, color, kind) in enumerate(catalog.CATEGORIES):
            rows.append({"kind": "category", "id": cid, "data": {"label": label, "icon": icon, "color": color,
                                                                 "kind": kind, "order": i, "seed": True}})
        for cid, patterns in catalog.DEFAULT_RULES.items():
            for p in patterns:
                rows.append({"kind": "rule", "id": f"rule_{catalog.slug(p)}", "ref_id": cid,
                             "data": {"pattern": p.strip(), "category": cid, "source": "default"}})
        rows.append({"kind": "account", "id": "paypal", "data": {"name": "PayPal", "kind": "wallet", "seed": True}})
        rows.append({"kind": "account", "id": "hype", "data": {"name": "Hype", "kind": "bank", "seed": True}})
        rows.append({"kind": "account", "id": "contanti", "data": {"name": "Contanti", "kind": "cash", "seed": True}})
        self.store.write(rows)
        logger.info("event=plutus_seeded categories=%d rules=%d", len(catalog.CATEGORIES),
                    sum(len(v) for v in catalog.DEFAULT_RULES.values()))
        return len(rows)

    # ── categories, accounts, rules ──────────────────────────────────────────
    def categories(self, archived: bool = False) -> list[dict]:
        self.store.refresh()
        items = [c for c in self.store.items("category") if archived or not c.get("archived")]
        return sorted(items, key=lambda c: (c.get("order", 99), c.get("label", "")))

    def category_map(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.categories(archived=True)}

    def resolve_category(self, value: str | None) -> str | None:
        if not value:
            return None
        cats = self.category_map()
        key = catalog.slug(value)
        if key in cats:
            return key
        for c in cats.values():
            if catalog.slug(c.get("label")) == key or key and key in catalog.slug(c.get("label")):
                return c["id"]
        return None

    def save_category(self, body: dict, id: str | None = None) -> dict:
        label = str(body.get("label") or "").strip()
        current = self.store.data("category", id) if id else None
        if not label and not current:
            raise Invalid("nome della categoria mancante")
        cid = id or catalog.slug(label) or _id("cat")
        if not id and self.store.data("category", cid):
            raise Invalid(f"la categoria «{label}» esiste già")
        data = {**(current or {"kind": "expense", "order": 50, "icon": "tag", "color": "gray"}),
                **{k: body[k] for k in ("label", "icon", "color", "kind", "order", "archived", "parent")
                   if k in body}}
        if data.get("kind") not in ("expense", "income", "transfer"):
            raise Invalid("tipo categoria: expense, income o transfer")
        data.pop("id", None)
        return self.store.upsert("category", cid, data)

    def accounts(self) -> list[dict]:
        self.store.refresh()
        return sorted(self.store.items("account"), key=lambda a: a.get("name", ""))

    def resolve_account(self, value: str | None) -> str:
        if not value:
            return "contanti"
        key = catalog.slug(value)
        for a in self.accounts():
            if a["id"] == key or catalog.slug(a.get("name")) == key:
                return a["id"]
        self.store.upsert("account", key, {"name": str(value).strip()[:40], "kind": "bank"})
        return key

    def rules(self) -> list[dict]:
        self.store.refresh()
        return sorted(self.store.items("rule"), key=lambda r: (-len(r.get("pattern") or ""), r.get("pattern", "")))

    def categorize(self, merchant: str | None, description: str | None = None) -> str | None:
        hay = f" {catalog.norm_merchant(merchant)} {str(description or '').lower()} "
        for r in self.rules():                       # longest pattern first, user rules beat defaults on ties
            p = str(r.get("pattern") or "").lower()
            if p and p in hay and r.get("category") in self.category_map():
                return r["category"]
        return None

    def learn_rule(self, merchant: str, category: str) -> dict | None:
        pattern = catalog.norm_merchant(merchant)
        if len(pattern) < 3 or category not in self.category_map():
            return None
        rid = f"rule_{catalog.slug(pattern)}"
        return self.store.upsert("rule", rid, {"pattern": pattern, "category": category, "source": "user"},
                                 ref_id=category)

    def delete_rule(self, id: str) -> dict:
        self.get("rule", id)
        self.store.delete("rule", id)
        return {"deleted": True, "id": id}

    # ── transactions ─────────────────────────────────────────────────────────
    def _tx_rows(self) -> list[dict]:
        self.store.refresh()
        return self.store.items("tx")

    def find_ref(self, external_ref: str) -> dict | None:
        if not external_ref:
            return None
        for t in self._tx_rows():
            if t.get("external_ref") == external_ref:
                return t
        return None

    def add_tx(self, body: dict, *, source: str = "manual", link: bool = True) -> dict:
        amount = catalog.parse_amount(body.get("amount"))
        if amount is None or amount == 0:
            raise Invalid("importo mancante o zero")
        kind = body.get("type") or ""
        typed_category = self.resolve_category(body.get("category"))
        if not kind and typed_category:
            kind = {"income": "income"}.get(self.category_map()[typed_category].get("kind"), "")
        if not kind and source in ("manual", "quick", "chat") and amount > 0:
            kind = "expense"                     # «ho speso 12 €»: a typed positive amount is a spending
        if kind == "expense":
            amount = -abs(amount)
        elif kind == "income":
            amount = abs(amount)
        when = _d(body.get("date")) or self.today()
        external_ref = str(body.get("external_ref") or "").strip()
        existing = self.find_ref(external_ref)
        if existing:
            return {**existing, "duplicate": True}
        merchant = str(body.get("merchant") or "").strip()[:120]
        description = str(body.get("description") or "").strip()[:300]
        category = self.resolve_category(body.get("category"))
        status = "confirmed"
        if not category:
            category = self.categorize(merchant, description)
        if not category:
            category = "entrate" if amount > 0 else "altro"
            status = "to_review" if source in ("email", "statement", "phone") else "confirmed"
        data = {"date": when.isoformat(), "amount": round(amount, 2),
                "currency": str(body.get("currency") or self.currency()).upper()[:3],
                "merchant": merchant, "description": description, "category": category,
                "account": self.resolve_account(body.get("account")), "source": source if source in SOURCES else "manual",
                "external_ref": external_ref, "linked_to": None, "notes": str(body.get("notes") or "")[:500],
                "tags": [str(t)[:30] for t in body.get("tags") or []][:8], "status": body.get("status") or status,
                "import_id": body.get("import_id"), "mail_ref": body.get("mail_ref"), "created_at": now_iso()}
        tid = body.get("id") or _id("tx")
        out = self.store.upsert("tx", tid, data, ref_id=external_ref or None, at=f"{when.isoformat()}T12:00:00+00:00")
        if link:
            self.link_pass([out])
        return self.tx_view(self.store.data("tx", tid) or out)

    def update_tx(self, id: str, body: dict, *, learn: bool = False) -> dict:
        current = self.get("tx", id)
        data = {k: v for k, v in current.items() if k != "id"}
        if "amount" in body:
            amount = catalog.parse_amount(body["amount"])
            if amount is None or amount == 0:
                raise Invalid("importo non valido")
            kind = body.get("type") or ("income" if current.get("amount", 0) > 0 else "expense")
            data["amount"] = abs(amount) if kind == "income" else -abs(amount)
        if "category" in body:
            cat = self.resolve_category(body["category"])
            if not cat:
                raise Invalid(f"categoria «{body['category']}» sconosciuta")
            data["category"] = cat
            data["status"] = "confirmed"
            if learn and data.get("merchant"):
                self.learn_rule(data["merchant"], cat)
        if "date" in body:
            when = _d(body["date"])
            if not when:
                raise Invalid("data non valida")
            data["date"] = when.isoformat()
        if "account" in body:
            data["account"] = self.resolve_account(body["account"])
        for k in ("merchant", "description", "notes", "status", "tags", "currency"):
            if k in body:
                data[k] = body[k]
        if "linked_to" in body:
            data["linked_to"] = body["linked_to"] or None
            data["link_manual"] = True
        self.store.upsert("tx", id, data, ref_id=data.get("external_ref") or None, at=f"{data['date']}T12:00:00+00:00")
        return self.tx_view({**data, "id": id})

    def delete_tx(self, id: str) -> dict:
        tx = self.get("tx", id)
        self.store.delete("tx", id)
        for other in self._tx_rows():                # whoever was linked to it counts again
            if other.get("linked_to") == id:
                self.store.upsert("tx", other["id"], {**{k: v for k, v in other.items() if k != "id"},
                                                      "linked_to": None})
        return {"deleted": True, "id": id, "label": f"{tx.get('merchant') or 'Movimento'} eliminato"}

    def tx_view(self, t: dict) -> dict:
        cats = self.category_map()
        c = cats.get(t.get("category")) or {}
        return {**t, "category_label": c.get("label") or t.get("category"), "category_icon": c.get("icon"),
                "category_color": c.get("color"), "counted": self.counted(t, cats)}

    @staticmethod
    def counted(t: dict, cats: dict[str, dict]) -> bool:
        return not t.get("linked_to") and (cats.get(t.get("category")) or {}).get("kind") != "transfer"

    def transactions(self, *, month: str = "", since: str = "", until: str = "", category: str = "",
                     account: str = "", q: str = "", status: str = "", source: str = "", import_id: str = "",
                     limit: int = 500) -> list[dict]:
        rows = self._tx_rows()
        if month:
            start, end = self.month_range(month)
            rows = [t for t in rows if start.isoformat() <= t["date"] < end.isoformat()]
        if since:
            rows = [t for t in rows if t["date"] >= str(_d(since) or since)]
        if until:
            rows = [t for t in rows if t["date"] <= str(_d(until) or until)]
        if category:
            cat = self.resolve_category(category) or category
            rows = [t for t in rows if t.get("category") == cat]
        if account:
            rows = [t for t in rows if t.get("account") == catalog.slug(account)]
        if status:
            rows = [t for t in rows if t.get("status") == status]
        if source:
            rows = [t for t in rows if t.get("source") == source]
        if import_id:
            rows = [t for t in rows if t.get("import_id") == import_id]
        if q:
            k = q.lower()
            rows = [t for t in rows if k in f"{t.get('merchant', '')} {t.get('description', '')} {t.get('notes', '')}".lower()]
        rows.sort(key=lambda t: (t["date"], t.get("created_at") or ""), reverse=True)
        return [self.tx_view(t) for t in rows[: max(1, min(int(limit), 5000))]]

    # ── linking (no double counting) ─────────────────────────────────────────
    def link_pass(self, fresh: list[dict] | None = None) -> int:
        """Bank/card rows that are the money side of a PayPal payment → ``linked_to`` the PayPal row (detail kept,
        counted once). Same amount, within ``plutus.link.window_days``, bank text mentions PayPal."""
        window = int(self.setting("plutus.link.window_days", 3) or 3)
        rows = self._tx_rows()
        paypal_rows = [t for t in rows if t.get("account") == "paypal" and not t.get("linked_to")]
        taken = {t.get("linked_to") for t in rows if t.get("linked_to")}
        linked = 0
        for t in rows:
            if t.get("account") == "paypal" or t.get("linked_to") or t.get("link_manual"):
                continue
            text = f"{t.get('merchant', '')} {t.get('description', '')}".lower()
            if "paypal" not in text and "pp*" not in text:
                continue
            td = _d(t["date"])
            best = None
            for p in paypal_rows:
                if p["id"] in taken or abs(abs(p["amount"]) - abs(t["amount"])) > 0.01 or (p["amount"] > 0) != (t["amount"] > 0):
                    continue
                gap = abs((_d(p["date"]) - td).days)
                if gap <= window and (best is None or gap < best[0]):
                    best = (gap, p)
            if best:
                p = best[1]
                taken.add(p["id"])
                self.store.upsert("tx", t["id"], {**{k: v for k, v in t.items() if k != "id"}, "linked_to": p["id"]},
                                  ref_id=t.get("external_ref") or None, at=f"{t['date']}T12:00:00+00:00")
                linked += 1
                logger.info("event=plutus_linked bank=%s paypal=%s amount=%s", t["id"], p["id"], t["amount"])
        return linked

    # ── budgets ──────────────────────────────────────────────────────────────
    def budgets(self) -> dict[str, float]:
        self.store.refresh()
        return {b["id"].removeprefix("budget_"): float(b.get("amount") or 0) for b in self.store.items("budget")
                if float(b.get("amount") or 0) > 0}

    def set_budget(self, category: str, amount: Any) -> dict:
        target = "total" if catalog.slug(category) in ("total", "totale", "") else self.resolve_category(category)
        if not target:
            raise Invalid(f"categoria «{category}» sconosciuta")
        value = catalog.parse_amount(amount)
        if value is None or value < 0:
            raise Invalid("importo del budget non valido")
        bid = f"budget_{target}"
        if value == 0:
            self.store.delete("budget", bid)
        else:
            self.store.upsert("budget", bid, {"category": target, "amount": abs(value)}, ref_id=target)
        return {"category": target, "amount": abs(value)}

    # ── summaries ────────────────────────────────────────────────────────────
    def summary(self, month: str = "") -> dict:
        start, end = self.month_range(month or None)
        cats = self.category_map()
        rows = [t for t in self._tx_rows() if start.isoformat() <= t["date"] < end.isoformat()]
        counted = [t for t in rows if self.counted(t, cats)]
        spent = round(-sum(t["amount"] for t in counted if t["amount"] < 0 and cats.get(t["category"], {}).get("kind") != "income"), 2)
        income = round(sum(t["amount"] for t in counted if t["amount"] > 0), 2)
        budgets = self.budgets()
        by_cat: dict[str, float] = defaultdict(float)
        for t in counted:
            if t["amount"] < 0:
                by_cat[t["category"]] += -t["amount"]
        today = self.today()
        days_total = (end - start).days
        days_gone = max(1, min(days_total, (today - start).days + 1)) if start <= today < end else days_total
        categories = []
        for cid in sorted(set(by_cat) | {k for k in budgets if k != "total"}, key=lambda c: -by_cat.get(c, 0)):
            c = cats.get(cid) or {"label": cid}
            b = budgets.get(cid)
            categories.append({"id": cid, "label": c.get("label"), "icon": c.get("icon"), "color": c.get("color"),
                               "spent": round(by_cat.get(cid, 0), 2), "budget": b,
                               "pct": round(100 * by_cat.get(cid, 0) / b) if b else None})
        merchants: dict[str, float] = defaultdict(float)
        for t in counted:
            if t["amount"] < 0:
                merchants[t.get("merchant") or "—"] += -t["amount"]
        total_budget = budgets.get("total") or (sum(v for k, v in budgets.items() if k != "total") or None)
        return {"month": start.isoformat(), "label": self.month_label(start), "start": start.isoformat(),
                "end": (end - timedelta(days=1)).isoformat(), "currency": self.currency(), "spent": spent,
                "income": income, "net": round(income - spent, 2), "budget": total_budget,
                "left": round(total_budget - spent, 2) if total_budget else None,
                "pace": round(spent / days_gone * days_total, 2) if spent else 0.0,
                "days_gone": days_gone, "days_total": days_total, "categories": categories,
                "top_merchants": [{"merchant": m, "spent": round(v, 2)} for m, v in
                                  sorted(merchants.items(), key=lambda kv: -kv[1])[:5]],
                "count": len(rows), "to_review": sum(1 for t in rows if t.get("status") == "to_review"),
                "linked": sum(1 for t in rows if t.get("linked_to")),
                "recurring_next": [r for r in self.recurring() if r.get("status") == "confirmed"
                                   and r.get("next") and start.isoformat() <= r["next"] < end.isoformat()][:5]}

    def stats(self, months: int = 6) -> dict:
        months = max(1, min(int(months), 36))
        start, _ = self.month_range()
        cats = self.category_map()
        series = []
        for i in range(months - 1, -1, -1):
            s, e = self.month_range(_month_add(start, -i).replace(day=start.day))
            rows = [t for t in self._tx_rows() if s.isoformat() <= t["date"] < e.isoformat() and self.counted(t, cats)]
            by_cat: dict[str, float] = defaultdict(float)
            for t in rows:
                if t["amount"] < 0:
                    by_cat[t["category"]] += -t["amount"]
            series.append({"month": s.isoformat(), "label": self.month_label(s),
                           "spent": round(sum(by_cat.values()), 2),
                           "income": round(sum(t["amount"] for t in rows if t["amount"] > 0), 2),
                           "by_category": {k: round(v, 2) for k, v in by_cat.items()}})
        totals: dict[str, float] = defaultdict(float)
        for m in series:
            for k, v in m["by_category"].items():
                totals[k] += v
        merchants: dict[str, list[float]] = defaultdict(list)
        first = series[0]["month"]
        for t in self._tx_rows():
            if t["date"] >= first and self.counted(t, cats) and t["amount"] < 0:
                merchants[t.get("merchant") or "—"].append(-t["amount"])
        return {"currency": self.currency(), "months": series,
                "categories": [{"id": k, "label": (cats.get(k) or {}).get("label", k), "color": (cats.get(k) or {}).get("color"),
                                "total": round(v, 2), "avg": round(v / months, 2)}
                               for k, v in sorted(totals.items(), key=lambda kv: -kv[1])],
                "merchants": [{"merchant": m, "total": round(sum(v), 2), "count": len(v)}
                              for m, v in sorted(merchants.items(), key=lambda kv: -sum(kv[1]))[:15]],
                "avg_spent": round(sum(m["spent"] for m in series) / months, 2)}

    # ── recurring payments ───────────────────────────────────────────────────
    def detect_recurring(self) -> list[dict]:
        """Same merchant, similar amount (±15 %), regular interval (weekly / monthly / yearly), 3+ times
        (2 for yearly). Suggestions only: the user confirms or dismisses; dismissed ones are not proposed again."""
        cats = self.category_map()
        groups: dict[str, list[dict]] = defaultdict(list)
        for t in self._tx_rows():
            if t["amount"] < 0 and self.counted(t, cats) and t.get("merchant"):
                groups[catalog.norm_merchant(t["merchant"])].append(t)
        known = {r["id"]: r for r in self.store.items("recurring")}
        found = []
        for key, rows in groups.items():
            if len(rows) < 2 or not key:
                continue
            rows.sort(key=lambda t: t["date"])
            amounts = [-t["amount"] for t in rows]
            mid = median(amounts)
            if any(abs(a - mid) > 0.15 * mid for a in amounts[-3:]):
                continue
            gaps = [(_d(b["date"]) - _d(a["date"])).days for a, b in zip(rows, rows[1:])]
            g = median(gaps[-4:])
            period = "weekly" if 5 <= g <= 9 else "monthly" if 25 <= g <= 35 else "yearly" if 350 <= g <= 380 else ""
            if not period or (period != "yearly" and len(rows) < 3):
                continue
            rid = f"rec_{catalog.slug(key)}"
            prev = known.get(rid) or {}
            nxt = _d(rows[-1]["date"]) + timedelta(days={"weekly": 7, "monthly": 30, "yearly": 365}[period])
            data = {"merchant": rows[-1]["merchant"], "amount": round(mid, 2), "period": period,
                    "category": rows[-1].get("category"), "last": rows[-1]["date"], "next": nxt.isoformat(),
                    "count": len(rows), "status": prev.get("status") or "suggested",
                    # first seen (reflection signal «new subscription»); rows older than this field stay ""
                    "found_at": prev.get("found_at", "") if prev else self.today().isoformat()}
            if {k: prev.get(k) for k in data} != data:
                self.store.upsert("recurring", rid, data, ref_id=data["category"])
            found.append({**data, "id": rid})
        return found

    def recurring(self) -> list[dict]:
        self.store.refresh()
        rows = [r for r in self.store.items("recurring") if r.get("status") != "dismissed"]
        return sorted(rows, key=lambda r: (r.get("status") != "confirmed", r.get("next") or ""))

    def set_recurring(self, id: str, status: str) -> dict:
        if status not in ("confirmed", "dismissed", "suggested"):
            raise Invalid("stato: confirmed, dismissed o suggested")
        r = self.get("recurring", id)
        return self.store.upsert("recurring", id, {**{k: v for k, v in r.items() if k != "id"}, "status": status})

    # ── phone notifications (feed phone.notification from Hecate, Cindy 32) ──
    def process_phone(self, item: dict) -> dict:
        """A bank/payment app notification → a transaction (always to review: a notification is not a statement)."""
        parsed = phone.parse(str(item.get("app") or ""), str(item.get("title") or ""), str(item.get("text") or ""))
        if not parsed:
            return {"status": "ignored"}
        when = _d(item.get("at")) or self.today()
        tx = self.add_tx({"amount": parsed["amount"], "type": parsed["kind"], "currency": parsed["currency"],
                          "merchant": parsed["merchant"], "description": f"{item.get('app')}: {item.get('title') or ''}"[:200],
                          "date": when.isoformat(), "external_ref": phone.ref(item), "status": "to_review"},
                         source="phone")
        logger.info("event=plutus_phone_processed status=%s", "duplicate" if tx.get("duplicate") else "added")
        return {"status": "duplicate" if tx.get("duplicate") else "added", "tx_id": tx["id"], "amount": tx["amount"]}

    # ── PayPal mails (pushed by Iris) ────────────────────────────────────────
    def process_mail(self, record: dict) -> dict:
        """One raw mail record from Archive → transaction (or ignored). Idempotent by Gmail id / PayPal id."""
        payload = record.get("payload") or {}
        ref = str(payload.get("reference_id") or record.get("reference_id") or "")
        subject, body = str(payload.get("title") or ""), str(payload.get("body") or "")
        seen = self.store.data("mail", catalog.slug(ref)) if ref else None
        if seen:
            return {"status": "seen", "tx_id": seen.get("tx_id")}
        parsed = paypal.parse(subject, body)
        how = "parser"
        if not parsed and paypal.looks_like_money(subject, body):
            parsed, how = self._llm_mail(subject, body), "oracle"
        result: dict[str, Any] = {"status": "ignored", "how": how}
        if parsed and parsed.get("amount"):
            when = _d(payload.get("timestamp")) or self.today()
            ext = f"paypal:{parsed['txn_id']}" if parsed.get("txn_id") else f"mail:{payload.get('gmail_id') or ref}"
            tx = self.add_tx({"amount": parsed["amount"], "currency": parsed.get("currency"),
                              "merchant": parsed.get("merchant"), "description": subject[:200], "date": when.isoformat(),
                              "account": "paypal", "external_ref": ext, "mail_ref": ref,
                              "category": "entrate" if parsed.get("kind") == "received" else None},
                             source="email")
            result = {"status": "duplicate" if tx.get("duplicate") else "added", "how": how, "tx_id": tx["id"],
                      "amount": tx["amount"], "merchant": tx.get("merchant")}
        if ref:
            self.store.upsert("mail", catalog.slug(ref), {"ref": ref, "subject": subject[:120], **result})
        logger.info("event=plutus_mail_processed status=%s how=%s", result["status"], how)
        return result

    def _llm_mail(self, subject: str, body: str) -> dict | None:
        if not self.llm:
            return None
        flat = re.sub(r"\s+", " ", body)[:2500]
        prompt = ("Email PayPal. Estrai SOLO JSON {\"kind\": payment|refund|received|other, \"amount\": numero positivo, "
                  "\"currency\": EUR|USD|..., \"merchant\": chi, \"txn_id\": id transazione o \"\"}. "
                  f"Oggetto: {subject[:200]}\nTesto: {flat}")
        data = _json_from(self.llm(prompt))
        if not isinstance(data, dict) or data.get("kind") not in ("payment", "refund", "received"):
            return None
        amount = catalog.parse_amount(data.get("amount"))
        if not amount:
            return None
        amount = abs(amount)
        return {"kind": data["kind"], "amount": -amount if data["kind"] == "payment" else amount,
                "currency": str(data.get("currency") or self.currency()).upper()[:3],
                "merchant": str(data.get("merchant") or "PayPal")[:80], "txn_id": str(data.get("txn_id") or "")[:20]}

    def guess_categories(self, merchants: list[str]) -> dict[str, str]:
        """One Oracle call for the merchants no rule knows (statement import). Unknown → nothing (stays to review)."""
        if not self.llm or not merchants:
            return {}
        cats = [c for c in self.categories() if c.get("kind") != "transfer"]
        prompt = ("Categorie spese: " + ", ".join(f"{c['id']}={c['label']}" for c in cats)
                  + ". Per ogni esercente dai la categoria (id). SOLO JSON {\"esercente\": \"id\"}. Esercenti: "
                  + json.dumps(merchants[:60], ensure_ascii=False))
        data = _json_from(self.llm(prompt))
        valid = {c["id"] for c in cats}
        return {m: c for m, c in (data or {}).items() if isinstance(data, dict) and c in valid}

    # ── alerts / review / context ────────────────────────────────────────────
    def budget_alerts(self) -> list[dict]:
        s = self.summary()
        threshold = int(self.setting("plutus.alerts.threshold", 80) or 80)
        out = []
        cur = s["currency"]
        items = [c for c in s["categories"] if c.get("budget")]
        if s.get("budget"):
            items.append({"id": "total", "label": "Totale del mese", "spent": s["spent"], "budget": s["budget"],
                          "pct": round(100 * s["spent"] / s["budget"]) if s["budget"] else None})
        for c in items:
            pct = c.get("pct") or 0
            level = 100 if pct >= 100 else threshold if pct >= threshold else 0
            if not level:
                continue
            text = (f"{c['label']}: hai speso {c['spent']:.2f} {cur} su {c['budget']:.2f} ({pct}%)"
                    + (" — budget superato." if level == 100 else f" — oltre il {threshold}%."))
            out.append({"key": f"finance.budget.{c['id']}", "category": c["id"], "level": level, "pct": pct,
                        "text": text, "month": s["month"]})
        return out

    def review(self, month: str = "") -> dict:
        """Numbers of the previous budget month vs the one before (Oracle writes the text, Hermes delivers)."""
        cur_start, _ = self.month_range(month or None)
        prev_start, _ = self.month_range(_month_add(cur_start, -1).replace(day=cur_start.day))
        before_start, _ = self.month_range(_month_add(prev_start, -1).replace(day=prev_start.day))
        last, before = self.summary(prev_start.isoformat()), self.summary(before_start.isoformat())
        b_by = {c["id"]: c["spent"] for c in before["categories"]}
        changes = sorted(({"label": c["label"], "spent": c["spent"], "delta": round(c["spent"] - b_by.get(c["id"], 0), 2)}
                          for c in last["categories"]), key=lambda c: -abs(c["delta"]))[:4]
        return {"month": last["label"], "currency": last["currency"], "spent": last["spent"], "income": last["income"],
                "budget": last["budget"], "previous_spent": before["spent"],
                "over_budget": [c["label"] for c in last["categories"] if c.get("pct") and c["pct"] > 100],
                "biggest_changes": changes, "top_merchants": last["top_merchants"][:3],
                "new_recurring": [r["merchant"] for r in self.recurring() if r.get("status") == "suggested"][:5],
                "to_review": last["to_review"]}

    def recap(self, day: date, nxt: date) -> dict:
        """Facts for the daily recap (docs/work/2026-10-20-recap-giornaliero): spent and earned on ``day`` by
        category, movements to review, confirmed recurring payments due on ``nxt``, month budget. No LLM."""
        cats, cur = self.category_map(), self.currency()

        def money(v: float) -> str:
            return (f"{v:.0f}" if abs(v - round(v)) < 0.005 else f"{v:.2f}").replace(".", ",") + f" {cur}"

        rows = [t for t in self._tx_rows() if t["date"] == day.isoformat()]
        counted = [t for t in rows if self.counted(t, cats)]
        by_cat: dict[str, float] = defaultdict(float)
        for t in counted:
            if t["amount"] < 0 and cats.get(t.get("category"), {}).get("kind") != "income":
                by_cat[t.get("category")] += -t["amount"]
        done, upcoming = [], []
        spent = sum(by_cat.values())
        if spent:
            top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:3]
            done.append({"text": f"Spesi {money(spent)} ("
                                 + ", ".join(f"{(cats.get(c) or {}).get('label') or c or 'altro'} {money(v)}" for c, v in top)
                                 + ")"})
        income = sum(t["amount"] for t in counted if t["amount"] > 0)
        if income:
            done.append({"text": f"Entrate {money(income)}", "tone": "success"})
        review = sum(1 for t in rows if t.get("status") == "to_review")
        if review:
            done.append({"text": f"{review} moviment{'o' if review == 1 else 'i'} da rivedere", "tone": "warning"})
        for r in self.recurring():
            if r.get("status") == "confirmed" and r.get("next") == nxt.isoformat():
                upcoming.append({"text": f"{r['merchant']} {money(float(r.get('amount') or 0))}"})
        note = ""
        if done or upcoming:
            alerts = [a["text"] for a in self.budget_alerts()]
            if alerts:
                note = alerts[0]
            else:
                s = self.summary()
                if s.get("budget"):
                    note = f"{s['label']}: {money(s['spent'])} su {money(s['budget'])}"
        return {"done": done, "next": upcoming, "note": note}

    def context_text(self, budget: int = 400) -> str:
        s = self.summary()
        cur = s["currency"]
        parts = [f"Spese {s['label']}: {s['spent']:.0f}{cur}"
                 + (f"/{s['budget']:.0f} budget" if s.get("budget") else "")
                 + (f", ritmo {s['pace']:.0f}" if s.get("pace") and s["days_gone"] < s["days_total"] else "")]
        over = [f"{c['label']} {c['pct']}%" for c in s["categories"] if c.get("pct") and c["pct"] >= 80]
        if over:
            parts.append("budget alto: " + ", ".join(over[:4]))
        if s["categories"]:
            parts.append("top: " + ", ".join(f"{c['label']} {c['spent']:.0f}" for c in s["categories"][:3]))
        if s["to_review"]:
            parts.append(f"{s['to_review']} da rivedere")
        if s["recurring_next"]:
            parts.append("in arrivo: " + ", ".join(f"{r['merchant']} {r['amount']:.0f}" for r in s["recurring_next"][:3]))
        text = ". ".join(parts)
        return text if len(text) <= budget else text[: max(0, budget - 1)] + "…"

    # ── reflection signals (hestia_common.signals_client; Athena reads them, never the rows) ──
    PACE_MIN_DAYS = 5          # pace on fewer days of the month is noise
    UNUSUAL_RATIO = 1.5        # this week vs median of the previous 8
    TO_REVIEW_MIN = 5
    NEW_RECURRING_DAYS = 7

    def _sym(self) -> str:
        cur = self.currency()
        return "€" if cur == "EUR" else cur

    def weekly_spending(self, weeks: int = 12) -> dict[str, dict]:
        """``{YYYY-Www: {total, by_cat, rows}}`` of the last ``weeks`` ISO weeks (current last). Expenses only:
        counted rows, amount < 0, no income category (same rule as ``summary``)."""
        order = last_weeks(weeks, self.today())
        out = {w: {"total": 0.0, "by_cat": defaultdict(float), "rows": []} for w in order}
        cats = self.category_map()
        for t in self._tx_rows():
            d = _d(t.get("date"))
            w = iso_week(d) if d else None
            if w not in out or t["amount"] >= 0 or not self.counted(t, cats) \
                    or cats.get(t["category"], {}).get("kind") == "income":
                continue
            out[w]["total"] += -t["amount"]
            out[w]["by_cat"][t["category"]] += -t["amount"]
            out[w]["rows"].append(t)
        return out

    def signals(self) -> tuple[list[dict], list[dict]]:
        """Deterministic signals + weekly metrics (12 ISO weeks) for the reflection layer. Texts say «Spese»."""
        sym, cats = self._sym(), self.category_map()
        sigs: list[dict] = []
        # budget pace / over budget (month and per category)
        s = self.summary()
        items = [(c["id"], c["label"], c["spent"], c["budget"]) for c in s["categories"] if c.get("budget")]
        if s.get("budget"):
            items.append(("month", "del mese", s["spent"], s["budget"]))
        for cid, label, spent, budget in items:
            pace = round(spent / s["days_gone"] * s["days_total"], 2) if spent else 0.0
            name = f"Budget {label}" if cid != "month" else "Budget del mese"
            nums = {"spent": round(spent, 2), "budget": budget, "pace": pace, "days_gone": s["days_gone"],
                    "days_total": s["days_total"]}
            if spent >= budget:
                sigs.append(signal(f"budget_pace:{cid}", f"{name} superato: {spent:.0f}/{budget:.0f}{sym}.",
                                   kind="goal", severity="alta", metrics=nums, period=s["month"], page="budget"))
            elif s["days_gone"] >= self.PACE_MIN_DAYS and pace > budget:
                sigs.append(signal(f"budget_pace:{cid}", f"{name} a ritmo alto: {spent:.0f}/{budget:.0f}{sym}, "
                                   f"fine mese ~{pace:.0f}{sym}.", kind="goal", severity="attenzione", metrics=nums,
                                   period=s["month"], page="budget"))
        # unusual week vs median of the previous 8
        weeks = self.weekly_spending(12)
        order = list(weeks)
        this_week = order[-1]
        prev = [weeks[w]["total"] for w in order[-9:-1]]
        mid = median(prev) if prev else 0
        now = weeks[this_week]["total"]
        if mid > 0 and now > self.UNUSUAL_RATIO * mid:
            sigs.append(signal("unusual_week", f"Settimana di spesa alta: {now:.0f}{sym} contro {mid:.0f}{sym} "
                               "di solito.", kind="anomaly", severity="attenzione",
                               metrics={"spent": round(now, 2), "median_8w": round(mid, 2)}, period=this_week,
                               page="statistiche"))
        # recurring payments found in the last days
        since = (self.today() - timedelta(days=self.NEW_RECURRING_DAYS)).isoformat()
        for r in self.detect_recurring():
            if r.get("status") != "dismissed" and (r.get("found_at") or "") >= since:
                period = {"weekly": "settimanale", "monthly": "mensile", "yearly": "annuale"}.get(r["period"], "")
                sigs.append(signal(f"new_subscription:{r['id']}", f"Nuovo pagamento ricorrente: {r['merchant']} "
                                   f"{r['amount']:.2f}{sym} {period}.", kind="trend", severity="info",
                                   metrics={"amount": r["amount"], "count": r["count"]}, page="abbonamenti"))
        # rows waiting for a category
        n = sum(1 for t in self._tx_rows() if t.get("status") == "to_review")
        if n >= self.TO_REVIEW_MIN:
            sigs.append(signal("to_review", f"{n} movimenti di spesa da rivedere.", kind="trend", severity="info",
                               metrics={"count": n}, page="movimenti"))
        # weekly metrics: total + top 4 categories of the period
        mets = [metric("finance.spent", w, weeks[w]["total"], "Spesa settimanale") for w in order]
        totals: dict[str, float] = defaultdict(float)
        for w in order:
            for k, v in weeks[w]["by_cat"].items():
                totals[k] += v
        for cid, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:4]:
            label = (cats.get(cid) or {}).get("label") or cid
            mets += [metric(f"finance.spent.{cid}", w, weeks[w]["by_cat"].get(cid, 0.0), label) for w in order]
        return sigs, mets

    def topic_text(self, topic: str, budget: int = 400) -> str | None:
        """Detail behind one signal key (``/api/module/context?topic=``); unknown topic → None."""
        sym = self._sym()
        text = None
        if topic.startswith("budget_pace:"):
            cid = topic.split(":", 1)[1]
            s = self.summary()
            start = s["start"]
            if cid == "month" and s.get("budget"):
                text = (f"Budget mese {s['label']}: speso {s['spent']:.0f}/{s['budget']:.0f}{sym}, giorno "
                        f"{s['days_gone']}/{s['days_total']}, ritmo {s['pace']:.0f}. Categorie: "
                        + ", ".join(f"{c['label']} {c['spent']:.0f}" for c in s["categories"][:4]))
            else:
                c = next((c for c in s["categories"] if c["id"] == cid and c.get("budget")), None)
                if c:
                    pace = c["spent"] / s["days_gone"] * s["days_total"] if c["spent"] else 0
                    big = sorted((t for t in self.transactions(month=start, category=cid)
                                  if t.get("counted") and t["amount"] < 0), key=lambda t: t["amount"])[:4]
                    text = (f"{c['label']} {s['label']}: speso {c['spent']:.0f}/{c['budget']:.0f}{sym} "
                            f"({c['pct']}%), giorno {s['days_gone']}/{s['days_total']}, ritmo {pace:.0f}. "
                            "Più grandi: " + ", ".join(f"{t.get('merchant') or '—'} {-t['amount']:.0f} {t['date'][5:]}"
                                                       for t in big))
        elif topic == "unusual_week":
            weeks = self.weekly_spending(12)
            order = list(weeks)
            cur = weeks[order[-1]]
            mid = median([weeks[w]["total"] for w in order[-9:-1]])
            cats = self.category_map()
            top_c = sorted(cur["by_cat"].items(), key=lambda kv: -kv[1])[:3]
            merch: dict[str, float] = defaultdict(float)
            for t in cur["rows"]:
                merch[t.get("merchant") or "—"] += -t["amount"]
            text = (f"Settimana {order[-1]}: {cur['total']:.0f}{sym}, mediana 8 settimane {mid:.0f}{sym}. "
                    "Categorie: " + ", ".join(f"{(cats.get(k) or {}).get('label', k)} {v:.0f}" for k, v in top_c)
                    + ". Esercenti: " + ", ".join(f"{m} {v:.0f}" for m, v in
                                                  sorted(merch.items(), key=lambda kv: -kv[1])[:3]))
        elif topic.startswith("new_subscription:"):
            r = self.store.data("recurring", topic.split(":", 1)[1])
            if r:
                text = (f"Ricorrente {r['merchant']}: {r['amount']:.2f}{sym} {r['period']}, visto {r['count']} volte, "
                        f"ultimo {r['last']}, prossimo {r['next']}, stato {r['status']}.")
        elif topic == "to_review":
            rows = self.transactions(status="to_review", limit=6)
            text = (f"{len(self.transactions(status='to_review', limit=5000))} da rivedere. Ultimi: "
                    + ", ".join(f"{t.get('merchant') or '—'} {abs(t['amount']):.0f}" for t in rows))
        if text is None:
            return None
        return text if len(text) <= budget else text[: max(0, budget - 1)] + "…"

    # ── quick (Home) ─────────────────────────────────────────────────────────
    def quick_categories(self) -> list[dict]:
        used: dict[str, int] = defaultdict(int)
        since = (self.today() - timedelta(days=60)).isoformat()
        for t in self._tx_rows():
            if t["date"] >= since and t.get("source") in ("quick", "manual", "chat"):
                used[t.get("category")] += 1
        cats = [c for c in self.categories() if c.get("kind") == "expense"]
        cats.sort(key=lambda c: (-used.get(c["id"], 0), c.get("order", 99)))
        return [{"id": c["id"], "label": c["label"], "icon": c.get("icon"), "favorite": used.get(c["id"], 0) > 2}
                for c in cats[:8]]

    def export(self) -> dict:
        self.store.refresh()
        return {k: self.store.items(k) for k in ("tx", "category", "rule", "budget", "account", "recurring", "import")}
