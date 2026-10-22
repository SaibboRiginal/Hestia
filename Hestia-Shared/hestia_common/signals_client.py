"""Module signals — the first layer of Hestia's reflection (docs/work/2026-10-20-riflessione-a-livelli).

Each domain module judges ITS OWN data with deterministic rules and publishes short **signals** (a stall on
an exercise, routines skipped, a budget running fast) plus **weekly metrics** (one number per ISO week:
sessions, adherence %, spent…). Athena, the layer above, reads only these (never the raw data), links the
weekly series of different domains and asks a module for details through ``/api/module/context?topic=``.

Storage: Archive ``signals-store`` (generic module store: rows + cursor), through Hub. Row layout:

- signal: ``kind="signal"``, ``id="<module>:<key>"``, ``ref_id=<module>``, ``parent_id=<domain>``,
  ``data={key, kind, severity, text, metrics, period, page, topic, expires_at}``;
- metric: ``kind="metric"``, ``id="<module>:<name>:<YYYY-Www>"``, ``data={name, week, value, label}``;
- Athena's observations live in the same store with ``ref_id="athena"`` (kind ``observation``).

A module computes its whole current set and calls ``sync(signals, metrics)``: only what changed is written
(unchanged rows keep their cursor), signals no longer present are retracted (tombstones). ``changed()`` asks
for a debounced re-evaluation after a write (push, never poll); a daily agenda job (``signals_rule``) covers
time-based facts (missed days, things not used for weeks, the week that closes).

    from hestia_common.signals_client import Signals, signal, metric, signals_rule, iso_week

    signals = Signals("hercules", "fitness", evaluate=hercules.signals)   # evaluate() -> (signals, metrics)
    signals.changed()                       # after a write: re-evaluate in background, a few seconds later
    rules.append(signals_rule("hercules", "Allenamento", path="/api/fitness/signals/run", tz=TZ))

User-facing text never names modules: ``text`` speaks of the domain («Allenamento», «Spese»).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import requests

logger = logging.getLogger("hestia_common.signals")

STORE = "api/signals-store"
KINDS = ("trend", "streak", "anomaly", "goal", "milestone")
SEVERITIES = ("info", "attenzione", "alta")


def _hub_default() -> str:
    return os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def iso_week(day: date | datetime | None = None) -> str:
    """``YYYY-Www`` of ``day`` (today when omitted)."""
    d = day or date.today()
    if isinstance(d, datetime):
        d = d.date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(week: str) -> date:
    """Monday of an ``YYYY-Www`` week."""
    y, w = week.split("-W")
    return date.fromisocalendar(int(y), int(w), 1)


def last_weeks(n: int, today: date | None = None) -> list[str]:
    """The last ``n`` ISO weeks, oldest first, the current (still open) week last."""
    t = today or date.today()
    return [iso_week(t - timedelta(weeks=i)) for i in range(max(1, n) - 1, -1, -1)]


def signal(key: str, text: str, *, kind: str = "trend", severity: str = "info", metrics: dict | None = None,
           period: str | None = None, ttl_days: int = 7, page: str = "", topic: str = "") -> dict:
    """One signal. ``key`` is stable inside the module (republishing updates, never duplicates); ``text`` is one
    short Italian line; ``metrics`` the numbers behind it; ``page`` the module plugin page it belongs to;
    ``topic`` what to pass to ``/api/module/context?topic=`` for details (default: ``key``)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    return {"key": str(key)[:80], "kind": kind, "severity": severity, "text": str(text).strip()[:240],
            "metrics": {k: v for k, v in (metrics or {}).items() if isinstance(v, (int, float, str, bool))},
            "period": period or date.today().isoformat(), "ttl_days": max(1, int(ttl_days)), "page": page,
            "topic": topic or str(key)[:80]}


def metric(name: str, week: str, value: float, label: str = "") -> dict:
    """One weekly value of a series (``name`` like ``fitness.sessions``, ``label`` in Italian for clients)."""
    return {"name": str(name)[:80], "week": week, "value": round(float(value), 4), "label": label or name}


