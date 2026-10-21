"""Outdoor activities (run, bike, walk…) — light intentions next to the gym, never a Garmin replacement.

Dossier docs/work/2026-10-20-meteo-hecate §3.8. «Ho voglia di correre 2 volte questa settimana» →
``propose`` picks the best slots of the week from the forecast at the place (Hecate) and the free time in the
calendar; nothing reaches the calendar until ``confirm``. A confirmed slot becomes an event in Marko's Google
calendar «Allenamenti» (owned by Hercules: activities and finished gym sessions = the training history) and a
one-off agenda task that asks afterwards «L'hai fatto?» (Fatto / Non fatto / Spostato). A morning agenda job
nudges «Ottimo giorno per…» only while an intention is open. Partial data is fine.

Store kinds: ``activity_plan`` (the weekly intention with its slots), ``activity`` (one done activity),
``calendar_link`` (session/slot → provider event), ``activity_nudge`` (one marker per morning message).
The slot picker (``score_hour`` / ``pick_slots``) is pure; ``Activities`` wires store, Hub and agenda.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import domain
from .store import now_iso

logger = logging.getLogger("hestia_hercules.activities")

KINDS = {"corsa": "Corsa", "bici": "Bici", "camminata": "Camminata", "nuoto": "Nuoto", "altro": "Attività"}
ALIASES = {"run": "corsa", "running": "corsa", "correre": "corsa", "jogging": "corsa", "bike": "bici",
           "bicicletta": "bici", "ciclismo": "bici", "walk": "camminata", "camminare": "camminata",
           "passeggiata": "camminata", "hike": "camminata", "escursione": "camminata", "swim": "nuoto",
           "nuotare": "nuoto", "piscina": "nuoto"}
SLOT_STATUS = ("proposed", "planned", "done", "missed", "moved", "cancelled")
CALENDAR_NAME = "Allenamenti"
EARLIEST, LATEST = 6, 21          # hours a slot may start
GOOD_SCORE = 70                    # «ottimo giorno» threshold


def kind_of(text: Any) -> str:
    k = domain._str(text, 40).lower().strip()
    k = ALIASES.get(k, k)
    return k if k in KINDS else ("altro" if k else "corsa")


def label(kind: str) -> str:
    return KINDS.get(kind, "Attività")


# ── normalizers (registered in domain.NORMALIZERS) ─────────────────────────
def norm_plan(d: dict) -> dict:
    times = domain._num(d.get("times"), lo=0, hi=14, integer=True)
    slots = []
    for s in d.get("slots") or []:
        if not isinstance(s, dict) or not s.get("start"):
            continue
        status = s.get("status") or "proposed"
        if status not in SLOT_STATUS:
            raise domain.Invalid(f"stato non valido: {status}")
        slots.append({**s, "id": s.get("id") or domain.new_id(), "status": status})
    return {**d, "kind": kind_of(d.get("kind")), "times": 1 if times is None else times,
            "minutes": domain._num(d.get("minutes"), lo=10, hi=600, integer=True) or 45,
            "place": domain._str(d.get("place"), 120), "week_from": domain._str(d.get("week_from"), 10),
            "week_to": domain._str(d.get("week_to"), 10), "status": d.get("status") or "proposed", "slots": slots}


def norm_activity(d: dict) -> dict:
    if not d.get("date"):
        raise domain.Invalid("data mancante")
    return {**d, "kind": kind_of(d.get("kind")), "date": domain._str(d.get("date"), 10),
            "minutes": domain._num(d.get("minutes"), lo=1, hi=1440, integer=True),
            "km": domain._num(d.get("km"), lo=0, hi=1000), "note": domain._str(d.get("note"), 300),
            "status": d.get("status") or "done"}


# ── slot picker (pure) ──────────────────────────────────────────────────────
def score_hour(h: dict, *, sunrise: str = "", sunset: str = "", kind: str = "corsa") -> tuple[int, list[str]]:
    """0–100 for starting the activity at hour ``h`` (Hecate hour row) + the reasons."""
    hh = int(str(h.get("time") or "T00")[11:13] or 0)
    why: list[str] = []
    score = 100
    rain = h.get("rain_prob") or 0
    if rain >= 60 or (h.get("rain_mm") or 0) >= 1:
        return 0, ["pioggia"]
    if rain >= 30:
        score -= 35
        why.append(f"pioggia possibile {rain}%")
    if sunrise and sunset and not (sunrise[:5] <= f"{hh:02d}:30" and f"{hh:02d}:00" < sunset[:5]):
        return 0, ["buio"]
    if not h.get("is_day", True) and not (sunrise and sunset):
        return 0, ["buio"]
    t = h.get("feels_c") if h.get("feels_c") is not None else h.get("temp_c")
    lo, hi = (8, 20) if kind in ("corsa", "camminata") else (12, 24)
    if t is not None:
        if t < lo - 8 or t > hi + 10:
            return 0, [f"{t}° troppo {'freddo' if t < lo else 'caldo'}"]
        if t < lo:
            score -= int((lo - t) * 4)
            why.append(f"fresco ({t}°)")
        elif t > hi:
            score -= int((t - hi) * 4)
            why.append(f"caldo ({t}°)")
        else:
            why.append(f"{t}°")
    wind = h.get("wind_kmh") or 0
    if wind > 30:
        score -= min(40, int((wind - 30) * 2))
        why.append(f"vento {wind} km/h")
    if rain < 30:
        why.append("asciutto")
    if hh in (7, 8, 17, 18, 19):          # usual training hours: a small preference, never a rule
        score += 5
    return max(0, min(100, score)), why


def _overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    return any(start < b1 and b0 < end for b0, b1 in busy)


def best_of_day(day: str, hours: list[dict], *, minutes: int, busy: list[tuple[datetime, datetime]],
                sunrise: str = "", sunset: str = "", kind: str = "corsa", not_before: datetime | None = None,
                tz=None) -> dict | None:
    """Best free starting hour of ``day`` (needs the whole duration dry and free)."""
    best = None
    rows = [h for h in hours if str(h.get("time", "")).startswith(day)]
    for i, h in enumerate(rows):
        hh = int(h["time"][11:13])
        if not EARLIEST <= hh <= LATEST:
            continue
        start = datetime.fromisoformat(h["time"]).replace(tzinfo=tz)
        end = start + timedelta(minutes=minutes)
        if not_before and start < not_before:
            continue
        if _overlaps(start, end, busy):
            continue
        sc, why = score_hour(h, sunrise=sunrise, sunset=sunset, kind=kind)
        nxt = rows[i + 1] if i + 1 < len(rows) and minutes > 60 else None
        if nxt:
            sc2, _ = score_hour(nxt, sunrise=sunrise, sunset=sunset, kind=kind)
            sc = min(sc, sc2 + 10)
        if sc and (best is None or sc > best["score"]):
            best = {"start": start.isoformat(), "end": end.isoformat(), "score": sc, "why": why,
                    "weather": {k: h.get(k) for k in ("temp_c", "condition", "icon", "rain_prob")}}
    return best


def pick_slots(candidates: list[dict], times: int) -> list[dict]:
    """``times`` best days, avoiding back-to-back days when there is a choice."""
    ranked = sorted([c for c in candidates if c], key=lambda c: -c["score"])
    chosen: list[dict] = []
    for spaced in (True, False):
        for c in ranked:
            if len(chosen) >= times:
                break
            if c in chosen:
                continue
            d = date.fromisoformat(c["start"][:10])
            if spaced and any(abs((date.fromisoformat(x["start"][:10]) - d).days) < 2 for x in chosen):
                continue
            chosen.append(c)
    return sorted(chosen, key=lambda c: c["start"])


def slot_text(slot: dict) -> str:
    s = datetime.fromisoformat(slot["start"])
    w = slot.get("weather") or {}
    days = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    out = f"{days[s.weekday()]} {s.day} alle {s:%H:%M}"
    if w.get("temp_c") is not None:
        out += f", {w['temp_c']}°"
    if w.get("condition"):
        out += f" {w['condition']}"
    return out


# ── service ─────────────────────────────────────────────────────────────────
class Activities:
    def __init__(self, hercules, call: Callable[..., tuple[int, Any]], agenda=None, *, api: str = "/api/hercules"):
        """``call(service, method, path, body=, query=, timeout=)`` = Hub route (raises on transport errors)."""
        self.h = hercules
        self.call = call
        self.agenda = agenda
        self.api = api

    # ── helpers ─────────────────────────────────────────────────────────────
    @property
    def tz(self):
        return self.h.tz

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _week(self, which: str = "") -> tuple[date, date]:
        """Rest of this week (from today) or the whole next one, by the personal week start."""
        today = self.h.today()
        ws = self.h.week_start()
        start = today - timedelta(days=(today.weekday() - ws) % 7)
        if str(which).lower() in ("next", "prossima", "prossima settimana"):
            start += timedelta(days=7)
            return start, start + timedelta(days=6)
        return today, start + timedelta(days=6)

    def _hecate(self, method: str, path: str, **kw) -> dict:
        try:
            status, payload = self.call("hecate", method, path, **kw)
        except Exception as exc:
            logger.warning("[🔄] event=hercules_hecate_failed path=%s error=%s", path, exc)
            return {"status": "unavailable"}
        if status >= 400 or not isinstance(payload, dict):
            return {"status": "unavailable", "code": status}
        return payload

    def forecast(self, place: str, d0: date, d1: date) -> dict:
        q = {"date_from": d0.isoformat(), "date_to": d1.isoformat(), "hourly": "true", **({"place": place} if place else {})}
        return self._hecate("GET", "api/gateway/weather/forecast", query=q, timeout=8)

    def busy(self, d0: date, d1: date) -> list[tuple[datetime, datetime]]:
        """Busy intervals of Marko's calendars (all providers, primary) + slots already planned here."""
        out: list[tuple[datetime, datetime]] = []
        ev = self._hecate("GET", "api/gateway/calendar/events", timeout=12, query={
            "start_datetime": datetime.combine(d0, datetime.min.time(), self.tz).isoformat(),
            "end_datetime": datetime.combine(d1 + timedelta(days=1), datetime.min.time(), self.tz).isoformat(),
            "max_results": 250})
        for e in ev.get("events") or []:
            try:
                s, t = str(e.get("start_datetime") or ""), str(e.get("end_datetime") or "")
                if len(s) <= 10:              # all-day events do not block an hour
                    continue
                out.append((datetime.fromisoformat(s.replace("Z", "+00:00")), datetime.fromisoformat(t.replace("Z", "+00:00"))))
            except ValueError:
                continue
        for p in self.h.store.items("activity_plan"):
            for s in p.get("slots") or []:
                if s.get("status") == "planned":
                    out.append((datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])))
        return out

    def plans(self, *, open_only: bool = False) -> list[dict]:
        rows = sorted(self.h.store.items("activity_plan"), key=lambda p: p.get("week_from") or "")
        if open_only:
            today = self.h.today().isoformat()
            rows = [p for p in rows if p.get("status") == "confirmed" and (p.get("week_to") or "") >= today]
        return rows

    def logs(self, d0: date | None = None, d1: date | None = None) -> list[dict]:
        rows = [a for a in self.h.store.items("activity") if a.get("status", "done") == "done"]
        if d0:
            rows = [a for a in rows if a.get("date", "") >= d0.isoformat()]
        if d1:
            rows = [a for a in rows if a.get("date", "") <= d1.isoformat()]
        return sorted(rows, key=lambda a: a.get("date", ""))

    def progress(self, plan: dict) -> dict:
        done = [a for a in self.logs(date.fromisoformat(plan["week_from"]), date.fromisoformat(plan["week_to"]))
                if a.get("kind") == plan.get("kind")]
        times = int(plan.get("times") or 0)
        return {"done": len(done), "times": times, "remaining": max(0, times - len(done)),
                "hint": f"{label(plan['kind'])} {len(done)}/{times}"}

    def _candidates(self, plan: dict, d0: date, d1: date, *, exclude_days: set[str] | None = None) -> tuple[list[dict], dict]:
        f = self.forecast(plan.get("place") or "", d0, d1)
        if f.get("status") != "ok":
            return [], f
        hours = [h for d in f.get("days") or [] for h in d.get("hours") or []]
        busy = self.busy(d0, d1)
        now = self._now() + timedelta(minutes=30)
        cands = []
        for d in f.get("days") or []:
            if exclude_days and d["date"] in exclude_days:
                continue
            c = best_of_day(d["date"], hours, minutes=int(plan.get("minutes") or 45), busy=busy,
                            sunrise=d.get("sunrise") or "", sunset=d.get("sunset") or "", kind=plan.get("kind", "corsa"),
                            not_before=now, tz=self.tz)
            if c:
                cands.append(c)
        return cands, f

    # ── propose / confirm ───────────────────────────────────────────────────
    def propose(self, kind: str = "corsa", times: int = 1, place: str = "", minutes: int = 45, week: str = "") -> dict:
        """Best slots for the intention (nothing in the calendar yet). Without forecast: the intention alone."""
        d0, d1 = self._week(week)
        plan = {"kind": kind_of(kind), "times": max(1, int(times or 1)), "minutes": int(minutes or 45),
                "place": place or "", "week_from": d0.isoformat(), "week_to": d1.isoformat(), "status": "proposed",
                "created_at": now_iso()}
        cands, f = self._candidates(plan, d0, d1)
        chosen = pick_slots(cands, plan["times"])
        plan["slots"] = [{**c, "id": domain.new_id(), "status": "proposed"} for c in chosen]
        saved = self.h.save("activity_plan", plan)
        out = {"plan_id": saved["id"], "kind": label(saved["kind"]), "times": saved["times"],
               "week": f"{d0.isoformat()} → {d1.isoformat()}", "place": (f.get("place") or {}).get("label") or place,
               "slots": [{"n": i + 1, "id": s["id"], "when": slot_text(s), "start": s["start"], "why": s["why"]}
                         for i, s in enumerate(saved["slots"])],
               "next": "Conferma con fitness_confirm_activity (plan_id, slots facoltativi): nulla va in calendario prima."}
        if f.get("status") != "ok":
            out["weather"] = f.get("status")
            out["hint"] = ("Previsione non disponibile: posso salvare solo l'intenzione e ti propongo i giorni al mattino"
                           if f.get("status") != "needs_place" else "Aggiungi Casa nei tuoi luoghi per avere il meteo")
        elif len(chosen) < plan["times"]:
            out["hint"] = f"Solo {len(chosen)} momenti buoni questa settimana (pioggia, buio o impegni)"
        logger.info("event=hercules_activity_proposed kind=%s times=%s slots=%s", saved["kind"], saved["times"], len(chosen))
        return out

    def confirm(self, plan_id: str, slots: list | None = None) -> dict:
        """Confirm the intention; ``slots`` = numbers/ids of proposed slots to keep or ISO starts (default: all)."""
        plan = self.h.get("activity_plan", plan_id)
        proposed = [s for s in plan.get("slots") or [] if s.get("status") == "proposed"]
        keep: list[dict] = []
        if slots is None:
            keep = proposed
        else:
            for x in slots:
                xs = str(x).strip()
                hit = next((s for i, s in enumerate(proposed) if xs in (s["id"], str(i + 1))), None)
                if hit:
                    keep.append(hit)
                elif len(xs) >= 13:            # an explicit time from the user: «giovedì alle 19»
                    start = datetime.fromisoformat(xs)
                    start = start if start.tzinfo else start.replace(tzinfo=self.tz)
                    keep.append({"id": domain.new_id(), "start": start.isoformat(), "why": ["scelto da te"],
                                 "end": (start + timedelta(minutes=int(plan.get("minutes") or 45))).isoformat()})
        kept_ids = {s["id"] for s in keep}
        new_slots = [s for s in plan.get("slots") or [] if s.get("status") != "proposed"]
        for s in keep:
            new_slots.append({**s, "status": "planned"})
        for s in proposed:
            if s["id"] not in kept_ids:
                new_slots.append({**s, "status": "cancelled"})
        plan.update(status="confirmed", slots=new_slots, confirmed_at=now_iso())
        plan = self.h.save("activity_plan", plan, id=plan_id)
        for s in plan["slots"]:
            if s["status"] == "planned" and s["id"] in kept_ids:
                self._schedule(plan, s)
        planned = [s for s in plan["slots"] if s["status"] == "planned"]
        logger.info("event=hercules_activity_confirmed plan=%s slots=%s", plan_id, len(planned))
        return {"confirmed": True, "plan_id": plan_id, "kind": label(plan["kind"]), "times": plan["times"],
                "planned": [slot_text(s) for s in planned],
                "note": "Eventi nel calendario «Allenamenti»; dopo ogni uscita ti chiedo se l'hai fatta."
                        if planned else "Intenzione salvata: al mattino ti dico quando è un buon momento."}

    def add_slot(self, plan_id: str, start: str = "") -> dict:
        """«Pianifica» from the morning message or the plugin: a new planned slot (default: best today)."""
        plan = self.h.get("activity_plan", plan_id)
        if start:
            st = datetime.fromisoformat(start)
            st = st if st.tzinfo else st.replace(tzinfo=self.tz)
            slot = {"id": domain.new_id(), "start": st.isoformat(), "why": ["scelto da te"],
                    "end": (st + timedelta(minutes=int(plan.get("minutes") or 45))).isoformat()}
        else:
            today = self.h.today()
            cands, _ = self._candidates(plan, today, today)
            if not cands:
                return {"error": "oggi non vedo un buon momento"}
            slot = {**cands[0], "id": domain.new_id()}
        slot["status"] = "planned"
        plan["slots"] = [*(plan.get("slots") or []), slot]
        if plan.get("status") == "proposed":
            plan["status"] = "confirmed"
        plan = self.h.save("activity_plan", plan, id=plan_id)
        self._schedule(plan, slot)
        return {"planned": slot_text(slot), "plan_id": plan_id, "slot_id": slot["id"]}

    # ── slot outcome ────────────────────────────────────────────────────────
    def _slot(self, plan_id: str, slot_id: str) -> tuple[dict, dict]:
        plan = self.h.get("activity_plan", plan_id)
        slot = next((s for s in plan.get("slots") or [] if s.get("id") == slot_id), None)
        if not slot:
            raise domain.Invalid("momento non trovato")
        return plan, slot

    def _set_slot(self, plan: dict, slot_id: str, **changes) -> dict:
        plan["slots"] = [{**s, **changes} if s.get("id") == slot_id else s for s in plan.get("slots") or []]
        return self.h.save("activity_plan", plan, id=plan["id"])

    def slot_done(self, plan_id: str, slot_id: str, minutes: int | None = None, km: float | None = None) -> dict:
        plan, slot = self._slot(plan_id, slot_id)
        if slot.get("status") != "done":
            self.h.save("activity", {"kind": plan["kind"], "date": slot["start"][:10], "at": slot["start"],
                                     "minutes": minutes or plan.get("minutes"), "km": km, "plan_id": plan_id,
                                     "slot_id": slot_id, "source": "slot"})
        plan = self._set_slot(plan, slot_id, status="done")
        self._event_title(plan, slot, done=True)
        self._close_question(slot_id, "Fatto")
        return {"done": True, **self.progress(plan)}

    def slot_missed(self, plan_id: str, slot_id: str) -> dict:
        plan, slot = self._slot(plan_id, slot_id)
        plan = self._set_slot(plan, slot_id, status="missed")
        self._event_title(plan, slot, done=False)
        self._close_question(slot_id, "Non fatto")
        return {"missed": True, **self.progress(plan)}

    def slot_moved(self, plan_id: str, slot_id: str, to: str = "") -> dict:
        """Moved: the old slot goes, a new one is planned (``to`` or the best one left this week)."""
        plan, slot = self._slot(plan_id, slot_id)
        plan = self._set_slot(plan, slot_id, status="moved")
        self._unschedule(plan, slot)
        self._close_question(slot_id, "Spostato")
        if to:
            return {"moved": True, **self.add_slot(plan_id, to)}
        d0 = max(self.h.today(), date.fromisoformat(plan["week_from"]))
        d1 = date.fromisoformat(plan["week_to"])
        used = {s["start"][:10] for s in plan["slots"] if s.get("status") in ("planned", "done")}
        cands, _ = self._candidates(plan, d0, d1, exclude_days=used | {slot["start"][:10]})
        if not cands:
            return {"moved": True, "planned": None, "note": "Nessun altro buon momento questa settimana"}
        best = pick_slots(cands, 1)[0]
        return {"moved": True, **self.add_slot(plan_id, best["start"])}

    def log(self, kind: str = "corsa", day: str = "", minutes: int | None = None, km: float | None = None,
            note: str = "") -> dict:
        """«Ho corso 5 km»: one done activity; a planned slot of the same kind that day becomes done."""
        d = day or self.h.today().isoformat()
        k = kind_of(kind)
        for plan in self.plans():
            for s in plan.get("slots") or []:
                if s.get("status") == "planned" and s["start"][:10] == d and plan.get("kind") == k:
                    return {**self.slot_done(plan["id"], s["id"], minutes=minutes, km=km), "slot": slot_text(s)}
        a = self.h.save("activity", {"kind": k, "date": d, "at": now_iso(), "minutes": minutes, "km": km,
                                     "note": note, "source": "log"})
        self._history_event_for_log(a)
        open_plan = next((p for p in self.plans(open_only=True) if p.get("kind") == k
                          and p["week_from"] <= d <= p["week_to"]), None)
        return {"logged": True, "id": a["id"], "kind": label(k), "date": d,
                **(self.progress(open_plan) if open_plan else {})}

    def unlog(self, id: str) -> dict:
        """Undo a log: the activity goes; a slot it had closed is planned again, its history event goes."""
        a = self.h.get("activity", id)
        out = self.h.delete("activity", id)
        if a.get("plan_id") and a.get("slot_id"):
            try:
                plan, slot = self._slot(a["plan_id"], a["slot_id"])
                self._set_slot(plan, slot["id"], status="planned")
                self._update_event(f"slot:{slot['id']}", {"title": label(plan["kind"])})
            except (domain.Invalid, LookupError):
                pass
        else:
            self._delete_event(f"activity:{id}")
        return out

    # ── calendar «Allenamenti» + agenda ─────────────────────────────────────
    def _calendar(self) -> str | None:
        r = self._hecate("POST", "api/gateway/calendar/calendars", body={"name": CALENDAR_NAME, "provider": "google"})
        return r.get("calendar_id") if r.get("status") == "ok" else None

    def _create_event(self, link_id: str, title: str, start: str, end: str, *, location: str = "",
                      description: str = "", reminders: list[int] | None = None) -> None:
        if self.h.store.data("calendar_link", link_id):
            return
        cal = self._calendar()
        if not cal:
            logger.warning("[🔄] event=hercules_calendar_sync_failed link=%s reason=no_calendar fallback=next_write", link_id)
            return
        r = self._hecate("POST", "api/gateway/calendar/events", timeout=15, body={
            "event": {"title": title, "start_datetime": start, "end_datetime": end, "location": location or None,
                      "description": description or None, "timezone": str(self.tz),
                      "reminders_minutes_before": reminders or []},
            "target_providers": ["google"], "calendar_id": cal, "nag": False})
        ok = next((x for x in r.get("results") or [] if x.get("success")), None)
        if not ok:
            logger.warning("[🔄] event=hercules_calendar_sync_failed link=%s fallback=next_write", link_id)
            return
        self.h.store.write([{"kind": "calendar_link", "id": link_id, "at": now_iso(),
                             "data": {"event_id": ok["event_id"], "calendar_id": cal, "provider": "google"}}])
        logger.info("event=hercules_calendar_event_created link=%s", link_id)

    def _update_event(self, link_id: str, updates: dict) -> None:
        link = self.h.store.data("calendar_link", link_id)
        if not link:
            return
        self._hecate("PUT", f"api/gateway/calendar/events/{link['event_id']}", timeout=15,
                     body={"provider": link.get("provider", "google"), "calendar_id": link["calendar_id"],
                           "updates": updates})

    def _delete_event(self, link_id: str) -> None:
        link = self.h.store.data("calendar_link", link_id)
        if not link:
            return
        self._hecate("DELETE", f"api/gateway/calendar/events/{link['event_id']}", timeout=15,
                     query={"provider": link.get("provider", "google"), "calendar_id": link["calendar_id"]})
        self.h.store.delete("calendar_link", link_id)

    def _schedule(self, plan: dict, slot: dict) -> None:
        w = slot.get("weather") or {}
        desc = "Pianificato da Hestia" + (f" · previsione {w.get('temp_c')}°, {w.get('condition')}" if w else "")
        self._create_event(f"slot:{slot['id']}", label(plan["kind"]), slot["start"], slot["end"],
                           location=plan.get("place") or "", description=desc, reminders=[30])
        if self.agenda:
            ask_at = datetime.fromisoformat(slot["end"]) + timedelta(minutes=30)
            self.agenda.plan(f"hercules.activity.{slot['id']}", f"{label(plan['kind'])}: l'hai fatto?", ask_at,
                             action={"service": "hercules", "method": "POST",
                                     "path": f"{self.api}/activities/{plan['id']}/slots/{slot['id']}/ask"},
                             description=f"{label(plan['kind'])} {slot_text(slot)}: dopo ti chiedo se l'hai fatto.",
                             params={"place": plan.get("place") or "", "start": slot["start"]})

    def _unschedule(self, plan: dict, slot: dict) -> None:
        self._delete_event(f"slot:{slot['id']}")
        if self.agenda:
            self.agenda.cancel(f"hercules.activity.{slot['id']}")

    def _event_title(self, plan: dict, slot: dict, *, done: bool) -> None:
        # Google shows no icons: a check / cross in the title is the only mark there (Hestia clients use icons)
        self._update_event(f"slot:{slot['id']}", {"title": f"{label(plan['kind'])} {'✓' if done else '✗'}"})
        if self.agenda:
            self.agenda.done(f"hercules.activity.{slot['id']}")

    def _close_question(self, slot_id: str, outcome: str = "Segnato") -> None:
        """Answered from anywhere (plugin, chat): the live «L'hai fatto?» closes (Hermes ``closes``)."""
        key = f"hercules.activity.{slot_id}"
        try:
            self.call("hermes", "POST", "api/events/ingest", timeout=5, body={
                "event_type": "service.action_required", "domain": "fitness", "entity_id": key,
                "payload": {"closes": key, "decision": "done", "outcome_text": outcome, "_source": "hercules"}})
        except Exception as exc:
            logger.warning("[🔄] event=hercules_question_close_failed error=%s fallback=expires_on_its_own", exc)

    def _history_event_for_log(self, a: dict) -> None:
        start = datetime.fromisoformat(f"{a['date']}T{datetime.now(self.tz):%H:%M}").replace(tzinfo=self.tz)
        minutes = int(a.get("minutes") or 45)
        title = f"{label(a['kind'])} ✓" + (f" {a['km']} km" if a.get("km") else "")
        self._create_event(f"activity:{a['id']}", title, (start - timedelta(minutes=minutes)).isoformat(),
                           start.isoformat())

    def sync_sessions(self, days: int = 14) -> int:
        """Finished gym sessions → events in «Allenamenti» (history). Idempotent through ``calendar_link``."""
        since = (self.h.today() - timedelta(days=days)).isoformat()
        n = 0
        for s in self.h.store.items("session"):
            if s.get("status") != "done" or str(s.get("started_at") or "")[:10] < since:
                continue
            if self.h.store.data("calendar_link", f"session:{s['id']}"):
                continue
            end = s.get("ended_at") or s.get("started_at")
            self._create_event(f"session:{s['id']}", s.get("name") or "Palestra", s["started_at"], end,
                               description="Allenamento registrato in Hestia")
            n += 1
        return n

    # ── questions to Marko (Hermes) ─────────────────────────────────────────
    def ask(self, plan_id: str, slot_id: str) -> dict | None:
        """The «L'hai fatto?» message for a slot that is still planned (None = nothing to ask)."""
        plan, slot = self._slot(plan_id, slot_id)
        if slot.get("status") != "planned":
            return None
        base = f"{self.api}/activities/{plan_id}/slots/{slot_id}"
        s = datetime.fromisoformat(slot["start"])
        text = f"Hai fatto la {label(plan['kind']).lower()} delle {s:%H:%M}?"
        actions = [{"id": "done", "label": "Fatto", "text": "Fatto", "style": "primary", "service": "hercules",
                    "method": "POST", "path": f"{base}/done", "body": {}, "resolves": True},
                   {"id": "missed", "label": "Non fatto", "text": "Non fatto", "service": "hercules", "method": "POST",
                    "path": f"{base}/missed", "body": {}, "resolves": True},
                   {"id": "moved", "label": "Spostato", "text": "Spostato", "service": "hercules", "method": "POST",
                    "path": f"{base}/moved", "body": {}, "resolves": True}]
        return {"key": f"hercules.activity.{slot_id}", "text": text, "actions": actions}

    def morning(self) -> dict | None:
        """Morning coach line: rain on today's slot → offer to move; else a good window and the week behind →
        «Ottimo giorno per…». One message a day at most, only while an intention is open."""
        today = self.h.today()
        if any(r.get("day") == today.isoformat() for r in self.h.store.items("activity_nudge")):
            return {"skip": "sent_today"}
        for plan in self.plans(open_only=True):
            prog = self.progress(plan)
            if prog["remaining"] <= 0:
                continue
            todays = [s for s in plan["slots"] if s.get("status") == "planned" and s["start"][:10] == today.isoformat()]
            cands, f = self._candidates(plan, today, today)
            if f.get("status") != "ok":
                continue
            base = f"{self.api}/activities/{plan['id']}"
            name = label(plan["kind"]).lower()
            if todays:
                slot = todays[0]
                hour = next((h for d in f["days"] for h in d.get("hours") or [] if h["time"][:13] == slot["start"][:13]), None)
                if hour and score_hour(hour, kind=plan["kind"])[0] >= 40:
                    continue                              # the planned slot still holds: nothing to say
                alt = cands[0] if cands else None
                text = f"Pioggia alle {slot['start'][11:16]} per la {name}"
                actions = []
                if alt and alt["start"][:13] != slot["start"][:13]:
                    text += f": meglio alle {alt['start'][11:16]}?"
                    actions.append({"id": "move", "label": f"Sposta alle {alt['start'][11:16]}", "style": "primary",
                                    "service": "hercules", "method": "POST",
                                    "path": f"{base}/slots/{slot['id']}/moved", "body": {"to": alt["start"]},
                                    "resolves": True})
                else:
                    text += ": oggi non vedo finestre asciutte. Spostiamo a un altro giorno?"
                    actions.append({"id": "move", "label": "Altro giorno", "style": "primary", "service": "hercules",
                                    "method": "POST", "path": f"{base}/slots/{slot['id']}/moved", "body": {},
                                    "resolves": True})
                actions.append({"id": "keep", "label": "Tengo", "service": "hercules", "method": "POST",
                                "path": f"{base}/keep", "body": {}, "resolves": True})
                return {"key": f"hercules.activity.morning.{plan['id']}", "text": text, "actions": actions}
            future = [s for s in plan["slots"] if s.get("status") == "planned" and s["start"][:10] > today.isoformat()]
            if len(future) >= prog["remaining"] or not cands or cands[0]["score"] < GOOD_SCORE:
                continue
            best = cands[0]
            w = best.get("weather") or {}
            text = (f"Ottimo giorno per {'la ' + name if plan['kind'] != 'altro' else 'muoverti'}: "
                    f"{best['start'][11:16]}–{best['end'][11:16]}"
                    + (f", {w['temp_c']}°" if w.get("temp_c") is not None else "")
                    + (f", {w['condition']}" if w.get("condition") else "") + f" · {prog['hint']}")
            actions = [{"id": "plan", "label": "Pianifica", "style": "primary", "service": "hercules", "method": "POST",
                        "path": f"{base}/slots", "body": {"start": best["start"]}, "resolves": True},
                       {"id": "no", "label": "Non oggi", "service": "hercules", "method": "POST", "path": f"{base}/keep",
                        "body": {}, "resolves": True}]
            return {"key": f"hercules.activity.morning.{plan['id']}", "text": text, "actions": actions}
        return None

    def mark_nudge(self) -> None:
        self.h.store.write([{"kind": "activity_nudge", "id": domain.new_id(), "at": now_iso(), "data": {"at": now_iso(), "day": self.h.today().isoformat()}}])

    # ── views ───────────────────────────────────────────────────────────────
    def week(self) -> dict:
        """This week's intentions with progress and slots (plugin week widget, summary, recap)."""
        d0, d1 = self._week()
        out = []
        for p in self.plans():
            if p.get("status") not in ("confirmed",) or not (p["week_from"] <= d1.isoformat() and p["week_to"] >= d0.isoformat()):
                continue
            out.append({"id": p["id"], "kind": p["kind"], "label": label(p["kind"]), "place": p.get("place") or "",
                        **self.progress(p),
                        "slots": [{"id": s["id"], "start": s["start"], "end": s["end"], "status": s["status"],
                                   "when": slot_text(s)} for s in p["slots"] if s["status"] in ("planned", "done", "missed")]})
        logs = self.logs(d0 - timedelta(days=(d0.weekday() - self.h.week_start()) % 7), d1)
        return {"intentions": out, "done": [{"id": a["id"], "kind": a["kind"], "label": label(a["kind"]), "date": a["date"],
                                             "minutes": a.get("minutes"), "km": a.get("km")} for a in logs]}

    def cancel(self, plan_id: str) -> dict:
        plan = self.h.get("activity_plan", plan_id)
        for s in plan.get("slots") or []:
            if s.get("status") == "planned":
                self._unschedule(plan, s)
        plan["slots"] = [{**s, "status": "cancelled"} if s.get("status") in ("planned", "proposed") else s
                         for s in plan.get("slots") or []]
        plan["status"] = "cancelled"
        self.h.save("activity_plan", plan, id=plan_id)
        return {"cancelled": True}
