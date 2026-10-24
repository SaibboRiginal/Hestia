"""Web Push for the WebUI's browsers (brainstorm C15, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

A browser subscribes (``POST /api/push/subscribe`` with the PushSubscription JSON); the subscription is a row of
Archive ``/api/hermes-store`` (kind ``push``). Every notification that rings on the WebUI is also pushed to every
subscribed browser; the WebUI service worker shows it only when no Hestia tab is focused. A gone subscription
(404/410) is deleted. Keys are infrastructure/secrets in env: ``HERMES_VAPID_PUBLIC_KEY``,
``HERMES_VAPID_PRIVATE_KEY``, ``HERMES_VAPID_SUBJECT`` (``mailto:``…); without them Web Push is simply off.
The payload is small (title, text, link, id): no secret form values ever travel here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("hestia_hermes.webpush")

CLIENT = "webui"
_STORE = "api/hermes-store/records"
_TAGS = re.compile(r"<[^>]+>")


def public_key() -> str:
    return os.getenv("HERMES_VAPID_PUBLIC_KEY", "").strip()


def configured() -> bool:
    return bool(public_key() and os.getenv("HERMES_VAPID_PRIVATE_KEY", "").strip())


def _sub_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:40]


def subscribe(archive, subscription: dict, device: str = "") -> dict:
    endpoint = str((subscription or {}).get("endpoint") or "")
    keys = (subscription or {}).get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("subscription needs endpoint (https), keys.p256dh and keys.auth")
    row = {"kind": "push", "id": _sub_id(endpoint), "data": {"endpoint": endpoint, "keys": keys,
                                                             "device": str(device)[:80]},
           "at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(),
           "deleted": False}
    archive._route_archive("PUT", _STORE, body={"rows": [row]})
    logger.info("event=webpush_subscribed id=%s", row["id"])
    return {"ok": True, "id": row["id"]}


def unsubscribe(archive, endpoint: str) -> dict:
    sid = _sub_id(str(endpoint or ""))
    archive._route_archive("PUT", _STORE, body={"rows": [{"kind": "push", "id": sid, "data": {},
                                                          "updated_at": datetime.now(timezone.utc).isoformat(),
                                                          "deleted": True}]})
    logger.info("event=webpush_unsubscribed id=%s", sid)
    return {"ok": True, "id": sid}


def subscriptions(archive) -> list[dict]:
    out = archive._route_archive("GET", _STORE, query={"kind": "push", "limit": 50})
    rows = (out or {}).get("rows") if isinstance(out, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and (r.get("data") or {}).get("endpoint")]


def payload_of(body: dict[str, Any]) -> dict[str, Any]:
    text = _TAGS.sub("", str(body.get("message") or ""))
    return {"id": body.get("notification_id"), "title": str(body.get("title") or "Hestia")[:120],
            "body": text[:300], "level": body.get("level") or "info", "link": body.get("link"),
            "pending": bool(body.get("actions") or body.get("secret"))}


def send_all(archive, body: dict[str, Any]) -> int:
    """Push one notification to every subscribed browser; returns how many accepted it."""
    if not configured():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ModuleNotFoundError:
        logger.warning("[🔄] event=webpush_unavailable reason=pywebpush_missing")
        return 0
    data = json.dumps(payload_of(body), ensure_ascii=False)
    claims = {"sub": os.getenv("HERMES_VAPID_SUBJECT", "").strip() or "mailto:owner@localhost"}
    sent = 0
    for row in subscriptions(archive):
        info = {"endpoint": row["data"]["endpoint"], "keys": row["data"].get("keys") or {}}
        try:
            webpush(subscription_info=info, data=data, vapid_private_key=os.getenv("HERMES_VAPID_PRIVATE_KEY"),
                    vapid_claims=dict(claims), ttl=3600)
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", 0)
            if code in (404, 410):
                unsubscribe(archive, info["endpoint"])
            else:
                logger.warning("[🔄] event=webpush_failed id=%s status=%s", row.get("id"), code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=webpush_failed id=%s error=%s", row.get("id"), str(exc)[:160])
    logger.info("event=webpush_sent notification_id=%s browsers=%d", body.get("notification_id"), sent)
    return sent
