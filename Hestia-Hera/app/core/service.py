"""Hera — the important people («Persone», dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A4).

A card per person: relation, birthday and other dates, likes and dislikes, gift ideas (from conversations: the
assistant adds them with ``people_gift_idea``), notes, last contact and how often Marko wants to hear from them.
Dates go to the calendar as Chronos special events (``POST /api/special``, stable key ``hera-<id>-<n>``, the
owner's edits in the calendar win); on the day Chronos pushes ``special_moment`` here and Hera answers with the gift
ideas. A daily agenda job sends one notice per person that is due a call (``contact_every_days``).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso

logger = logging.getLogger("hestia_hera.service")

RELATIONS = ("partner", "famiglia", "amico", "collega", "altro")
DATE_KINDS = ("birthday", "anniversary", "custom")
_MMDD = re.compile(r"^(?:(\d{4})-)?(\d{2})-(\d{2})$")


def parse_day(text: Any) -> str:
    """``YYYY-MM-DD`` or ``MM-DD`` (year unknown) or ``DD/MM[/YYYY]`` → normalised; Invalid otherwise."""
    s = str(text or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$", s)
    if m:
        s = f"{m.group(3) + '-' if m.group(3) else ''}{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = _MMDD.match(s)
    if not m:
        raise Invalid("data non valida: usa GG/MM o AAAA-MM-GG")
    year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    try:
        date(int(year or 2000), month, day)
    except ValueError:
        raise Invalid("data non valida: questo giorno non esiste") from None
    return f"{year + '-' if year else ''}{month:02d}-{day:02d}"


def next_occurrence(day: str, today: date) -> date:
    m = _MMDD.match(day)
    month, d = int(m.group(2)), int(m.group(3))
    for year in (today.year, today.year + 1):
        try:
            when = date(year, month, d)
        except ValueError:                                  # 29/02 in a common year → 28/02
            when = date(year, month, 28)
        if when >= today:
            return when
    return when


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [v for v in re.split(r"[,;]\s*", value) if v.strip()]
    return [str(v).strip()[:120] for v in value or [] if str(v).strip()][:40]


class People:
    def __init__(self, store, get: Callable[[str, Any], Any], *, tz_name: str = "Europe/Rome", hub=None):
        self.store = store
        self.get = get
        self.tz = ZoneInfo(tz_name)
        self.hub = hub

    def today(self) -> date:
        return datetime.now(self.tz).date()

    # ── cards ───────────────────────────────────────────────────────────────
    def list(self, query: str = "") -> list[dict]:
        self.store.refresh()
        q = query.strip().casefold()
        rows = [self.view(p) for p in self.store.items("person")
                if not q or q in p.get("name", "").casefold() or q in (p.get("relation") or "")]
        return sorted(rows, key=lambda p: p["name"].casefold())

    def find(self, ref: str) -> dict:
        self.store.refresh()
        p = self.store.data("person", ref)
        if p:
            return p
        q = str(ref or "").strip().casefold()
        hits = [p for p in self.store.items("person") if p.get("name", "").casefold() == q] or \
               [p for p in self.store.items("person") if q and q in p.get("name", "").casefold()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise NotFound(f"nessuna persona «{ref}»")
        raise Invalid("più persone corrispondono: " + ", ".join(h["name"] for h in hits[:5]))

    def view(self, p: dict) -> dict:
        today = self.today()
        dates = []
        for i, d in enumerate(p.get("dates") or []):
            nxt = next_occurrence(d["day"], today)
            dates.append({**d, "n": i, "next": nxt.isoformat(), "in_days": (nxt - today).days})
        due = None
        if p.get("contact_every_days") and p.get("last_contact"):
            last = date.fromisoformat(p["last_contact"][:10])
            due = (last + timedelta(days=int(p["contact_every_days"])) - today).days
        return {**p, "dates": dates, "contact_due_in": due,
                "gift_ideas": [g for g in p.get("gift_ideas") or [] if not g.get("done")]}

    def save(self, body: dict, pid: str | None = None) -> dict:
        old = self.find(pid) if pid else {}
        name = str(body.get("name") or old.get("name") or "").strip()[:80]
        if not name:
            raise Invalid("serve il nome")
        relation = body.get("relation", old.get("relation") or "altro")
        relation = relation if relation in RELATIONS else "altro"
        dates = old.get("dates") or []
        if body.get("birthday"):
            dates = [d for d in dates if d.get("kind") != "birthday"] + [
                {"kind": "birthday", "label": "Compleanno", "day": parse_day(body["birthday"]),
                 "lead_days": int(body.get("lead_days") or 7)}]
        for d in body.get("dates") or []:
            dates.append({"kind": d.get("kind") if d.get("kind") in DATE_KINDS else "custom",
                          "label": str(d.get("label") or "Data importante")[:60], "day": parse_day(d.get("day")),
                          "lead_days": int(d.get("lead_days") or 7)})
        data = {**{k: v for k, v in old.items() if k != "id"}, "name": name, "relation": relation, "dates": dates,
                "likes": _list(body["likes"]) if "likes" in body else old.get("likes") or [],
                "dislikes": _list(body["dislikes"]) if "dislikes" in body else old.get("dislikes") or [],
                "notes": str(body.get("notes", old.get("notes") or ""))[:2000],
                "contact_every_days": int(body["contact_every_days"]) if body.get("contact_every_days") else
                old.get("contact_every_days"),
                "gift_ideas": old.get("gift_ideas") or [], "last_contact": old.get("last_contact"),
                "updated_at": now_iso()}
        pid = old.get("id") or new_id("p")
        self.store.upsert("person", pid, data, ref_id=name.casefold())
        self.sync_calendar({**data, "id": pid})
        logger.info("event=person_saved dates=%d", len(dates))
        return self.view({**data, "id": pid})

    def delete(self, ref: str) -> dict:
        p = self.find(ref)
        self.store.delete("person", p["id"])
        for i, _ in enumerate(p.get("dates") or []):
            self._hub("DELETE", f"api/special/hera-{p['id']}-{i}")
        return {"deleted": True, "name": p["name"]}

    # ── what the assistant learns in conversations ──────────────────────────
    def gift_idea(self, ref: str, text: str, source: str = "chat") -> dict:
        p = self.find(ref)
        text = str(text or "").strip()[:200]
        if not text:
            raise Invalid("quale idea regalo?")
        ideas = p.get("gift_ideas") or []
        if any(g["text"].casefold() == text.casefold() for g in ideas):
            return self.view(p)
        ideas.append({"id": new_id("g"), "text": text, "source": source, "at": now_iso(), "done": False})
        return self._patch(p, gift_ideas=ideas)

    def gift_done(self, ref: str, idea_id: str) -> dict:
        p = self.find(ref)
        ideas = [{**g, "done": True} if g["id"] == idea_id else g for g in p.get("gift_ideas") or []]
        return self._patch(p, gift_ideas=ideas)

    def like(self, ref: str, text: str, dislike: bool = False) -> dict:
        p = self.find(ref)
        key = "dislikes" if dislike else "likes"
        values = p.get(key) or []
        if text.strip() and text.strip().casefold() not in {v.casefold() for v in values}:
            values.append(text.strip()[:120])
        return self._patch(p, **{key: values})

    def contact(self, ref: str, note: str = "", when: str = "") -> dict:
        p = self.find(ref)
        day = when or self.today().isoformat()
        self.store.upsert("interaction", new_id("i"), {"person_id": p["id"], "date": day, "note": note[:500]},
                          parent_id=p["id"], at=f"{day}T12:00:00+00:00")
        return self._patch(p, last_contact=day)

    def _patch(self, p: dict, **changes) -> dict:
        data = {**{k: v for k, v in p.items() if k != "id"}, **changes, "updated_at": now_iso()}
        self.store.upsert("person", p["id"], data, ref_id=p["name"].casefold())
        return self.view({**data, "id": p["id"]})

    # ── calendar and moments ────────────────────────────────────────────────
    def _hub(self, method: str, path: str, body: Any = None) -> Any:
        if not self.hub:
            return None
        try:
            return self.hub.ok("chronos", method, path, body=body, timeout=10)
        except Exception as exc:
            logger.warning("[🔄] event=hera_calendar_failed path=%s error=%s fallback=next_save", path, exc)
            return None

    def sync_calendar(self, p: dict) -> None:
        """Every date of the card → a yearly special event in the calendar (Chronos keeps the owner's edits)."""
        for i, d in enumerate(p.get("dates") or []):
            day = d["day"] if len(d["day"]) == 10 else f"2000-{d['day']}"
            title = f"{d['label']} di {p['name']}" if d["kind"] != "custom" else f"{d['label']} · {p['name']}"
            self._hub("POST", "api/special", {"title": title, "day": day, "kind": d["kind"], "lead_days": d["lead_days"],
                                              "person": p["name"], "person_id": p["id"], "yearly": True,
                                              "source": "persone", "key": f"hera-{p['id']}-{i}", "by": "hera"})

    def upcoming(self, days: int = 30) -> list[dict]:
        out = []
        for p in self.list():
            for d in p["dates"]:
                if d["in_days"] <= days:
                    out.append({"person": p["name"], "person_id": p["id"], "label": d["label"], "next": d["next"],
                                "in_days": d["in_days"], "gift_ideas": [g["text"] for g in p["gift_ideas"]][:5]})
        return sorted(out, key=lambda x: x["in_days"])

    def moment(self, moment: dict) -> dict:
        """Chronos ``special_moment`` of today: a person's date → the gift ideas as a notice."""
        pid = moment.get("person_id")
        p = self.store.data("person", pid) if pid else None
        if not p:
            return {"handled": False}
        ideas = [g["text"] for g in p.get("gift_ideas") or [] if not g.get("done")][:5]
        if self.hub and ideas:
            self.hub.notify({"event_type": "service.action_required", "domain": "people", "entity_id": f"hera-{pid}",
                             "payload": {"kind": "hera.gift", "service": "hera", "_source": "Persone",
                                         "_title": f"Idee per {p['name']}", "level": "info", "target": "owner",
                                         "_message": "Hai segnato: " + "; ".join(ideas), "icon": "heart",
                                         "replaces": f"hera.gift.{pid}",
                                         "_link": {"module": "hera", "page": f"persona/{pid}"}}})
        return {"handled": True, "ideas": len(ideas)}

    def daily(self) -> dict:
        """Agenda job: one «senti …» notice per person due a contact today (never piling up: ``replaces``)."""
        due = [p for p in self.list() if p.get("contact_due_in") is not None and p["contact_due_in"] <= 0]
        for p in due:
            if self.hub:
                self.hub.notify({"event_type": "service.action_required", "domain": "people",
                                 "entity_id": f"hera-contact-{p['id']}",
                                 "payload": {"kind": "hera.contact", "service": "hera", "_source": "Persone",
                                             "_title": f"Senti {p['name']}?", "level": "info", "target": "owner",
                                             "_message": f"L'ultima volta: {p['last_contact']}.", "icon": "user",
                                             "replaces": f"hera.contact.{p['id']}",
                                             "_actions": [{"id": "fatto", "label": "Sentito", "service": "hera",
                                                           "path": f"/api/people/{p['id']}/contact", "body": {},
                                                           "resolves": True}]}})
        return {"due": len(due)}

    def recap(self, day: date, nxt: date) -> dict:
        soon = [u for u in self.upcoming(7) if u["in_days"] <= (nxt - self.today()).days + 6]
        return {"next": [{"text": f"{u['label']} di {u['person']} " + ("domani" if u["in_days"] == 1 else
                                                                       f"tra {u['in_days']} giorni"
                                                                       if u["in_days"] else "oggi")}
                         for u in soon[:4]]}