def signals_rule(module: str, area: str, *, path: str, tz: str | None = None, hour: int = 17,
                 minute: int = 30) -> dict:
    """The daily agenda job that re-evaluates a module's signals (time-based facts). Default 17:30, before
    Athena's reflection window; the user moves it in the agenda like any job."""
    from .agenda_client import job_rule
    return job_rule(f"{module}.signals", f"{area}: segnali per la riflessione", service=module, path=path,
                    recurrence="FREQ=DAILY", start_at=f"2026-01-01T{int(hour):02d}:{int(minute):02d}:00", tz=tz,
                    description="Rilegge i dati della giornata e aggiorna i segnali brevi e i numeri della "
                                "settimana che usa la riflessione serale.")


def _same(old: dict, new: dict, fields: Iterable[str]) -> bool:
    return all(old.get(f) == new.get(f) for f in fields)


class Signals:
    """Publisher bound to one module/domain. Every call fails soft (Archive or Hub down → logged, retried at
    the next evaluation)."""

    def __init__(self, module: str, domain: str, *, evaluate: Callable[[], tuple[list[dict], list[dict]]] | None = None,
                 hub_api_url: str | None = None, debounce_seconds: float = 5.0):
        self.module = module
        self.domain = domain
        self.hub = (hub_api_url or _hub_default()).rstrip("/")
        self._evaluate = evaluate
        self._debounce = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ── transport ────────────────────────────────────────────────────────
    def _call(self, method: str, path: str, *, body: Any = None, query: dict | None = None,
              timeout: float = 10) -> Any:
        resp = requests.post(
            f"{self.hub}/route/archive/{STORE}/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": {k: v for k, v in (query or {}).items() if v is not None},
                  "body": body, "timeout_seconds": timeout},
            timeout=timeout + 3)
        resp.raise_for_status()
        routed = resp.json() or {}
        status = int(routed.get("status_code", 500))
        if status >= 400:
            raise RuntimeError(f"signals-store status {status}")
        return routed.get("payload")

    def _own_rows(self) -> list[dict]:
        payload = self._call("GET", "records", query={"ref_id": self.module, "limit": 5000})
        return list((payload or {}).get("rows") or [])

    # ── publish ──────────────────────────────────────────────────────────
    def _signal_row(self, s: dict, now: datetime) -> dict:
        data = {k: s[k] for k in ("key", "kind", "severity", "text", "metrics", "period", "page", "topic")}
        data["module"], data["domain"] = self.module, self.domain
        data["expires_at"] = (now + timedelta(days=int(s.get("ttl_days") or 7))).isoformat()
        return {"kind": "signal", "id": f"{self.module}:{s['key']}", "ref_id": self.module,
                "parent_id": self.domain, "at": now.isoformat(), "data": data, "updated_at": now.isoformat()}

    def _metric_row(self, m: dict, now: datetime) -> dict:
        data = {**m, "module": self.module, "domain": self.domain}
        return {"kind": "metric", "id": f"{self.module}:{m['name']}:{m['week']}", "ref_id": self.module,
                "parent_id": self.domain, "at": datetime.combine(week_start(m["week"]), datetime.min.time(),
                                                                  tzinfo=timezone.utc).isoformat(),
                "data": data, "updated_at": now.isoformat()}

    def sync(self, signals: list[dict], metrics: list[dict] | None = None) -> dict:
        """Write the module's current set: new or changed rows, retract signals that are gone. A signal that
        is unchanged but close to expiry is refreshed (its TTL restarts)."""
        now = _now()
        try:
            existing = {(r["kind"], r["id"]): r for r in self._own_rows() if not r.get("deleted")}
        except Exception as exc:
            logger.warning("[🔄] event=signals_sync_read_failed module=%s error=%s fallback=next_run", self.module, exc)
            return {"written": 0, "retracted": 0, "error": str(exc)}
        rows, seen = [], set()
        for s in signals or []:
            row = self._signal_row(s, now)
            seen.add(("signal", row["id"]))
            old = existing.get(("signal", row["id"]))
            if old:
                od = old.get("data") or {}
                fresh = str(od.get("expires_at") or "") > (now + timedelta(days=1)).isoformat()
                if fresh and _same(od, row["data"], ("text", "severity", "kind", "metrics", "page")):
                    continue
            rows.append(row)
        for m in metrics or []:
            row = self._metric_row(m, now)
            old = existing.get(("metric", row["id"]))
            if old and (old.get("data") or {}).get("value") == row["data"]["value"]:
                continue
            rows.append(row)
        retracted = 0
        for (kind, rid), old in existing.items():
            if kind == "signal" and (kind, rid) not in seen:
                rows.append({**{k: old.get(k) for k in ("kind", "id", "ref_id", "parent_id", "at")},
                             "data": old.get("data") or {}, "updated_at": now.isoformat(), "deleted": True})
                retracted += 1
        if not rows:
            return {"written": 0, "retracted": 0}
        try:
            self._call("PUT", "records", body={"rows": rows})
        except Exception as exc:
            logger.warning("[🔄] event=signals_sync_write_failed module=%s rows=%d error=%s fallback=next_run",
                           self.module, len(rows), exc)
            return {"written": 0, "retracted": 0, "error": str(exc)}
        logger.info("event=signals_synced module=%s written=%d retracted=%d", self.module, len(rows) - retracted,
                    retracted)
        return {"written": len(rows) - retracted, "retracted": retracted}

    def run(self) -> dict:
        """Evaluate now (agenda job / startup) and sync."""
        if not self._evaluate:
            return {"written": 0, "retracted": 0, "error": "no evaluate"}
        try:
            sigs, mets = self._evaluate()
        except Exception as exc:
            logger.warning("[🔄] event=signals_evaluate_failed module=%s error=%s fallback=next_run", self.module, exc)
            return {"written": 0, "retracted": 0, "error": str(exc)}
        out = self.sync(sigs, mets)
        return {**out, "signals": len(sigs or []), "metrics": len(mets or [])}

    def changed(self) -> None:
        """Data changed: re-evaluate in background after a short debounce (many writes → one sync)."""
        if not self._evaluate:
            return
        with self._lock:
            if self._timer and self._timer.is_alive():
                return
            self._timer = threading.Timer(self._debounce, self.run)
            self._timer.daemon = True
            self._timer.start()


