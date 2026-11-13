"""First observe, then propose (docs/work/2026-11-13-prima-osserva-poi-propone).

An improvement to the code or a change of a setting is a judgement, and one sighting is not enough to make it: on
the first day Athena knows nothing about how the system normally behaves. So for ``improvement`` and ``setting``
candidates she keeps a ledger and proposes only when

1. she has been observing for at least ``athena.evidence.min_days`` days, and
2. the same thing came up on at least ``athena.evidence.seen_days`` different days within the last
   ``athena.evidence.window_days``.

Until then the candidate is kept as ``collecting`` (visible on the Pensieri page with what is missing). Faults
(``remediation``/``notification``) never wait, and «Pensa ora» (the owner asked) skips the wait.
The ledger lives in Archive ``signals-store`` (``kind=evidence``), so it survives restarts.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from . import athena_settings as S
from .athena_settings import get_int
from .reflection import local_day
from .shared_imports import import_shared_symbol

SignalReader = import_shared_symbol("hestia_common.signals_client", "SignalReader")

logger = logging.getLogger("hestia_athena.evidence")

STORE_KIND = "evidence"
START_KEY = "_start"
GATED_KINDS = ("improvement", "setting")
SAME_TITLE = 0.5            # share of common words for two improvement titles to be the same finding
_WORD = re.compile(r"[a-zà-ù0-9_]{4,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(str(text or "").lower()))


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _row_id(key: str) -> str:
    return "athena:evidence:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _short(day: str) -> str:
    try:
        d = date.fromisoformat(day)
        return f"{d.day}/{d.month}"
    except ValueError:
        return day


class Evidence:
    def __init__(self, hub_api_url: str) -> None:
        self.hub_api_url = hub_api_url.rstrip("/")
        self.reader = SignalReader(self.hub_api_url)
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._loaded = False
        self._rows: dict[str, dict] = {}      # key -> {key, kind, title, days, first_day, proposed_day}

    # ── ledger ───────────────────────────────────────────────────────────────
    def _load(self) -> None:
        if self._loaded:
            return
        try:
            rows = self.reader.rows(STORE_KIND, ref_id="athena", limit=1000)
        except Exception as exc:
            # Not loaded: nothing is proposed on a ledger we could not read (it would look like day one again).
            logger.warning("[🔄] event=evidence_read_failed error=%s fallback=retry_next_cycle", exc)
            raise
        for r in rows:
            data = r.get("data") or {}
            if not r.get("deleted") and data.get("key"):
                self._rows[str(data["key"])] = dict(data)
        self._loaded = True

    def _save(self, row: dict, now: datetime) -> None:
        at = now.isoformat()
        body = {"rows": [{"kind": STORE_KIND, "id": _row_id(row["key"]), "ref_id": "athena", "parent_id": "evidence",
                          "at": at, "data": row, "updated_at": at}]}
        try:
            resp = self._session.post(
                f"{self.hub_api_url}/route/archive/api/signals-store/records",
                json={"method": "PUT", "headers": {}, "query": {}, "body": body, "timeout_seconds": 10}, timeout=14)
            resp.raise_for_status()
        except Exception as exc:   # kept in memory until the next restart
            logger.warning("[🔄] event=evidence_store_failed key=%s error=%s fallback=memory_only", row["key"], exc)

    def start_day(self, now: datetime | None = None) -> str:
        """The first day she observed (written the first time it is asked)."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._load()
            row = self._rows.get(START_KEY)
            if not row:
                row = {"key": START_KEY, "first_day": local_day(now)}
                self._rows[START_KEY] = row
                self._save(row, now)
            return str(row["first_day"])

    def known_days(self, now: datetime | None = None) -> int:
        """Whole days since she started observing; 0 on the first day or when the ledger cannot be read."""
        now = now or datetime.now(timezone.utc)
        try:
            return max(0, (date.fromisoformat(local_day(now)) - date.fromisoformat(self.start_day(now))).days)
        except Exception:
            return 0

    # ── one candidate ────────────────────────────────────────────────────────
    def _key(self, candidate: Any) -> str:
        if candidate.kind == "setting":
            return f"setting:{str(candidate.setting_key or '').strip().lower()}"
        words = _words(candidate.title)
        best, best_score = "", 0.0
        for key, row in self._rows.items():
            if row.get("kind") != "improvement":
                continue
            score = _overlap(words, _words(row.get("title", "")))
            if score > best_score:
                best, best_score = key, score
        if best and best_score >= SAME_TITLE:
            return best
        return "improvement:" + " ".join(sorted(words))[:160]

    def weigh(self, candidate: Any, *, on_demand: bool = False, now: datetime | None = None) -> dict[str, Any]:
        """Note today's sighting and say whether there is enough to propose.
        ``{"ready": bool, "note": str, "seen_days": n, "need_days": n, "known_days": n, "need_known": n}``"""
        if candidate.kind not in GATED_KINDS:
            return {"ready": True, "note": ""}
        now = now or datetime.now(timezone.utc)
        today = local_day(now)
        need_days = max(1, get_int(S.EVIDENCE_SEEN_DAYS))
        need_known = max(0, get_int(S.EVIDENCE_MIN_DAYS))
        window = max(need_days, get_int(S.EVIDENCE_WINDOW_DAYS))
        try:
            known = (date.fromisoformat(today) - date.fromisoformat(self.start_day(now))).days
        except Exception:
            if on_demand:
                return {"ready": True, "note": "Chiesto da te: proposto senza attendere altre prove."}
            return {"ready": False, "note": "Registro delle prove non leggibile: riprovo al prossimo giro.",
                    "seen_days": 0, "need_days": need_days, "known_days": 0, "need_known": need_known}
        oldest = (date.fromisoformat(today) - timedelta(days=window - 1)).isoformat()
        with self._lock:
            key = self._key(candidate)
            row = self._rows.get(key) or {"key": key, "kind": candidate.kind, "title": str(candidate.title or "")[:160],
                                          "days": [], "first_day": today, "proposed_day": None}
            days = sorted({d for d in [*row.get("days", []), today] if d >= oldest})
            row["days"] = days
            out = {"seen_days": len(days), "need_days": need_days, "known_days": max(0, known),
                   "need_known": need_known, "first_day": days[0]}
            if on_demand:
                out.update(ready=True, note="Chiesto da te: proposto senza attendere altre prove "
                                            f"(visto in {len(days)} {_giorni(len(days))}).")
            elif known < need_known:
                out.update(ready=False, note=f"Sto ancora osservando: {max(0, known)} {_giorni(known)} su "
                                             f"{need_known} prima di proporre miglioramenti.")
            elif len(days) < need_days:
                out.update(ready=False, note=f"Raccolgo prove: visto in {len(days)} {_giorni(len(days))} su "
                                             f"{need_days} richiesti (dal {_short(days[0])}).")
            else:
                out.update(ready=True, note=f"Visto in {len(days)} giorni diversi dal {_short(days[0])}.")
            if out["ready"]:
                row["days"], row["proposed_day"] = [], today      # proposed: it must build up again from zero
            self._rows[key] = row
            self._save(row, now)
        logger.info("event=evidence_weighed key=%s ready=%s seen_days=%d need_days=%d known_days=%d on_demand=%s",
                    key[:60], out["ready"], out["seen_days"], need_days, out["known_days"], on_demand)
        return out

    def list(self) -> list[dict]:
        """What she is collecting (newest sighting first), for the Pensieri page."""
        try:
            with self._lock:
                self._load()
                rows = [dict(r) for k, r in self._rows.items() if k != START_KEY]
        except Exception:
            return []
        return sorted(rows, key=lambda r: (r.get("days") or [""])[-1], reverse=True)


def _giorni(n: int) -> str:
    return "giorno" if n == 1 else "giorni"
