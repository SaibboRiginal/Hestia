"""Kairos — deadlines of everything, with advice («Scadenze», dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 B7).

Bills, insurance, car tax, inspection, servicing, documents, subscriptions. A deadline has a due day, an optional
amount, a recurrence (rolls on when marked paid/done), a lead time and an advice line (deterministic per category;
the assistant may write a better one through Oracle use case ``kairos.consiglio``). Every open deadline is mirrored
in the calendar (agenda event ``kairos.<id>``). Mails arrive by push (Iris subscription ``kairos:mail``): a mail that
clearly names a due date becomes a **proposal** the owner confirms in a Hermes card; nothing is added on its own.
The daily agenda job sends one notice at the lead time and one on the day (``replaces``: never piling up).
"""
from __future__ import annotations

import calendar as _cal
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso

logger = logging.getLogger("hestia_kairos.service")

CATEGORIES = {
    "bolletta": ("Bolletta", 5, "Controlla la lettura e che l'addebito sia passato; confronta con lo stesso mese "
                                "dell'anno scorso."),
    "assicurazione": ("Assicurazione", 30, "Un mese prima chiedi due preventivi: spesso il rinnovo automatico costa "
                                           "di più."),
    "bollo": ("Bollo auto", 15, "Si paga online (PagoPA) o in tabaccheria; controlla la regione e l'importo."),
    "revisione": ("Revisione", 30, "Prenota il centro per tempo; porta libretto e certificato precedente."),
    "tagliando": ("Tagliando", 21, "Chiedi il preventivo prima e controlla cosa prevede il libretto di manutenzione."),
    "documento": ("Documento", 60, "Carta d'identità e passaporto: l'appuntamento in comune o in questura può "
                                   "richiedere settimane."),
    "abbonamento": ("Abbonamento", 7, "Decidi se tenerlo prima del rinnovo: disdire dopo costa un mese."),
    "tassa": ("Tasse", 15, "Controlla l'F24 o l'avviso; segna la ricevuta dopo il pagamento."),
    "altro": ("Scadenza", 7, ""),
}
RECURRENCES = ("none", "monthly", "bimonthly", "quarterly", "semiannual", "yearly", "biennial")
_MONTHS = {"none": 0, "monthly": 1, "bimonthly": 2, "quarterly": 3, "semiannual": 6, "yearly": 12, "biennial": 24}
_IT_MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
              "ottobre", "novembre", "dicembre")
_DATE_RES = (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b"),
             re.compile(r"\b(\d{1,2})\s+(" + "|".join(_IT_MONTHS) + r")\s+(\d{4})\b", re.I))
_DUE_WORDS = re.compile(r"scaden|entro il|da pagare|rinnov|revision|bollo|fattura|bolletta|pagamento entro", re.I)
_AMOUNT = re.compile(r"(?:€|EUR)\s?(\d[\d.]*,\d{2}|\d+(?:\.\d{2})?)|(\d[\d.]*,\d{2})\s?(?:€|EUR|euro)", re.I)
_CATEGORY_WORDS = (("bolletta", r"bollett|luce|gas|acqua|energia|enel|fattura"), ("assicurazione", r"assicura|polizza|rca"),
                   ("bollo", r"bollo"), ("revisione", r"revision"), ("tagliando", r"tagliand|manutenzion"),
                   ("documento", r"carta d'identit|passaporto|patente|permesso"), ("abbonamento", r"abbonament|rinnovo"),
                   ("tassa", r"f24|imu|tari|tassa|agenzia delle entrate"))


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


def guess_category(text: str) -> str:
    low = (text or "").lower()
    return next((c for c, rx in _CATEGORY_WORDS if re.search(rx, low)), "altro")


