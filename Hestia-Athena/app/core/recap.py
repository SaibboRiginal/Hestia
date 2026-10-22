"""Daily recap — collect every module's piece, have Oracle write it, Hermes deliver it.

Dossier ``docs/work/2026-10-20-recap-giornaliero``. Independent from the thinking loop: the recap runs when its
agenda job fires (``athena.recap.evening`` by default, or a «Recap» template the user adds), when the user asks
in chat (tool ``recap_today``) or from the quick action.

- pieces: every Hub service with ``capabilities.recap_endpoint`` (Athena's own included, called through Hub
  like the others), in parallel, each within ``athena.recap.piece_timeout_seconds``; a failing one is skipped;
- text: Oracle ``/api/llm/generate`` use case ``athena.recap``; model unavailable → the same pieces as a plain
  list (the recap is never lost);
- nothing to say → no message (``event=recap_empty``); proposals for quiet days belong elsewhere;
- delivery: Hermes event, ``replaces: athena.recap`` (only the latest stays live), link to the «Recap» page;
- history: Archive, domain ``recap`` (one row per day and moment).
"""
from __future__ import annotations

import html
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests

from .athena_settings import RECAP_MAX_CHARS, RECAP_PIECE_TIMEOUT, RECAP_STYLE, get_float, get_int, settings

logger = logging.getLogger("hestia_athena")

USE_CASE = "athena.recap"
ARCHIVE_DOMAIN = "recap"
REPLACES_KEY = "athena.recap"
JOB_EVENING = "athena.recap.evening"
MOMENTS = ("sera", "mattina")
# Evening by default (Marko 2026-10-20): 21:30, free to move 20:00–23:30 around his own events (Chronos flex).
EVENING_AT = "21:30"
EVENING_FLEX = {"earliest": "20:00", "latest": "23:30"}

_WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_MONTHS = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_TAG = re.compile(r"</?(?!b>|/b>|i>|/i>)[a-zA-Z][^>]*>")


