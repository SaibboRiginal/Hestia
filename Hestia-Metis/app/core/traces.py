"""Training dataset, phase D1 «Registra» (docs/work/2026-10-30-dataset-allenamento).

Oracle pushes one **trace** per finished chat turn the owner typed (``POST /api/metis/traces``): system prompt, the
history text the model got, the user message, every tool call with arguments and result, the final answer, model
and route. Metis keeps them in Archive ``dataset-store`` (big rows: always read with filters, never mirrored):

- kind ``trace``   — id = trace_id, parent_id = session, at = turn time, data = the trace (tool schemas by ref);
- kind ``toolset`` — id = hash of the tool schemas offered, stored once (the same domain mix repeats a lot);
- kind ``signal``  — what the next turns tell about a trace, id ``<trace>:<type>``, ref_id = trace_id:
  ``rephrase`` (the owner asked again almost the same thing within minutes), ``correction`` (the next message
  starts with «no», «intendevo»…), ``tool_failed`` (a tool of the turn failed). Votes stay in Archive feedback
  (``interaction_id`` = trace_id); the review of phase D2 reads both.

A conversation marked «non usare per l'allenamento» (Archive chat meta ``training_off``) is never stored;
deleting a conversation or marking it drops its rows (tombstones with empty data). Rows older than
``metis.traces.keep_days`` are dropped by the agenda job that already prunes the usage log. Nothing leaves Hestia.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from hestia_common.module_kit import Invalid, now_iso, parse_dt

logger = logging.getLogger("hestia_metis.traces")

STORE = "api/dataset-store"
REPHRASE_SECONDS = 180          # a new message this soon and this similar = the previous answer missed
REPHRASE_RATIO = 0.6
_META_TTL = 60.0
_CORRECTION = re.compile(
    r"^\s*(no+\b|non (è|e'|era) (quello|così|cosi|giusto)|intendevo|ho detto|sbagliat|hai sbagliato|ma no\b|"
    r"non hai capito|non ti ho chiesto|veramente\b)", re.IGNORECASE)


def toolset_ref(tools: list[dict]) -> str:
    raw = json.dumps(sorted(tools or [], key=lambda t: str(t.get("name"))), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _similar(a: str, b: str) -> float:
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


class Traces:
    def __init__(self, hub, keep_days: Callable[[], int] = lambda: 365):
        self.hub = hub
        self.keep_days = keep_days
        self._lock = threading.Lock()
        self._toolsets: set[str] = set()
        self._last: dict[str, dict] = {}                 # session → {trace_id, user, at}
        self._meta: dict[str, tuple[float, bool]] = {}   # session → (checked at, training_off)

    # ── Archive ───────────────────────────────────────────────────────────
    def _write(self, rows: list[dict]) -> None:
        for r in rows:
            r.setdefault("updated_at", now_iso())
            r.setdefault("deleted", False)
            r.setdefault("data", {})
        self.hub.ok("archive", "PUT", f"{STORE}/records", body={"rows": rows}, timeout=20)

    def _rows(self, **query) -> list[dict]:
        out = self.hub.ok("archive", "GET", f"{STORE}/records", query=query, timeout=20) or {}
        return list(out.get("rows") or [])

    def _count(self, **query) -> int:
        out = self.hub.ok("archive", "GET", f"{STORE}/count", query=query, timeout=10) or {}
        return int(out.get("count") or 0)

    def excluded(self, session_id: str) -> bool:
        """«Non usare per l'allenamento». Archive unreachable → excluded (never store what may be private)."""
        now = time.monotonic()
        with self._lock:
            hit = self._meta.get(session_id)
        if hit and now - hit[0] < _META_TTL:
            return hit[1]
        try:
            meta = self.hub.ok("archive", "GET", f"api/chat/sessions/{session_id}/meta", timeout=6) or {}
            off = bool(meta.get("training_off"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=trace_meta_unknown session_id=%s error=%s fallback=skip_trace", session_id, exc)
            return True
        with self._lock:
            self._meta[session_id] = (now, off)
        return off

    # ── receive ───────────────────────────────────────────────────────────
    def receive(self, trace: dict) -> dict:
        tid = str(trace.get("trace_id") or "").strip()[:60]
        sid = str(trace.get("session_id") or "").strip()[:120]
        user, answer = str(trace.get("user") or "").strip(), str(trace.get("answer") or "").strip()
        if not tid or not sid or not user or not answer:
            raise Invalid("trace: trace_id, session_id, user, answer")
        if self.excluded(sid):
            logger.info("event=trace_skipped trace_id=%s reason=training_off", tid)
            return {"stored": False, "reason": "training_off"}
        at = parse_dt(trace.get("at")) or datetime.now(timezone.utc)
        tools = [t for t in (trace.get("tools") or []) if isinstance(t, dict) and t.get("name")]
        ref = toolset_ref(tools) if tools else ""
        data = {k: v for k, v in trace.items() if k != "tools"}
        data.update(toolset_ref=ref, tool_names=[str(t["name"]) for t in tools])
        rows: list[dict] = []
        if ref and ref not in self._toolsets:
            rows.append({"kind": "toolset", "id": ref, "at": at.isoformat(), "data": {"tools": tools}})
        rows.append({"kind": "trace", "id": tid, "parent_id": sid, "at": at.isoformat(), "data": data})
        signals = self._signals(tid, sid, user, at, trace.get("steps") or [])
        rows += signals
        self._write(rows)
        if ref:
            self._toolsets.add(ref)
        logger.info("event=trace_stored trace_id=%s route=%s steps=%d signals=%d", tid, trace.get("route"),
                    len(trace.get("steps") or []), len(signals))
        return {"stored": True, "trace_id": tid, "signals": [s["data"]["type"] for s in signals]}

    def _signals(self, tid: str, sid: str, user: str, at: datetime, steps: list) -> list[dict]:
        out: list[dict] = []

        def sig(target: str, kind: str, weight: float, **extra) -> None:
            out.append({"kind": "signal", "id": f"{target}:{kind}", "parent_id": sid, "ref_id": target,
                        "at": at.isoformat(), "data": {"type": kind, "source": "auto", "weight": weight,
                                                       "by_trace": tid, **extra}})

        with self._lock:
            prev = self._last.get(sid)
            self._last[sid] = {"trace_id": tid, "user": user, "at": at}
            if len(self._last) > 500:
                self._last.pop(next(iter(self._last)))
        if prev and 0 <= (at - prev["at"]).total_seconds() <= REPHRASE_SECONDS:
            ratio = _similar(user, prev["user"])
            if ratio >= REPHRASE_RATIO and user.strip().lower() != "sì":
                sig(prev["trace_id"], "rephrase", -0.5, similarity=round(ratio, 2))
        if prev and _CORRECTION.search(user):
            sig(prev["trace_id"], "correction", -0.7, text=user[:300])
        failed = [str(s.get("tool") or "") for s in steps if isinstance(s, dict) and not s.get("ok")]
        if failed:
            sig(tid, "tool_failed", -0.3, tools=failed[:10])
        return out

    # ── forget, prune, status ─────────────────────────────────────────────
    def _tombstone(self, rows: list[dict]) -> int:
        dead = [{"kind": r["kind"], "id": r["id"], "parent_id": r.get("parent_id"), "ref_id": r.get("ref_id"),
                 "at": r.get("at"), "data": {}, "deleted": True} for r in rows if not r.get("deleted")]
        for i in range(0, len(dead), 1000):
            self._write(dead[i:i + 1000])
        return len(dead)

    def forget_session(self, session_id: str) -> dict:
        sid = str(session_id or "").strip()
        if not sid:
            raise Invalid("session_id")
        with self._lock:
            self._last.pop(sid, None)
            self._meta.pop(sid, None)
        removed = 0
        while True:
            rows = self._rows(parent_id=sid, limit=1000)
            if not rows:
                break
            removed += self._tombstone(rows)
            if len(rows) < 1000:
                break
        logger.info("event=traces_forgotten session_id=%s rows=%d", sid, removed)
        return {"removed": removed}

    def prune(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(self.keep_days())))
        removed = 0
        for _ in range(20):
            old = self._rows(kind="trace,signal,review", at_to=cutoff.isoformat(), limit=1000)
            if not old:
                break
            removed += self._tombstone(old)
            if len(old) < 1000:
                break
        if removed:
            logger.info("event=traces_pruned rows=%d keep_days=%s", removed, self.keep_days())
        return removed

    def status(self) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        latest = self._rows(kind="trace", order="-at", limit=1)
        return {
            "traces": self._count(kind="trace"),
            "traces_7d": self._count(kind="trace", at_from=since),
            "signals": self._count(kind="signal"),
            "toolsets": self._count(kind="toolset"),
            "last_at": (latest[0].get("at") if latest else None),
            "keep_days": int(self.keep_days()),
        }

    def recent(self, limit: int = 20) -> list[dict]:
        """Newest traces, short (for the page and checks): no prompts, no tool results."""
        rows = self._rows(kind="trace", order="-at", limit=max(1, min(int(limit), 100)))
        out = []
        for r in rows:
            d = r.get("data") or {}
            out.append({"trace_id": r["id"], "session_id": r.get("parent_id"), "at": r.get("at"),
                        "route": d.get("route"), "model": d.get("model"), "client": d.get("client"),
                        "user": str(d.get("user") or "")[:120], "answer": str(d.get("answer") or "")[:160],
                        "tools": [s.get("tool") for s in d.get("steps") or []]})
        return out

