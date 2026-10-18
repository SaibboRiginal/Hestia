"""Health history + incidents — what the *Salute* page shows (SPEC 2026-10-18-moduli-core-e-mcp-esterno §A2).

In memory only (Argus owns no DB; Archive is the only DB owner): restarts start from an empty history.
- **History**: per service, one sample per minute (worst status seen in that minute), last 24 h.
- **Incidents**: a service that stops being "up" opens an incident; every step Argus takes (alert to Hermes,
  repair request to Hephaestus, recheck planned in the agenda, manual recheck) is appended as an action;
  recovery closes it. The last closed incidents are kept for the page.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger(f"hestia_argus.{__name__}")

MINUTES_KEPT = 24 * 60
CLOSED_KEPT = 50
ACTIONS_KEPT = 40
_RANK = {"up": 0, "degraded": 1, "down": 2}
_CODE = {0: "u", 1: "w", 2: "d"}      # strip codes: up · warning (degraded) · down; "-" = no data

_lock = threading.Lock()
_minutes: dict[str, deque] = {}                 # service → deque[[minute_epoch, rank]]
_last: dict[str, dict[str, Any]] = {}           # service → {status, error, checked_at}
_cycle: dict[str, Any] = {"at": None, "ms": None, "count": 0}
_open: dict[str, dict[str, Any]] = {}           # service → incident
_closed: deque = deque(maxlen=CLOSED_KEPT)
_seq = {"n": 0}


def reset() -> None:
    """Tests only."""
    with _lock:
        _minutes.clear(); _last.clear(); _open.clear(); _closed.clear()
        _cycle.update(at=None, ms=None, count=0)


# ── recording ───────────────────────────────────────────────────────────────

def record(service: str, status: str, error: str | None = None, at: float | None = None) -> None:
    """One health sample (monitor cycle or manual recheck)."""
    at = time.time() if at is None else at
    rank = _RANK.get(status, 2)
    minute = int(at // 60) * 60
    with _lock:
        ring = _minutes.setdefault(service, deque(maxlen=MINUTES_KEPT))
        if ring and ring[-1][0] == minute:
            ring[-1][1] = max(ring[-1][1], rank)
        else:
            ring.append([minute, rank])
        _last[service] = {"status": status, "error": error, "checked_at": at}


def record_cycle(health: dict[str, Any], ms: int | None = None, at: float | None = None) -> None:
    """All HealthReports of one monitor cycle."""
    at = time.time() if at is None else at
    for name, report in health.items():
        record(name, getattr(report, "status", "down"), getattr(report, "error", None), at)
    with _lock:
        _cycle.update(at=at, ms=ms, count=int(_cycle["count"]) + 1)


def note_unhealthy(service: str, status: str, error: str | None = None) -> bool:
    """Open an incident (True) or follow a status change of the open one (False)."""
    now = time.time()
    with _lock:
        inc = _open.get(service)
        if inc is None:
            _seq["n"] += 1
            _open[service] = {"id": f"{service}-{int(now)}-{_seq['n']}", "service": service, "status": status,
                              "error": error, "opened_at": now, "closed_at": None,
                              "actions": [{"at": now, "kind": "detected", "ok": None,
                                           "text": f"Rilevato: {status}" + (f" — {error}" if error else "")}]}
            opened = True
        else:
            if inc["status"] != status:
                inc["actions"].append({"at": now, "kind": "status", "ok": None, "text": f"Ora {status}"})
                del inc["actions"][:-ACTIONS_KEPT]
            inc["status"], inc["error"] = status, error
            opened = False
    if opened:
        logger.info("event=argus_incident_opened service=%s status=%s", service, status)
    return opened


def note_action(service: str, kind: str, text: str, ok: bool | None = None) -> None:
    """What Argus did about an open incident (ignored when nothing is open)."""
    with _lock:
        inc = _open.get(service)
        if inc is None:
            return
        inc["actions"].append({"at": time.time(), "kind": kind, "ok": ok, "text": text})
        del inc["actions"][:-ACTIONS_KEPT]


def note_recovered(service: str) -> None:
    now = time.time()
    with _lock:
        inc = _open.pop(service, None)
        if inc is None:
            return
        inc["actions"].append({"at": now, "kind": "recovered", "ok": True, "text": "Di nuovo online"})
        inc["closed_at"], inc["status"] = now, "up"
        _closed.appendleft(inc)
    logger.info("event=argus_incident_closed service=%s duration_s=%d", service, int(now - inc["opened_at"]))


# ── reading ─────────────────────────────────────────────────────────────────

def _copy(inc: dict) -> dict:
    out = dict(inc)
    out["actions"] = [dict(a) for a in inc["actions"]]
    out["duration_seconds"] = round((inc["closed_at"] or time.time()) - inc["opened_at"], 1)
    return out


def incidents(limit: int = 20) -> dict:
    limit = max(0, min(int(limit), CLOSED_KEPT))
    with _lock:
        open_ = sorted((_copy(i) for i in _open.values()), key=lambda i: i["opened_at"], reverse=True)
        recent = [_copy(i) for i in list(_closed)[:limit]]
    return {"open": open_, "recent": recent, "open_count": len(open_)}


def history(minutes: int = 360, buckets: int = 60, now: float | None = None) -> dict:
    """Per service: last status + a strip of ``buckets`` codes (worst status per bucket) over ``minutes``."""
    minutes = max(5, min(int(minutes), MINUTES_KEPT))
    buckets = max(1, min(int(buckets), minutes))
    now = time.time() if now is None else now
    start = now - minutes * 60
    width = minutes * 60 / buckets
    out: dict[str, dict] = {}
    with _lock:
        for name in sorted(set(_minutes) | set(_last)):
            worst = [-1] * buckets
            up = total = 0
            for minute, rank in _minutes.get(name, ()):
                if minute + 60 <= start:
                    continue
                i = min(buckets - 1, max(0, int((minute - start) // width)))
                worst[i] = max(worst[i], rank)
                total += 1
                up += rank == 0
            last = _last.get(name, {})
            out[name] = {"status": last.get("status"), "error": last.get("error"),
                         "checked_at": last.get("checked_at"),
                         "strip": "".join(_CODE.get(r, "-") for r in worst),
                         "uptime_pct": round(100 * up / total, 1) if total else None,
                         "incident_open": name in _open}
        cycle = dict(_cycle)
    return {"minutes": minutes, "buckets": buckets, "bucket_seconds": round(width, 1), "from": start, "to": now,
            "last_cycle_at": cycle["at"], "last_cycle_ms": cycle["ms"], "services": out}


def overview() -> dict:
    """Cheap snapshot from the last monitor cycle (widget *Stato sistema*, no network)."""
    with _lock:
        last = {k: dict(v) for k, v in _last.items()}
        cycle = dict(_cycle)
        open_count = len(_open)
    bad = sorted(n for n, v in last.items() if v.get("status") != "up")
    return {"last_cycle_at": cycle["at"], "last_cycle_ms": cycle["ms"], "cycles": cycle["count"],
            "total": len(last), "healthy": len(last) - len(bad), "unhealthy": len(bad),
            "unhealthy_services": [{"service": n, "status": last[n].get("status"), "error": last[n].get("error")}
                                   for n in bad],
            "open_incidents": open_count}


def recheck_targets() -> list[dict]:
    """Quick-action chips: one per service that is not up (open incident or last sample bad)."""
    with _lock:
        names = {n for n, v in _last.items() if v.get("status") != "up"} | set(_open)
        last = {n: dict(_last.get(n, {})) for n in names}
    return [{"id": n, "label": f"Ricontrolla {n}", "icon": "refresh", "state": "late",
             "hint": str(last[n].get("error") or last[n].get("status") or "")[:80]} for n in sorted(names)]
