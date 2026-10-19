"""Iris mail dispatch — modules subscribe, Iris pushes matching mail to them (SPEC 2026-10-19-email-push-spese).

- Subscriptions live in Archive (``/api/iris-store``, kind ``subscription``, id ``<owner>:<key>``) so they survive
  restarts; a small in-memory copy serves matching and keeps working when Archive is briefly away.
- Hecate (the only mailbox watcher) posts new mail *headers* to ``incoming``. Matching is deterministic on headers
  (senders, subject words, labels); rules with Gmail ``queries`` are checked by asking Hecate.
- Delivery is durable: the full mail is shipped to Archive as a raw record under the subscriber's domain
  (``reference_id = mail:<domain>:<gmail id>``, deduplicated by Archive), then the subscriber is rung through Hub
  (``POST <path> {owner, key, domain, count, reference_ids}``). A module that is down finds its mails pending in
  Archive when it comes back.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Callable

logger = logging.getLogger("hestia_iris.dispatch")

MATCH_FIELDS = ("senders", "subject_contains", "labels", "queries")
DEFAULT_BACKFILL_DAYS = 7

HubCall = Callable[..., tuple[int, Any]]   # (service, method, path, *, body=None, query=None, timeout=...) → (status, payload)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in value if str(v).strip()]


def _queries(rule: dict) -> list[str]:
    """Gmail queries may contain commas: a list, or a string split on ``||``."""
    value = rule.get("queries") or []
    if isinstance(value, str):
        value = value.split("||")
    return [str(q).strip() for q in value if str(q).strip()]


def fingerprint(rule: dict) -> str:
    raw = json.dumps({f: sorted(_queries(rule) if f == "queries" else _list(rule.get(f))) for f in MATCH_FIELDS}
                     | {"domain": rule.get("domain")},
                     sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def sender_address(header_from: str) -> str:
    return (parseaddr(header_from or "")[1] or header_from or "").strip().lower()


def sender_matches(address: str, senders: list[str]) -> bool:
    address = address.lower()
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    for s in senders:
        s = s.lower().strip().strip('"')
        if "@" in s and not s.startswith("@"):
            if address == s:
                return True
        else:
            d = s.lstrip("@")
            if domain == d or domain.endswith("." + d):
                return True
    return False


def header_match(rule: dict, header: dict) -> bool | None:
    """True/False on the header groups the rule fills; None when the rule only has Gmail queries."""
    senders, words, labels = _list(rule.get("senders")), _list(rule.get("subject_contains")), _list(rule.get("labels"))
    if not (senders or words or labels):
        return None
    if senders and not sender_matches(sender_address(header.get("from", "")), senders):
        return False
    if words:
        subject = (header.get("subject") or "").lower()
        if not any(w.lower() in subject for w in words):
            return False
    if labels and not set(labels) & set(header.get("labels") or []):
        return False
    return True


def gmail_query(rule: dict) -> list[tuple[str, bool]]:
    """Gmail searches equivalent to the rule (for backfill): ``(query, check_headers)`` pairs. The header
    part is re-checked locally (Gmail's ``from:`` is fuzzier than the rule); the rule's own queries are not."""
    out = [(q, False) for q in _queries(rule)]
    parts = []
    senders = _list(rule.get("senders"))
    if senders:
        parts.append("from:(" + " OR ".join(s.lstrip("@") for s in senders) + ")")
    words = _list(rule.get("subject_contains"))
    if words:
        parts.append("subject:(" + " OR ".join(f'"{w}"' if " " in w else w for w in words) + ")")
    for label in _list(rule.get("labels")):
        parts.append(f"label:{label}")
    if parts:
        out.append((" ".join(parts), True))
    return out


class Dispatcher:
    def __init__(self, hub: HubCall):
        self.hub = hub
        self.subs: dict[str, dict] = {}
        self.loaded = False
        self.log: deque[dict] = deque(maxlen=200)
        self.stats: dict[str, Any] = {"incoming_batches": 0, "incoming_messages": 0, "unmatched": 0,
                                      "last_incoming_at": None, "last_source": None}
        self._lock = threading.RLock()

    # ── storage (Archive iris-store) ─────────────────────────────────────────
    def load(self, force: bool = False) -> bool:
        if self.loaded and not force:
            return True
        status, payload = self.hub("archive", "GET", "api/iris-store/records",
                                   query={"kind": "subscription", "limit": 5000}, timeout=10)
        if not status or status >= 400 or not isinstance(payload, dict):
            logger.warning("[🔄] event=iris_subscriptions_load_failed status=%s fallback=memory", status)
            return False
        with self._lock:
            self.subs = {r["id"]: {**(r.get("data") or {}), "id": r["id"]} for r in payload.get("rows") or []
                         if not r.get("deleted")}
            self.loaded = True
        logger.info("event=iris_subscriptions_loaded count=%d", len(self.subs))
        return True

    def _write(self, rows: list[dict]) -> bool:
        if not rows:
            return True
        now = _now().isoformat()
        body = {"rows": [{"kind": "subscription", "id": r["id"], "ref_id": r.get("owner"), "data": r.get("data", {}),
                          "updated_at": now, "deleted": bool(r.get("deleted"))} for r in rows]}
        status, _ = self.hub("archive", "PUT", "api/iris-store/records", body=body, timeout=10)
        if not status or status >= 400:
            logger.warning("[🔄] event=iris_subscriptions_write_failed status=%s rows=%d", status, len(rows))
            return False
        return True

    # ── subscriptions ────────────────────────────────────────────────────────
    def register(self, owner: str, rules: list[dict]) -> dict:
        """Full rule set of ``owner`` (idempotent). New or changed match rules → backfill."""
        self.load()
        owner = owner.strip()
        if not owner:
            raise ValueError("owner required")
        writes, backfill, keep = [], [], set()
        with self._lock:
            for rule in rules:
                key = str(rule.get("key") or "").strip()
                if not key or not rule.get("path") or not rule.get("domain"):
                    raise ValueError("each rule needs key, path and domain")
                sid = f"{owner}:{key}"
                keep.add(sid)
                current = self.subs.get(sid)
                fp = fingerprint(rule)
                data = {k: rule.get(k) for k in ("key", "title", "path", "domain", "description")}
                data.update({f: _queries(rule) if f == "queries" else _list(rule.get(f)) for f in MATCH_FIELDS})
                data.update(owner=owner, fingerprint=fp,
                            backfill_days=int(rule.get("backfill_days", DEFAULT_BACKFILL_DAYS)),
                            delivered_total=(current or {}).get("delivered_total", 0),
                            last_delivery_at=(current or {}).get("last_delivery_at"),
                            last_ring=(current or {}).get("last_ring"),
                            created_at=(current or {}).get("created_at") or _now().isoformat())
                if current and all(current.get(k) == v for k, v in data.items()):
                    continue
                if not current or current.get("fingerprint") != fp:
                    backfill.append(sid)
                self.subs[sid] = {**data, "id": sid}
                writes.append({"id": sid, "owner": owner, "data": data})
            for sid, sub in list(self.subs.items()):
                if sub.get("owner") == owner and sid not in keep:
                    writes.append({"id": sid, "owner": owner, "data": sub, "deleted": True})
                    self.subs.pop(sid)
        self._write(writes)
        if writes:
            logger.info("event=iris_subscriptions_registered owner=%s rules=%d changed=%d backfill=%d",
                        owner, len(rules), len(writes), len(backfill))
        for sid in backfill:
            threading.Thread(target=self.backfill, args=(sid,), daemon=True, name=f"iris-backfill-{sid}").start()
        return {"status": "ok", "owner": owner, "rules": len(rules), "changed": len(writes),
                "backfill": [s.split(":", 1)[1] for s in backfill]}

    def remove(self, owner: str, key: str) -> bool:
        self.load()
        sid = f"{owner}:{key}"
        with self._lock:
            sub = self.subs.pop(sid, None)
        if sub:
            self._write([{"id": sid, "owner": owner, "data": sub, "deleted": True}])
        return bool(sub)

    def list(self, owner: str | None = None) -> list[dict]:
        self.load()
        return sorted((s for s in self.subs.values() if not owner or s.get("owner") == owner),
                      key=lambda s: s["id"])

    # ── matching & delivery ──────────────────────────────────────────────────
    def _hecate_search(self, q: str, since: datetime, limit: int = 200) -> list[dict] | None:
        status, payload = self.hub("hecate", "GET", "api/gateway/email/messages",
                                   query={"q": q, "since": since.date().isoformat(), "limit": limit}, timeout=90)
        if not status or status >= 400 or not isinstance(payload, dict) or payload.get("status") == "error":
            logger.warning("[🔄] event=iris_hecate_search_failed q=%s status=%s", q, status)
            return None
        return payload.get("messages") or []

    def _full(self, gmail_id: str) -> dict | None:
        status, payload = self.hub("hecate", "GET", f"api/gateway/email/messages/{gmail_id}", timeout=30)
        if status and status < 400 and isinstance(payload, dict):
            return payload.get("message")
        logger.warning("[🔄] event=iris_message_fetch_failed id=%s status=%s", gmail_id, status)
        return None

    def incoming(self, messages: list[dict], source: str = "watch") -> dict:
        """New mail headers from Hecate → deliver to every matching subscription.
        Returns ``ok=False`` when a matched mail could not be stored (Hecate keeps its cursor and retries)."""
        self.load()
        headers = {m["id"]: m for m in messages if m.get("id")}
        self.stats.update(incoming_batches=self.stats["incoming_batches"] + 1,
                          incoming_messages=self.stats["incoming_messages"] + len(headers),
                          last_incoming_at=_now().isoformat(), last_source=source)
        matched_any: set[str] = set()
        ok, delivered = True, []
        for sub in self.list():
            ids = [mid for mid, h in headers.items() if header_match(sub, h)]
            queries = _queries(sub)
            if queries and headers:
                oldest = min((_parse(h.get("created_at")) for h in headers.values()), default=_now())
                for q in queries:
                    found = self._hecate_search(q, oldest - timedelta(days=1))
                    if found is None:
                        ok = False
                        continue
                    ids += [m["id"] for m in found if m.get("id") in headers and m["id"] not in ids]
            if not ids:
                continue
            matched_any.update(ids)
            result = self.deliver(sub, ids, source=source)
            ok = ok and result["stored"] == len(ids)
            delivered.append({"owner": sub["owner"], "key": sub["key"], "count": result["stored"]})
        unmatched = len(set(headers) - matched_any)
        self.stats["unmatched"] = self.stats["unmatched"] + unmatched
        if headers:
            logger.info("event=mail_incoming count=%d delivered=%d unmatched=%d source=%s", len(headers),
                        sum(d["count"] for d in delivered), unmatched, source)
        return {"status": "ok" if ok else "partial", "ok": ok, "received": len(headers), "delivered": delivered,
                "unmatched": unmatched}

    def deliver(self, sub: dict, gmail_ids: list[str], *, rows: dict[str, dict] | None = None,
                source: str = "watch") -> dict:
        """Store each mail under the subscriber's domain, then ring the subscriber once."""
        refs, subjects = [], []
        for gid in gmail_ids:
            msg = (rows or {}).get(gid) or self._full(gid)
            if not msg:
                continue
            ref = f"mail:{sub['domain']}:{gid}"
            record = {"reference_id": ref, "domain": sub["domain"], "source": "email",
                      "payload": {"reference_id": ref, "source": "email", "gmail_id": gid,
                                  "thread_id": msg.get("thread_id"), "message_id": msg.get("message_id"),
                                  "title": msg.get("subject") or "No Subject",
                                  "sender": msg.get("from") or "Unknown Sender",
                                  "to": msg.get("to"), "labels": msg.get("labels") or [],
                                  "body": msg.get("body") or msg.get("snippet") or "",
                                  "timestamp": msg.get("created_at"),
                                  "subscription": f"{sub['owner']}:{sub['key']}"}}
            status, _ = self.hub("archive", "POST", "api/archive", body=record, timeout=10)
            if status and status < 400:
                refs.append(ref)
                subjects.append((msg.get("subject") or "")[:80])
            else:
                logger.warning("[🔄] event=mail_store_failed owner=%s id=%s status=%s", sub["owner"], gid, status)
        ring_ok = None
        if refs:
            status, _ = self.hub(sub["owner"], "POST", sub["path"].lstrip("/"),
                                 body={"owner": sub["owner"], "key": sub["key"], "domain": sub["domain"],
                                       "count": len(refs), "reference_ids": refs, "source": source}, timeout=20)
            ring_ok = bool(status and status < 400)
            if ring_ok:
                logger.info("event=mail_dispatched owner=%s key=%s count=%d source=%s", sub["owner"], sub["key"],
                            len(refs), source)
            else:
                logger.warning("[🔄] event=mail_ring_failed owner=%s key=%s count=%d status=%s (mails wait in "
                               "Archive)", sub["owner"], sub["key"], len(refs), status)
            now = _now().isoformat()
            with self._lock:
                live = self.subs.get(sub["id"])
                if live is not None:
                    live.update(delivered_total=int(live.get("delivered_total") or 0) + len(refs),
                                last_delivery_at=now, last_ring="ok" if ring_ok else "failed")
                    data = {k: v for k, v in live.items() if k != "id"}
                    self._write([{"id": sub["id"], "owner": sub["owner"], "data": data}])
            self.log.appendleft({"at": now, "owner": sub["owner"], "key": sub["key"], "title": sub.get("title"),
                                 "count": len(refs), "subjects": subjects[:3], "ring_ok": ring_ok,
                                 "source": source})
        return {"stored": len(refs), "ring_ok": ring_ok}

    def backfill(self, sid: str, days: int | None = None) -> dict:
        """Deliver the matching mails of the last ``days`` (new subscription or "check now")."""
        self.load()
        sub = self.subs.get(sid)
        if not sub:
            return {"status": "error", "error": f"subscription '{sid}' not found"}
        days = int(days if days is not None else sub.get("backfill_days", DEFAULT_BACKFILL_DAYS))
        if days <= 0:
            return {"status": "ok", "found": 0, "stored": 0}
        since = _now() - timedelta(days=days)
        rows: dict[str, dict] = {}
        failed = False
        for q, check_headers in gmail_query(sub):
            found = self._hecate_search(q, since)
            if found is None:
                failed = True
                continue
            for m in found:
                if m.get("id") and (not check_headers or header_match(sub, m)):
                    rows[m["id"]] = m
        result = self.deliver(sub, list(rows), rows=rows, source="backfill") if rows else {"stored": 0}
        logger.info("event=mail_backfill owner=%s key=%s days=%d found=%d stored=%d", sub["owner"], sub["key"],
                    days, len(rows), result["stored"])
        return {"status": "error" if failed and not rows else "ok", "found": len(rows), "stored": result["stored"],
                "days": days}


def _parse(value: Any) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return _now()