def day_label(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def moment_days(momento: str, day: date | None = None, *, today: date | None = None) -> tuple[date, date]:
    """``sera``: the day that ends (today) + tomorrow. ``mattina``: yesterday + today."""
    base = today or datetime.now().date()
    if momento == "mattina":
        d = day or base - timedelta(days=1)
    else:
        d = day or base
    return d, d + timedelta(days=1)


def has_content(pieces: list[dict]) -> bool:
    return any(p.get("done") or p.get("missed") or p.get("next") or p.get("note") for p in pieces)


def _lines(rows: list[dict] | None) -> list[str]:
    return [str(r.get("text") or "").strip() for r in rows or [] if str(r.get("text") or "").strip()]


def template_text(pieces: list[dict], momento: str, day: date, nxt: date) -> str:
    """Deterministic recap (Oracle unavailable): the pieces as a short HTML list, Telegram-safe."""
    head = "Com'è andata oggi" if momento == "sera" else f"Ieri, {day_label(day)}"
    out = [f"<b>{head}</b>"]
    upcoming: list[str] = []
    for p in pieces:
        title = html.escape(str(p.get("title") or ""))
        rows = [f"✓ {html.escape(t)}" for t in _lines(p.get("done"))]
        rows += [f"✗ {html.escape(t)}" for t in _lines(p.get("missed"))]
        if p.get("note"):
            rows.append(html.escape(str(p["note"])))
        if rows:
            out.append(f"{p.get('emoji') or '•'} <b>{title}</b>\n" + "\n".join(rows))
        nxt_rows = _lines(p.get("next"))
        if nxt_rows:
            upcoming.append(f"{title}: " + "; ".join(html.escape(t) for t in nxt_rows))
    if upcoming:
        label = "Domani" if momento == "sera" else "Oggi"
        out.append(f"<b>{label}, {day_label(nxt)}</b>\n" + "\n".join(f"• {u}" for u in upcoming))
    return "\n\n".join(out)


def build_prompt(pieces: list[dict], momento: str, day: date, nxt: date, style: str, max_chars: int) -> str:
    """Caveman prompt: facts as compact lines, rules short. Every token is paid each call."""
    facts: list[str] = []
    for p in pieces:
        title = str(p.get("title") or p.get("module") or "")
        for key, tag in (("done", "fatto"), ("missed", "saltato"), ("next", "prossimo")):
            for t in _lines(p.get(key)):
                facts.append(f"[{title}|{tag}] {t}")
        if p.get("note"):
            facts.append(f"[{title}|nota] {p['note']}")
    when = (f"oggi={day_label(day)} domani={day_label(nxt)}" if momento == "sera"
            else f"ieri={day_label(day)} oggi={day_label(nxt)}")
    tone = ("amichevole, caldo, una frase d'apertura breve" if style == "amichevole"
            else "asciutto, solo fatti, niente frasi di cortesia")
    return (
        f"Scrivi recap {'serale' if momento == 'sera' else 'del mattino'} per l'utente. Italiano. Tu = suo assistente.\n"
        f"{when}\n"
        f"Parti: 1) com'è andata ({'oggi' if momento == 'sera' else 'ieri'}): fatto/saltato per area; "
        f"2) {'domani' if momento == 'sera' else 'oggi'}: cosa c'è, in ordine di ora.\n"
        f"Tono: {tone}. Max {max_chars} caratteri. HTML Telegram: solo <b> per titoletti, niente markdown, "
        "un emoji al massimo per titoletto. Non inventare nulla oltre i fatti. Non nominare programmi o moduli. "
        "Niente domande finali.\n"
        "FATTI:\n" + "\n".join(facts)
    )


def clean_text(text: str, max_chars: int) -> str:
    """Model output → Telegram HTML within the cap (only <b>/<i> kept, markdown bold turned into <b>)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", str(text or "").strip())
    text = _TAG.sub("", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars].rsplit("\n", 1)[0].rstrip()
        text = cut if len(cut) > max_chars // 2 else text[:max_chars].rstrip() + "…"
    return text


class RecapComposer:
    """Collect → write → deliver → store. One recap at a time."""

    def __init__(self, hub_api_url: str, *, session: Any = None, now: Callable[[], datetime] | None = None):
        self.hub = hub_api_url.rstrip("/")
        self._http = session or requests.Session()
        self._now = now or datetime.now
        self._lock = threading.Lock()
        self._compose_lock = threading.Lock()
        self._recent: list[dict] = []

    # ── Hub helpers ───────────────────────────────────────────────────────────
    def _route(self, service: str, method: str, path: str, *, query: dict | None = None,
               body: dict | None = None, timeout: float = 8.0) -> tuple[int, Any]:
        resp = self._http.post(f"{self.hub}/route/{service}/{path.lstrip('/')}",
                               json={"method": method, "headers": {}, "query": query or {}, "body": body or {},
                                     "timeout_seconds": timeout}, timeout=timeout + 4)
        resp.raise_for_status()
        env = resp.json() if resp.content else {}
        return int((env or {}).get("status_code", 500)), (env or {}).get("payload")

    def sources(self) -> list[tuple[str, str]]:
        """``(service, path)`` of every registered service that declares ``recap_endpoint``."""
        resp = self._http.get(f"{self.hub}/registry/services", timeout=6)
        resp.raise_for_status()
        services = (resp.json() or {}).get("services") or []
        out: list[tuple[str, str]] = []
        for svc in services if isinstance(services, list) else []:
            name = str((svc or {}).get("name") or "").strip()
            path = str(((svc or {}).get("capabilities") or {}).get("recap_endpoint") or "").strip()
            if name and path and str((svc or {}).get("status") or "online").lower() != "offline":
                out.append((name, path))
        return sorted(set(out))

    # ── 1. collect ────────────────────────────────────────────────────────────
    def collect(self, day: date, nxt: date) -> list[dict]:
        try:
            sources = self.sources()
        except Exception as exc:
            logger.warning("[🔄] event=recap_discovery_failed error=%s fallback=no_pieces", exc)
            return []
        timeout = get_float(RECAP_PIECE_TIMEOUT)
        query = {"day": day.isoformat(), "next": nxt.isoformat()}

        def one(src: tuple[str, str]) -> dict | None:
            service, path = src
            try:
                status, payload = self._route(service, "GET", path, query=query, timeout=timeout)
            except Exception as exc:
                logger.warning("[🔄] event=recap_piece_failed module=%s error=%s fallback=skip", service, exc)
                return None
            if status >= 400 or not isinstance(payload, dict):
                logger.warning("[🔄] event=recap_piece_failed module=%s status=%s fallback=skip", service, status)
                return None
            if payload.get("empty"):
                return None
            return {**payload, "module": payload.get("module") or service}

        if not sources:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(sources))) as pool:
            pieces = [p for p in pool.map(one, sources) if p]
        pieces.sort(key=lambda p: (int(p.get("order") or 500), str(p.get("title") or "")))
        logger.info("event=recap_pieces_collected sources=%d pieces=%d", len(sources), len(pieces))
        return pieces

    # ── 2. write ──────────────────────────────────────────────────────────────
    def write(self, pieces: list[dict], momento: str, day: date, nxt: date) -> tuple[str, bool]:
        """→ (text, fallback_used)."""
        max_chars = get_int(RECAP_MAX_CHARS)
        style = str(settings.get(RECAP_STYLE) or "amichevole")
        prompt = build_prompt(pieces, momento, day, nxt, style, max_chars)
        try:
            status, payload = self._route("oracle", "POST", "api/llm/generate",
                                          body={"prompt": prompt, "use_case": USE_CASE}, timeout=90)
            text = ""
            if status < 400:
                text = str((payload or {}).get("response") or (payload or {}).get("text") or "") \
                    if isinstance(payload, dict) else str(payload or "")
            text = clean_text(text, max_chars)
            if text:
                return text, False
            logger.warning("[🔄] event=recap_fallback_template reason=oracle_status_%s", status)
        except Exception as exc:
            logger.warning("[🔄] event=recap_fallback_template reason=oracle_error error=%s", exc)
        return clean_text(template_text(pieces, momento, day, nxt), max(max_chars, 1500)), True

    # ── 3. deliver + store ────────────────────────────────────────────────────
    def deliver(self, text: str, momento: str, day: date) -> bool:
        title = "Recap della sera" if momento == "sera" else "Recap del mattino"
        event = {"event_type": "service.action_required", "domain": "system",
                 "entity_id": f"athena-recap-{day.isoformat()}-{momento}",
                 "payload": {"kind": "athena.recap", "service": "athena", "source": "athena", "domain": "recap",
                             "_source": "athena", "_title": title, "_message": text, "level": "info",
                             "target": "owner", "replaces": REPLACES_KEY, "emoji": "🌙" if momento == "sera" else "☀️",
                             "icon": "note", "tone": "info", "_actions": [],
                             "_link": {"module": "athena", "page": "recap"}}}
        try:
            status, payload = self._route("hermes", "POST", "api/events/ingest", body=event, timeout=10)
            if status >= 400:
                logger.warning("[🔄] event=recap_delivery_failed status=%s body=%s", status, str(payload)[:200])
                return False
            return True
        except Exception as exc:
            logger.warning("[🔄] event=recap_delivery_failed error=%s", exc)
            return False

    def store(self, record: dict) -> None:
        with self._lock:
            self._recent = [r for r in self._recent if r.get("id") != record["id"]]
            self._recent.insert(0, record)
            del self._recent[60:]
        try:
            self._route("archive", "POST", "api/entities",
                        body={"domain": ARCHIVE_DOMAIN, "entity_id": record["id"], "status": "active",
                              "payload": {"type": "athena_recap", "source": "athena", **record}}, timeout=6)
        except Exception as exc:
            logger.warning("[🔄] event=recap_archive_failed id=%s error=%s fallback=memory_only", record["id"], exc)

    def history(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit or 20), 100))
        try:
            status, rows = self._route("archive", "GET", "api/entities/records",
                                       query={"domain": ARCHIVE_DOMAIN, "limit": limit,
                                              "include_embedding": "false"}, timeout=6)
            if status < 400 and isinstance(rows, list):
                out = [r.get("payload") for r in rows if isinstance((r or {}).get("payload"), dict)]
                out = [{k: v for k, v in r.items() if k not in {"type", "source"}} for r in out]
                return sorted(out, key=lambda r: str(r.get("created_at") or ""), reverse=True)[:limit]
        except Exception as exc:
            logger.warning("[🔄] event=recap_history_failed error=%s fallback=memory", exc)
        with self._lock:
            return list(self._recent[:limit])

    # ── all together ──────────────────────────────────────────────────────────
    def compose(self, *, momento: str = "sera", day: str | None = None, deliver: bool = True,
                trigger: str = "manual") -> dict[str, Any]:
        momento = momento if momento in MOMENTS else "sera"
        today = self._now().date()
        d, n = moment_days(momento, date.fromisoformat(day) if day else None, today=today)
        with self._compose_lock:
            return self._compose(momento, d, n, deliver, trigger)

    def _compose(self, momento: str, d: date, n: date, deliver: bool, trigger: str) -> dict[str, Any]:
        pieces = self.collect(d, n)
        base = {"id": f"athena-recap-{d.isoformat()}-{momento}", "day": d.isoformat(), "next": n.isoformat(),
                "momento": momento, "trigger": trigger, "pieces": pieces,
                "created_at": datetime.now(timezone.utc).isoformat()}
        if not has_content(pieces):
            logger.info("event=recap_empty day=%s momento=%s trigger=%s", d, momento, trigger)
            return {**base, "status": "empty", "text": "", "delivered": False, "fallback": False}
        text, fallback = self.write(pieces, momento, d, n)
        delivered = self.deliver(text, momento, d) if deliver else False
        record = {**base, "status": "ok", "text": text, "delivered": delivered, "fallback": fallback}
        if deliver:   # a chat request is an answer, not a recap of the day: not stored, not delivered
            self.store(record)
        logger.info("event=recap_composed day=%s momento=%s pieces=%d chars=%d fallback=%s delivered=%s trigger=%s",
                    d, momento, len(pieces), len(text), fallback, delivered, trigger)
        return record
