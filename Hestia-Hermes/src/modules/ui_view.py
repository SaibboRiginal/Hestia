"""Hermes inside view (WebUI plugin page «Consegne», widget «Consegne oggi»).

SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Read-only: what was sent to which client,
held / quiet / retracted / superseded, answers, subscriptions. The inbox stays the WebUI Notifiche page.
Data = the notification rows Hermes already keeps in Archive (``outbound_events``, channel ``notification``,
per-client ``deliveries`` in the payload) and the active subscriptions.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from .notifications import CHANNEL, CLOSED_STATES, LISTED_STATES

logger = logging.getLogger("hestia_hermes.ui")

ALL_STATES = sorted(set(LISTED_STATES) | set(CLOSED_STATES))
FLAGS = ("held", "quiet", "retracted", "failed", "answered", "superseded", "pending")
_TAG_RE = re.compile(r"<[^>]+>")


class ArchiveUnavailable(RuntimeError):
    pass


def _plain(text: Any, limit: int = 160) -> str:
    out = _TAG_RE.sub("", str(text or "")).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    out = " ".join(out.split())
    return out if len(out) <= limit else out[: limit - 1] + "…"


def delivery_view(row: dict[str, Any]) -> dict[str, Any]:
    """One notification as the Consegne page shows it (no event payload, message preview only)."""
    stored = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    n = stored.get("notification") if isinstance(stored.get("notification"), dict) else {}
    raw = stored.get("deliveries") if isinstance(stored.get("deliveries"), dict) else {}
    state = str(row.get("lifecycle_state") or "")
    clients = {}
    for name, d in sorted(raw.items()):
        d = d if isinstance(d, dict) else {}
        clients[name] = {"state": d.get("state") or "", "at": d.get("at"),
                         "attempts": int(d.get("attempts") or 1), "retracted": d.get("retracted"),
                         "detail": _plain(d.get("detail"), 200) if d.get("state") in ("failed", "dead") else None}
    answer = stored.get("answer") if isinstance(stored.get("answer"), dict) else None
    if answer and answer.get("outcome_text"):
        answer = {**answer, "outcome_text": _plain(answer["outcome_text"], 200)}
    origin = n.get("origin") if isinstance(n.get("origin"), dict) else None
    flags = {
        "held": n.get("held") or None,                       # presence level that held the push
        "held_released": stored.get("held_released"),
        "quiet": bool(n.get("quiet")),
        "retracted": any(c["retracted"] for c in clients.values()),
        "failed": any(c["state"] in ("failed", "dead") for c in clients.values()) or state in ("failed", "dead"),
        "answered": state == "answered" or bool(answer),
        "superseded": state == "superseded",
        "pending": bool(n.get("actions")) and state not in CLOSED_STATES,
    }
    repeat = n.get("repeat") if isinstance(n.get("repeat"), dict) else None
    return {
        "id": row.get("outbound_event_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "state": state,
        "title": n.get("title") or "",
        "preview": _plain(n.get("message")),
        "level": n.get("level") or "info",
        "source": n.get("source") or row.get("domain") or "",
        "event_type": row.get("event_type") or "",
        "audience": n.get("audience") or "global",
        "origin_client": (origin or {}).get("client"),
        "actions": [a.get("label") or a.get("id") for a in (n.get("actions") or []) if isinstance(a, dict)],
        "clients": clients,
        "answer": {k: answer.get(k) for k in ("by", "action_id", "label", "status", "outcome_text", "at")
                   if k in answer} if answer else None,
        "seen": stored.get("read"),
        "repeat": {"count": repeat.get("count"), "skipped": repeat.get("skipped")} if repeat else None,
        "flags": flags,
    }


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    per_client: dict[str, dict[str, int]] = {}
    for it in items:
        for name, c in it["clients"].items():
            bucket = per_client.setdefault(name, {"delivered": 0, "skipped": 0, "failed": 0})
            key = "failed" if c["state"] in ("failed", "dead") else c["state"]
            if key in bucket:
                bucket[key] += 1
    return {"total": len(items),
            **{f: sum(1 for it in items if it["flags"][f]) for f in FLAGS},
            "clients": per_client}


def _iso(value: str, name: str) -> str:
    if not value:
        return ""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO datetime")
    return value


def deliveries(archive, *, since: str = "", before: str = "", limit: int = 50, flag: str = "",
               client: str = "", source: str = "") -> dict[str, Any]:
    """Newest first. ``flag`` one of FLAGS; ``client`` keeps rows that client received (any state)."""
    if flag and flag not in FLAGS:
        raise ValueError(f"flag must be one of {', '.join(FLAGS)}")
    limit = max(1, min(int(limit), 200))
    query: dict[str, Any] = {"channel": CHANNEL, "order_by": "created", "lifecycle_states": ",".join(ALL_STATES),
                             "limit": limit if not (flag or client) else 200}
    if _iso(since, "since"):
        query["created_after"] = since
    if _iso(before, "before"):
        query["created_before"] = before
    if source:
        query["payload_source"] = source
    rows = archive._route_archive("GET", "api/outbound-events", query=query, timeout=8)
    if not isinstance(rows, list):
        raise ArchiveUnavailable("archive")
    items = [delivery_view(r) for r in rows if isinstance(r, dict)]
    if flag:
        items = [i for i in items if i["flags"][flag]]
    if client:
        items = [i for i in items if client in i["clients"]]
    items = items[:limit]
    return {"items": items, "summary": summarize(items),
            "next_before": items[-1]["created_at"] if len(items) == limit else None}


def subscriptions(archive) -> dict[str, Any]:
    rows = archive._route_archive("GET", "api/subscriptions/active", query={}, timeout=8)
    if not isinstance(rows, list):
        raise ArchiveUnavailable("archive")
    out = []
    for s in rows:
        if not isinstance(s, dict):
            continue
        channels = [{"type": c.get("type"), **({"client": c["client"]} if c.get("client") else {})}
                    for c in (s.get("channels") or []) if isinstance(c, dict)]
        out.append({"subscription_id": s.get("subscription_id"), "owner": s.get("owner"),
                    "domain": s.get("domain"), "event_type": s.get("event_type"),
                    "filters": s.get("filters") or {}, "channels": channels,
                    "updated_at": s.get("updated_at") or s.get("created_at")})
    return {"count": len(out), "subscriptions": out}