class SignalReader:
    """Read side (Athena, and any layer above the modules): active signals, weekly series, cursor."""

    def __init__(self, hub_api_url: str | None = None, timeout: float = 10):
        self.hub = (hub_api_url or _hub_default()).rstrip("/")
        self.timeout = timeout

    def _get(self, query: dict) -> dict:
        resp = requests.post(
            f"{self.hub}/route/archive/{STORE}/records",
            json={"method": "GET", "headers": {}, "query": {k: v for k, v in query.items() if v is not None},
                  "body": None, "timeout_seconds": self.timeout},
            timeout=self.timeout + 3)
        resp.raise_for_status()
        routed = resp.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            raise RuntimeError(f"signals-store status {routed.get('status_code')}")
        return routed.get("payload") or {}

    def signals(self, domain: str | None = None, include_expired: bool = False) -> list[dict]:
        rows = self._get({"kind": "signal", "parent_id": domain, "limit": 2000}).get("rows") or []
        now = _now().isoformat()
        out = [{**(r.get("data") or {}), "updated_at": r.get("updated_at"), "seq": r.get("seq")} for r in rows]
        if not include_expired:
            out = [s for s in out if str(s.get("expires_at") or "9") > now]
        order = {s: i for i, s in enumerate(reversed(SEVERITIES))}
        return sorted(out, key=lambda s: (order.get(s.get("severity"), 9), str(s.get("updated_at") or "")))

    def series(self, weeks: int = 26) -> dict[str, dict]:
        """``{name: {label, module, domain, values: {week: value}}}`` for the last ``weeks`` weeks."""
        start = week_start(last_weeks(weeks)[0])
        rows = self._get({"kind": "metric", "at_from": start.isoformat(), "limit": 20000}).get("rows") or []
        out: dict[str, dict] = {}
        for r in rows:
            d = r.get("data") or {}
            name = d.get("name")
            if not name:
                continue
            s = out.setdefault(name, {"label": d.get("label") or name, "module": d.get("module"),
                                      "domain": d.get("domain"), "values": {}})
            s["values"][d.get("week")] = d.get("value")
        return out

    def rows(self, kind: str, ref_id: str | None = None, at_from: str | None = None, limit: int = 500) -> list[dict]:
        return self._get({"kind": kind, "ref_id": ref_id, "at_from": at_from, "order": "-at",
                          "limit": limit}).get("rows") or []
