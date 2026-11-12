"""What Hestia knows of "now" in an owner's chat turn (docs/work/2026-11-06-hestia-viva F3).

Up to four short background lines, read at turn time through Hub (each source owns its data):
- the owner's mood of today (Psyche ``GET /api/mood/today`` → ``summary``);
- the last notifications Hestia sent him today (Hermes ``GET /api/notifications``), and what she wrote him first
  today (kind ``athena.talk``), in full;
- the last things he opened or started (Metis ``GET /api/metis/usage/recent``).
Sources are read in parallel with a short timeout and cached ``CACHE_SECONDS``; a source that does not answer is
left out (``[🔄]`` log): the turn never waits on it or fails because of it. How many items: setting
``oracle.chat.consapevolezza_righe`` (0 = no lines).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(f"hestia_oracle.{__name__}")

CACHE_SECONDS = 60
TIMEOUT_SECONDS = 2
PREFIX = "[Contesto interno, non citarlo se non chiesto]"
TALK_KIND = "athena.talk"      # a message she wrote first (Hermes notification of Athena)

# (service, path, query) of each source; the hub routes them (Hub is the only door).
SOURCES = {
    "mood": ("psyche", "api/mood/today", {}),
    "notifications": ("hermes", "api/notifications", {"limit": 10}),
    "taps": ("metis", "api/metis/usage/recent", {"hours": 12}),
}

_cache: dict[str, Any] = {"at": 0.0, "items": -1, "lines": []}
_lock = threading.Lock()


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.getenv("TZ") or "Europe/Rome")
    except Exception:
        return ZoneInfo("Europe/Rome")


def _local(ts: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(_tz())


def mood_line(payload: Any) -> str:
    summary = (payload or {}).get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict) or not summary.get("mood_word"):
        return ""
    parts = [str(summary["mood_word"])]
    if summary.get("energy"):
        parts.append(f"energia {summary['energy']}/5")
    if summary.get("stress"):
        parts.append(f"stress {summary['stress']}/5")
    causes = [str(c) for c in (summary.get("causes") or [])][:3]
    if causes:
        parts.append("per " + ", ".join(causes))
    return "Umore di oggi dell'utente: " + ", ".join(parts) + "."


def notifications_line(payload: Any, limit: int, today: str | None = None) -> str:
    items = (payload or {}).get("items") if isinstance(payload, dict) else None
    today = today or datetime.now(_tz()).date().isoformat()
    out = []
    for row in items or []:
        at = _local(row.get("created_at")) if isinstance(row, dict) else None
        title = str((row or {}).get("title") or "").strip() if isinstance(row, dict) else ""
        if not at or not title or at.date().isoformat() != today or row.get("kind") == TALK_KIND:
            continue
        out.append(f"{at:%H:%M} «{title[:60]}»")
        if len(out) >= limit:
            break
    return ("Ultime notifiche che gli hai mandato oggi: " + "; ".join(out) + ".") if out else ""


def talk_line(payload: Any, today: str | None = None) -> str:
    """What she wrote him first today (Athena «parla con te», kind ``athena.talk``): the whole sentence, so his
    answer in any chat has its context (docs/work/2026-11-12-identita-e-proattivita)."""
    items = (payload or {}).get("items") if isinstance(payload, dict) else None
    today = today or datetime.now(_tz()).date().isoformat()
    out = []
    for row in items or []:
        if not isinstance(row, dict) or row.get("kind") != TALK_KIND:
            continue
        at = _local(row.get("created_at"))
        text = " ".join(str(row.get("message") or "").split())
        if not at or not text or at.date().isoformat() != today:
            continue
        out.append(f"{at:%H:%M} «{text[:240]}»")
        if len(out) >= 2:
            break
    return ("Oggi gli hai scritto tu per prima (se risponde, è a questo): " + "; ".join(out) + ".") if out else ""


def taps_line(payload: Any, limit: int) -> str:
    items = (payload or {}).get("items") if isinstance(payload, dict) else None
    out = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("label") or row.get("ref") or "").strip()
        at = _local(row.get("at"))
        if not name:
            continue
        where = {"webui": "sito", "telegram": "Telegram", "mcp": "un'altra AI"}.get(str(row.get("client")), "")
        out.append(f"{name[:40]}" + (f" ({where}" + (f", {at:%H:%M})" if at else ")") if where else ""))
        if len(out) >= limit:
            break
    return ("Ultime cose che ha aperto o avviato: " + "; ".join(out) + ".") if out else ""


def build_lines(fetch: Callable[[str, str, dict], Any], limit: int) -> list[str]:
    """The awareness lines from the three sources (``fetch(service, path, query)`` → payload or None)."""
    if limit <= 0:
        return []
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {name: pool.submit(fetch, *spec) for name, spec in SOURCES.items()}
        got = {}
        for name, future in futures.items():
            try:
                got[name] = future.result(timeout=TIMEOUT_SECONDS + 1)
            except Exception as exc:
                logger.info("[🔄] event=awareness_source_failed source=%s error=%s fallback=skip_line", name, exc)
                got[name] = None
    lines = [mood_line(got["mood"]), talk_line(got["notifications"]),
             notifications_line(got["notifications"], limit), taps_line(got["taps"], limit)]
    return [f"{PREFIX} {line}" for line in lines if line]


def lines_for_turn(hub, limit: int) -> list[str]:
    """Cached awareness lines for an owner's turn (empty when switched to 0 or nothing is known)."""
    now = time.monotonic()
    with _lock:
        if _cache["items"] == limit and now - _cache["at"] < CACHE_SECONDS:
            return list(_cache["lines"])

    def fetch(service: str, path: str, query: dict) -> Any:
        q = dict(query)
        if service == "metis":
            q["limit"] = max(1, limit)
        ok, payload = hub.route_to_service(service, path, "GET", query=q, timeout=TIMEOUT_SECONDS)
        if not ok:
            logger.info("[🔄] event=awareness_source_unavailable source=%s fallback=skip_line", service)
            return None
        return payload

    lines = build_lines(fetch, limit)
    with _lock:
        _cache.update(at=time.monotonic(), items=limit, lines=list(lines))
    return lines


def forget() -> None:
    """Drop the cache (a new notification or tap makes the next turn read again)."""
    with _lock:
        _cache.update(at=0.0, items=-1, lines=[])
