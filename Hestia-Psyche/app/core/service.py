"""Psyche — how the owner feels over time («Umore», dossier docs/work/2026-10-30-diario-umore).

A check-in is one row ``mood``: mood 1–5 (required), energy and stress 1–5 (optional), labels and causes from a
closed vocabulary, a note, and — when it came from chat — the owner's own words (``quote``). Rows come from a tap
(Home, page, Telegram, the evening check-in), from a tool, or from Oracle's quiet capture (``capture``: a chat
capture within ``psyche.capture.merge_minutes`` of the previous one of the same day updates it instead of adding).
Everything derived (day summary, trend, insights, signals, recap) is computed here, deterministically; no model.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso, parse_dt

logger = logging.getLogger("hestia_psyche.service")

KIND = "mood"
LABELS = ("stanco", "carico", "sereno", "contento", "motivato", "annoiato", "nervoso", "ansioso", "triste", "giù",
          "arrabbiato", "malato")
CAUSES = ("lavoro", "sonno", "persone", "salute", "sport", "soldi", "casa", "tempo libero", "meteo")
SOURCES = ("chat", "tap", "webui", "telegram", "external", "checkin")
MOOD_WORDS = {1: "a terra", 2: "giù", 3: "così così", 4: "bene", 5: "benissimo"}
WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
QUOTE_MAX = 200
NOTE_MAX = 1000


def _level(value: Any, field: str, required: bool = False) -> int | None:
    if value in (None, ""):
        if required:
            raise Invalid(f"{field}: serve un numero da 1 a 5")
        return None
    try:
        n = int(round(float(str(value).replace(",", "."))))
    except ValueError as exc:
        raise Invalid(f"{field}: serve un numero da 1 a 5") from exc
    if not 1 <= n <= 5:
        raise Invalid(f"{field}: serve un numero da 1 a 5")
    return n


def _vocab(values: Any, allowed: tuple[str, ...]) -> list[str]:
    """Keep only words of the vocabulary (case and «giu/giù» tolerant), in order, no duplicates."""
    if isinstance(values, str):
        values = [v for v in values.replace(";", ",").split(",")]
    out: list[str] = []
    norm = {a.replace("ù", "u"): a for a in allowed}
    for v in values or []:
        key = str(v or "").strip().lower().replace("ù", "u")
        if key in norm and norm[key] not in out:
            out.append(norm[key])
    return out


def mood_word(level: int | float | None) -> str:
    return MOOD_WORDS.get(int(round(level)), "") if level else ""


class Psyche:
    def __init__(self, store, get: Callable[..., Any], *, tz_name: str = "Europe/Rome"):
        self.store = store
        self.get = get
        self.tz = ZoneInfo(tz_name)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    # ── writing ─────────────────────────────────────────────────────────────
    def _clean(self, body: dict, old: dict | None = None) -> dict:
        old = old or {}
        d = dict(old)
        if "mood" in body or not old:
            d["mood"] = _level(body.get("mood"), "mood", required=True)
        for f in ("energy", "stress"):
            if f in body:
                d[f] = _level(body.get(f), f)
            else:
                d.setdefault(f, None)
        if "labels" in body or not old:
            d["labels"] = _vocab(body.get("labels"), LABELS)
        if "causes" in body or not old:
            d["causes"] = _vocab(body.get("causes"), CAUSES)
        if "note" in body or not old:
            d["note"] = str(body.get("note") or "").strip()[:NOTE_MAX]
        if "quote" in body or not old:
            d["quote"] = str(body.get("quote") or "").strip()[:QUOTE_MAX]
        if "date" in body and body.get("date") or not old:
            d["date"] = self._day(body.get("date")).isoformat()
            if old and d["date"] != old.get("date"):
                d["at"] = self._at(d["date"])
        if not old:
            source = str(body.get("source") or "webui").strip().lower()
            d["source"] = source if source in SOURCES else "webui"
            d["at"] = self._at(d["date"])
            d["created_at"] = now_iso()
        return d

    def _day(self, value: Any) -> date:
        if not value:
            return self.today()
        text = str(value).strip().lower()
        if text in ("oggi", "today"):
            return self.today()
        if text in ("ieri", "yesterday"):
            return self.today() - timedelta(days=1)
        try:
            d = date.fromisoformat(text[:10])
        except ValueError as exc:
            raise Invalid("date: usa AAAA-MM-GG, «oggi» o «ieri»") from exc
        if d > self.today():
            raise Invalid("date: non può essere nel futuro")
        return d

    def _at(self, day: str) -> str:
        now = self.now()
        if day == now.date().isoformat():
            return now.isoformat()
        return datetime.combine(date.fromisoformat(day), datetime.min.time().replace(hour=21), self.tz).isoformat()

    def _write(self, mid: str, d: dict) -> dict:
        self.store.upsert(KIND, mid, {k: v for k, v in d.items() if k != "id"}, ref_id=d["date"], at=d["at"])
        return self.view({**d, "id": mid})

    def log(self, body: dict) -> dict:
        d = self._clean(body)
        return self._write(new_id("m-"), d)

    def update(self, mid: str, body: dict) -> dict:
        old = self.find(mid)
        return self._write(old["id"], self._clean(body, old))

    def delete(self, mid: str) -> dict:
        row = self.find(mid)
        self.store.delete(KIND, row["id"])
        return {"deleted": True, "id": row["id"]}

    def capture(self, body: dict) -> dict:
        """Oracle's quiet capture from chat: merge into today's last chat capture when it is recent enough."""
        body = {**body, "source": "chat"}
        merge = int(self.get("psyche.capture.merge_minutes", 120) or 0)
        last = self._last_chat_capture()
        if last and merge > 0:
            age = self.now() - (parse_dt(last.get("updated_at") or last.get("at")) or self.now())
            if age <= timedelta(minutes=merge):
                quote = " · ".join(q for q in (last.get("quote"), str(body.get("quote") or "").strip()) if q)
                merged = {**body, "labels": list(dict.fromkeys((last.get("labels") or [])
                                                               + _vocab(body.get("labels"), LABELS))),
                          "causes": list(dict.fromkeys((last.get("causes") or [])
                                                       + _vocab(body.get("causes"), CAUSES))),
                          "quote": quote[-QUOTE_MAX:]}
                for f in ("energy", "stress"):
                    if merged.get(f) in (None, ""):
                        merged[f] = last.get(f)
                d = self._clean(merged, last)
                d["updated_at"] = now_iso()
                out = self._write(last["id"], d)
                logger.info("event=psyche_capture_merged id=%s mood=%s", last["id"], d["mood"])
                return {**out, "merged": True}
        d = self._clean(body)
        d["updated_at"] = now_iso()
        out = self._write(new_id("m-"), d)
        logger.info("event=psyche_capture_saved id=%s mood=%s labels=%s", out["id"], d["mood"], d["labels"])
        return {**out, "merged": False}

    def undo_capture(self) -> dict:
        last = self._last_chat_capture()
        if not last:
            return {"deleted": False}
        self.store.delete(KIND, last["id"])
        logger.info("event=psyche_capture_undone id=%s", last["id"])
        return {"deleted": True, "id": last["id"], "item": self.view(last)}

    def _last_chat_capture(self) -> dict | None:
        today = self.today().isoformat()
        rows = [r for r in self.entries() if r["date"] == today and r.get("source") == "chat"]
        return rows[-1] if rows else None

    # ── reading ─────────────────────────────────────────────────────────────
    def view(self, d: dict) -> dict:
        return {**d, "mood_word": mood_word(d.get("mood"))}

    def entries(self, start: date | None = None, end: date | None = None) -> list[dict]:
        """Check-ins oldest first (by day, then time)."""
        self.store.refresh()
        rows = [self.view(r) for r in self.store.items(KIND)]
        if start:
            rows = [r for r in rows if r.get("date", "") >= start.isoformat()]
        if end:
            rows = [r for r in rows if r.get("date", "") <= end.isoformat()]
        return sorted(rows, key=lambda r: (r.get("date", ""), str(r.get("at") or "")))

    def find(self, mid: str) -> dict:
        self.store.refresh()
        row = self.store.data(KIND, str(mid or "").strip())
        if not row:
            raise NotFound("Voce dell'umore non trovata.")
        return row

    @staticmethod
    def summary(rows: list[dict]) -> dict | None:
        """One day: the last check-in wins (it is how the day ended), plus min/max and every label."""
        if not rows:
            return None
        last = rows[-1]
        energies = [r["energy"] for r in rows if r.get("energy")]
        stresses = [r["stress"] for r in rows if r.get("stress")]
        return {"date": last["date"], "mood": last["mood"], "mood_word": mood_word(last["mood"]),
                "min": min(r["mood"] for r in rows), "max": max(r["mood"] for r in rows),
                "energy": energies[-1] if energies else None, "stress": stresses[-1] if stresses else None,
                "labels": list(dict.fromkeys(l for r in rows for l in r.get("labels") or [])),
                "causes": list(dict.fromkeys(c for r in rows for c in r.get("causes") or [])),
                "count": len(rows)}

    def days(self, n: int = 30, end: date | None = None) -> list[dict]:
        """Per-day summaries of the last ``n`` days (only days with check-ins), oldest first."""
        end = end or self.today()
        start = end - timedelta(days=max(1, int(n)) - 1)
        by_day: dict[str, list[dict]] = {}
        for r in self.entries(start, end):
            by_day.setdefault(r["date"], []).append(r)
        return [self.summary(v) for _, v in sorted(by_day.items())]

    def today_view(self) -> dict:
        rows = self.entries(self.today(), self.today())
        return {"date": self.today().isoformat(), "items": list(reversed(rows)), "summary": self.summary(rows)}

    def history(self, days: int = 30) -> dict:
        days = max(1, min(int(days or 30), 366))
        summaries = self.days(days)
        start = self.today() - timedelta(days=days - 1)
        return {"days": summaries, "items": list(reversed(self.entries(start))), "stats": self._stats(summaries),
                "from": start.isoformat(), "to": self.today().isoformat()}

    @staticmethod
    def _stats(summaries: list[dict]) -> dict:
        moods = [d["mood"] for d in summaries]
        energies = [d["energy"] for d in summaries if d.get("energy")]
        return {"days": len(summaries), "mood_avg": round(mean(moods), 2) if moods else None,
                "energy_avg": round(mean(energies), 2) if energies else None,
                "good_days": sum(m >= 4 for m in moods), "bad_days": sum(m <= 2 for m in moods)}

    # ── coaching (deterministic) ────────────────────────────────────────────
    def insights(self) -> dict:
        """Plain sentences about the last 30 days vs the 30 before; never causes, only what goes together."""
        min_days = int(self.get("psyche.insights.min_days", 7) or 7)
        today = self.today()
        recent = self.days(30)
        before = self.days(30, today - timedelta(days=30))
        stats, prev = self._stats(recent), self._stats(before)
        out: dict[str, Any] = {"stats": stats, "previous": prev, "sentences": [], "enough": len(recent) >= min_days,
                               "min_days": min_days}
        if len(recent) < min_days:
            missing = min_days - len(recent)
            out["sentences"].append(f"Servono ancora {missing} giorn{'o' if missing == 1 else 'i'} con l'umore segnato "
                                    "per vedere un andamento.")
            return out
        s = out["sentences"]
        s.append(f"Ultimi 30 giorni: umore medio {stats['mood_avg']:.1f} su 5 ({mood_word(stats['mood_avg'])}), "
                 f"{stats['good_days']} giorni buoni e {stats['bad_days']} giorni no.")
        if prev["mood_avg"] is not None and prev["days"] >= min_days:
            delta = stats["mood_avg"] - prev["mood_avg"]
            if abs(delta) >= 0.3:
                s.append(f"Rispetto al mese prima va {'meglio' if delta > 0 else 'peggio'} "
                         f"({prev['mood_avg']:.1f} → {stats['mood_avg']:.1f}).")
            else:
                s.append("Rispetto al mese prima è stabile.")
        if stats["energy_avg"] is not None:
            s.append(f"Energia media {stats['energy_avg']:.1f} su 5.")
        by_wd: dict[int, list[int]] = {}
        for d in self.days(90):
            by_wd.setdefault(date.fromisoformat(d["date"]).weekday(), []).append(d["mood"])
        wd = {k: mean(v) for k, v in by_wd.items() if len(v) >= 2}
        if len(wd) >= 3:
            best, worst = max(wd, key=wd.get), min(wd, key=wd.get)
            if wd[best] - wd[worst] >= 0.8:
                s.append(f"Il giorno che va meglio di solito è il {WEEKDAYS[best]}, quello più pesante il "
                         f"{WEEKDAYS[worst]}.")
                out["weekdays"] = {WEEKDAYS[k]: round(v, 2) for k, v in sorted(wd.items())}
        labels = Counter(l for d in recent for l in d["labels"])
        if labels:
            top = [f"{l} ({n})" for l, n in labels.most_common(3)]
            s.append("Le parole più frequenti: " + ", ".join(top) + ".")
        bad_causes = Counter(c for d in recent if d["mood"] <= 2 for c in d["causes"])
        if bad_causes:
            c, n = bad_causes.most_common(1)[0]
            if n >= 2:
                s.append(f"Nei giorni no torna spesso «{c}» ({n} volte).")
        good_causes = Counter(c for d in recent if d["mood"] >= 4 for c in d["causes"])
        if good_causes:
            c, n = good_causes.most_common(1)[0]
            if n >= 2:
                s.append(f"Nei giorni buoni c'è spesso «{c}» ({n} volte).")
        out["labels"] = dict(labels.most_common(8))
        return out

    def streak(self, test: Callable[[dict], bool], field_days: list[dict]) -> int:
        """Consecutive days ending today or yesterday whose summary passes ``test``."""
        by_date = {d["date"]: d for d in field_days}
        day = self.today()
        if day.isoformat() not in by_date:
            day -= timedelta(days=1)
        n = 0
        while day.isoformat() in by_date and test(by_date[day.isoformat()]):
            n += 1
            day -= timedelta(days=1)
        return n

    def signals(self) -> tuple[list[dict], list[dict]]:
        from hestia_common.signals_client import iso_week, last_weeks, metric, signal
        recent = self.days(28)
        sigs: list[dict] = []
        last7 = [d["mood"] for d in recent if d["date"] > (self.today() - timedelta(days=7)).isoformat()]
        prev21 = [d["mood"] for d in recent if d["date"] <= (self.today() - timedelta(days=7)).isoformat()]
        if len(last7) >= 3 and len(prev21) >= 5 and mean(prev21) - mean(last7) >= 1:
            sigs.append(signal("mood_drop", f"Umore in calo: media {mean(last7):.1f} negli ultimi 7 giorni contro "
                                            f"{mean(prev21):.1f} prima.", kind="trend", severity="attenzione",
                               metrics={"last7": round(mean(last7), 2), "before": round(mean(prev21), 2)},
                               page="umore"))
        low = self.streak(lambda d: d["mood"] <= 2, recent)
        if low >= 3:
            sigs.append(signal("low_streak", f"{low} giorni di fila con l'umore giù.", kind="streak",
                               severity="attenzione", metrics={"days": low}, page="umore", ttl_days=2))
        tired = self.streak(lambda d: bool(d.get("energy")) and d["energy"] <= 2, recent)
        if tired >= 3:
            sigs.append(signal("energy_low", f"{tired} giorni di fila con poca energia: una settimana più leggera "
                                             "potrebbe aiutare.", kind="streak", severity="attenzione",
                               metrics={"days": tired}, page="umore", ttl_days=2))
        good = self.streak(lambda d: d["mood"] >= 4, recent)
        if good >= 5:
            sigs.append(signal("good_streak", f"{good} giorni di fila di buon umore.", kind="milestone",
                               severity="info", metrics={"days": good}, page="umore", ttl_days=2))
        mets: list[dict] = []
        by_week: dict[str, list[dict]] = {}
        for d in self.days(12 * 7):
            by_week.setdefault(iso_week(date.fromisoformat(d["date"])), []).append(d)
        for week in last_weeks(12, self.today()):
            rows = by_week.get(week) or []
            if not rows:
                continue
            mets.append(metric("mood.avg", week, mean(r["mood"] for r in rows), "Umore medio"))
            energies = [r["energy"] for r in rows if r.get("energy")]
            if energies:
                mets.append(metric("mood.energy", week, mean(energies), "Energia media"))
        return sigs, mets

    def recap(self, day: date, nxt: date) -> dict:
        rows = self.entries(day, day)
        s = self.summary(rows)
        done = []
        if s:
            extra = ", ".join(s["labels"][:3])
            done.append({"text": f"Umore {s['mood']}/5 · {s['mood_word']}" + (f" · {extra}" if extra else ""),
                         "tone": "success" if s["mood"] >= 4 else "warning" if s["mood"] <= 2 else ""})
        recent = self.days(14, day)
        nxt_lines = []
        if self.streak(lambda d: bool(d.get("energy")) and d["energy"] <= 2, recent) >= 3:
            nxt_lines.append({"text": "Da qualche giorno hai poca energia: domani vai piano.", "tone": "info"})
        elif self.streak(lambda d: d["mood"] <= 2, recent) >= 3:
            nxt_lines.append({"text": "Qualche giorno pesante di fila: domani ritagliati qualcosa di bello.",
                              "tone": "info"})
        actions = [] if s else [{"label": "Come stai?", "command": "mood_log"}]
        return {"done": done, "next": nxt_lines, "actions": actions}

    def context_text(self, budget: int = 400) -> str:
        days = self.days(7)
        if not days:
            return "Umore: nessun dato negli ultimi 7 giorni."
        parts = [f"{d['date'][8:10]}/{d['date'][5:7]} {d['mood']}/5" + (f" ({', '.join(d['labels'][:2])})"
                                                                       if d["labels"] else "") for d in days]
        return ("Umore ultimi 7 giorni: " + "; ".join(parts))[:max(80, int(budget))]

    def checkin(self) -> dict | None:
        """Agenda job: the evening question, only when today has no check-in (the module decides, Hermes sends)."""
        if self.entries(self.today(), self.today()):
            return None
        base = "/api/mood"
        actions = [{"id": f"m{n}", "label": label, "text": label, "service": "psyche", "method": "POST",
                    "path": base, "body": {"mood": n, "source": "checkin"}, "resolves": True,
                    **({"style": "primary"} if n == 4 else {})}
                   for n, label in ((2, "Giù"), (3, "Così così"), (4, "Bene"))]
        return {"key": "psyche.checkin", "text": "Com'è andata oggi?", "actions": actions}