def find_due(text: str, today: date) -> date | None:
    """The first future date in a text that talks about a deadline (deterministic; None when unsure)."""
    if not _DUE_WORDS.search(text or ""):
        return None
    for rx in _DATE_RES:
        for m in rx.finditer(text):
            d, mo, y = m.group(1), m.group(2), m.group(3)
            mo = _IT_MONTHS.index(mo.lower()) + 1 if not mo.isdigit() else int(mo)
            y = int(y) + (2000 if len(y) == 2 else 0)
            try:
                when = date(y, mo, int(d))
            except ValueError:
                continue
            if today <= when <= today + timedelta(days=800):
                return when
    return None


def find_amount(text: str) -> float | None:
    m = _AMOUNT.search(text or "")
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).replace(".", "").replace(",", ".") if "," in (m.group(1) or m.group(2)) \
        else (m.group(1) or m.group(2))
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


class Deadlines:
    def __init__(self, store, get: Callable[[str, Any], Any], *, tz_name: str = "Europe/Rome", hub=None,
                 agenda=None):
        self.store = store
        self.get = get
        self.tz = ZoneInfo(tz_name)
        self.hub = hub
        self.agenda = agenda

    def today(self) -> date:
        return datetime.now(self.tz).date()

    # ── reading ─────────────────────────────────────────────────────────────
    def view(self, d: dict) -> dict:
        due = date.fromisoformat(d["due"])
        label, lead, advice = CATEGORIES.get(d.get("category") or "altro", CATEGORIES["altro"])
        return {**d, "category_label": label, "in_days": (due - self.today()).days,
                "advice": d.get("advice") or advice,
                "lead_days": d.get("lead_days") if d.get("lead_days") is not None else lead}

    def list(self, status: str = "open", days: int | None = None, category: str = "") -> list[dict]:
        self.store.refresh()
        rows = [self.view(d) for d in self.store.items("deadline")
                if (not status or d.get("status") == status) and (not category or d.get("category") == category)]
        if days is not None:
            rows = [d for d in rows if d["in_days"] <= days]
        return sorted(rows, key=lambda d: d["due"])

    def find(self, ref: str) -> dict:
        self.store.refresh()
        d = self.store.data("deadline", ref)
        if d:
            return d
        q = str(ref or "").strip().casefold()
        hits = [d for d in self.store.items("deadline") if d.get("status") in ("open", "proposed")
                and q and q in d.get("title", "").casefold()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise NotFound(f"nessuna scadenza «{ref}»")
        raise Invalid("più scadenze corrispondono: " + ", ".join(h["title"] for h in hits[:5]))

    # ── writing ─────────────────────────────────────────────────────────────
    def save(self, body: dict, did: str | None = None, *, source: str = "manual", status: str = "open") -> dict:
        old = self.find(did) if did else {}
        title = str(body.get("title") or old.get("title") or "").strip()[:120]
        if not title:
            raise Invalid("serve un titolo (es. «Bollo auto»)")
        try:
            due = date.fromisoformat(str(body.get("due") or old.get("due") or "")[:10])
        except ValueError:
            raise Invalid("data di scadenza AAAA-MM-GG") from None
        category = body.get("category") or old.get("category") or guess_category(title)
        category = category if category in CATEGORIES else "altro"
        recurrence = body.get("recurrence") or old.get("recurrence") or "none"
        if recurrence not in RECURRENCES:
            raise Invalid("ricorrenza: " + ", ".join(RECURRENCES))
        amount = body.get("amount", old.get("amount"))
        data = {**{k: v for k, v in old.items() if k != "id"}, "title": title, "due": due.isoformat(),
                "category": category, "recurrence": recurrence,
                "amount": round(float(amount), 2) if amount not in (None, "") else None,
                "lead_days": int(body["lead_days"]) if body.get("lead_days") not in (None, "") else old.get("lead_days"),
                "notes": str(body.get("notes", old.get("notes") or ""))[:1000],
                "status": old.get("status") or status, "source": old.get("source") or source,
                "mail_ref": body.get("mail_ref") or old.get("mail_ref"), "updated_at": now_iso()}
        did = old.get("id") or new_id("d")
        self.store.upsert("deadline", did, data, at=f"{data['due']}T12:00:00+00:00")
        out = self.view({**data, "id": did})
        if out["status"] == "open":
            self._calendar(out)
        logger.info("event=deadline_saved category=%s source=%s status=%s", category, data["source"], data["status"])
        return out

    def _calendar(self, d: dict) -> None:
        if not self.agenda:
            return
        start = datetime.combine(date.fromisoformat(d["due"]), datetime.min.time().replace(hour=9), self.tz)
        self.agenda.show(f"kairos.{d['id']}", f"Scadenza: {d['title']}", start,
                         description=(f"{d['amount']:.2f} €. " if d.get("amount") else "") + (d.get("advice") or ""),
                         end_at=start + timedelta(minutes=30), params={"deadline_id": d["id"]})

    def done(self, ref: str) -> dict:
        """Paid / done: a recurring deadline rolls on to the next due day, a one-off one closes."""
        d = self.find(ref)
        months = _MONTHS.get(d.get("recurrence") or "none", 0)
        data = {**{k: v for k, v in d.items() if k != "id"}, "last_done": self.today().isoformat(),
                "updated_at": now_iso(), "notified": {}}
        if months:
            data["due"] = add_months(date.fromisoformat(d["due"]), months).isoformat()
        else:
            data["status"] = "done"
        self.store.upsert("deadline", d["id"], data, at=f"{data['due']}T12:00:00+00:00")
        if months:
            self._calendar(self.view({**data, "id": d["id"]}))
        elif self.agenda:
            self.agenda.done(f"kairos.{d['id']}")
        return self.view({**data, "id": d["id"]})

    def snooze(self, ref: str, days: int = 3) -> dict:
        d = self.find(ref)
        data = {**{k: v for k, v in d.items() if k != "id"}, "snoozed_until":
                (self.today() + timedelta(days=max(1, int(days)))).isoformat(), "updated_at": now_iso()}
        self.store.upsert("deadline", d["id"], data, at=f"{d['due']}T12:00:00+00:00")
        return self.view({**data, "id": d["id"]})

    def delete(self, ref: str) -> dict:
        d = self.find(ref)
        self.store.delete("deadline", d["id"])
        if self.agenda:
            self.agenda.cancel(f"kairos.{d['id']}")
        return {"deleted": True, "title": d["title"]}

    def confirm(self, did: str) -> dict:
        d = self.find(did)
        if d.get("status") != "proposed":
            return self.view(d)
        data = {**{k: v for k, v in d.items() if k != "id"}, "status": "open", "updated_at": now_iso()}
        self.store.upsert("deadline", d["id"], data, at=f"{d['due']}T12:00:00+00:00")
        out = self.view({**data, "id": d["id"]})
        self._calendar(out)
        return out

    def dismiss(self, did: str) -> dict:
        d = self.find(did)
        self.store.upsert("deadline", d["id"], {**{k: v for k, v in d.items() if k != "id"}, "status": "dismissed",
                                                "updated_at": now_iso()})
        return {"dismissed": True}

    def set_advice(self, ref: str, advice: str) -> dict:
        d = self.find(ref)
        data = {**{k: v for k, v in d.items() if k != "id"}, "advice": advice.strip()[:500], "updated_at": now_iso()}
        self.store.upsert("deadline", d["id"], data, at=f"{d['due']}T12:00:00+00:00")
        return self.view({**data, "id": d["id"]})

    # ── mail (pushed by Iris) ───────────────────────────────────────────────
    def from_mail(self, record: dict) -> dict:
        """One mail record → a proposed deadline (Hermes card) when it clearly names a future due day."""
        payload = record.get("payload") or {}
        ref = str(payload.get("reference_id") or record.get("reference_id") or record.get("id") or "")
        subject, body = str(payload.get("title") or ""), str(payload.get("body") or "")
        if ref and any(d.get("mail_ref") == ref for d in self.store.items("deadline")):
            return {"status": "seen"}
        text = f"{subject}\n{body}"
        due = find_due(text, self.today())
        if not due:
            return {"status": "ignored"}
        d = self.save({"title": subject[:120] or "Scadenza da email", "due": due.isoformat(),
                       "amount": find_amount(text), "category": guess_category(text), "mail_ref": ref},
                      source="mail", status="proposed")
        if self.hub:
            amount = f" · {d['amount']:.2f} €" if d.get("amount") else ""
            self.hub.notify({"event_type": "service.action_required", "domain": "deadlines",
                             "entity_id": f"kairos-proposal-{d['id']}",
                             "payload": {"kind": "kairos.proposal", "service": "kairos", "_source": "Scadenze",
                                         "_title": "Nuova scadenza?", "level": "info", "target": "owner", "icon": "clock",
                                         "_message": f"<b>{d['title']}</b> entro il {due.strftime('%d/%m/%Y')}{amount}.",
                                         "_actions": [
                                             {"id": "si", "label": "Aggiungi", "style": "primary", "service": "kairos",
                                              "path": f"/api/deadlines/{d['id']}/confirm", "body": {}, "resolves": True},
                                             {"id": "no", "label": "No", "service": "kairos",
                                              "path": f"/api/deadlines/{d['id']}/dismiss", "body": {}, "resolves": True}]}})
        return {"status": "proposed", "id": d["id"]}

    # ── daily notices ───────────────────────────────────────────────────────
    def daily(self) -> dict:
        sent = 0
        today = self.today().isoformat()
        for d in self.list("open"):
            if d.get("snoozed_until") and d["snoozed_until"] > today:
                continue
            stage = "today" if d["in_days"] <= 0 else ("lead" if d["in_days"] <= d["lead_days"] else "")
            if not stage or (d.get("notified") or {}).get(stage) == d["due"]:
                continue
            when = "oggi" if d["in_days"] == 0 else ("scaduta" if d["in_days"] < 0 else f"tra {d['in_days']} giorni")
            if self.hub:
                self.hub.notify({"event_type": "service.action_required", "domain": "deadlines",
                                 "entity_id": f"kairos-{d['id']}",
                                 "payload": {"kind": "kairos.due", "service": "kairos", "_source": "Scadenze",
                                             "_title": f"{d['title']} {when}", "target": "owner", "icon": "clock",
                                             "level": "warning" if stage == "today" else "info",
                                             "_message": d.get("advice") or "", "replaces": f"kairos.{d['id']}",
                                             "_actions": [{"id": "fatto", "label": "Fatto", "style": "primary",
                                                           "service": "kairos", "path": f"/api/deadlines/{d['id']}/done",
                                                           "body": {}, "resolves": True},
                                                          {"id": "dopo", "label": "Fra 3 giorni", "service": "kairos",
                                                           "path": f"/api/deadlines/{d['id']}/snooze",
                                                           "body": {"days": 3}}]}})
            raw = self.store.data("deadline", d["id"]) or {}
            raw["notified"] = {**(raw.get("notified") or {}), stage: d["due"]}
            self.store.upsert("deadline", d["id"], {k: v for k, v in raw.items() if k != "id"},
                              at=f"{d['due']}T12:00:00+00:00")
            sent += 1
        return {"sent": sent}

    def recap(self, day: date, nxt: date) -> dict:
        soon = [d for d in self.list("open", days=7)]
        return {"next": [{"text": f"{d['title']} " + ("scaduta" if d["in_days"] < 0 else "oggi" if d["in_days"] == 0
                                                      else f"tra {d['in_days']} giorni"),
                          "tone": "warning" if d["in_days"] <= 1 else ""} for d in soon[:4]]}
