"""Web Push for the WebUI's browsers (brainstorm C15, dossier docs/work/2026-10-24-whole-cindy-brainstorm).

A browser subscribes (``POST /api/push/subscribe`` with the PushSubscription JSON); the subscription is a row of
Archive ``/api/hermes-store`` (kind ``push``). Every notification that rings on the WebUI is also pushed to every
subscribed browser; the WebUI service worker shows it only when no Hestia tab is focused. A gone subscription
(404/410) is deleted. The VAPID pair is made by Hermes itself at its first start (nothing for the owner to do,
dossier docs/work/2026-11-19-unified-connections) and saved like every key Hestia keeps: ``HERMES_KEY_VAPID_PUBLIC`` /
``HERMES_KEY_VAPID_PRIVATE`` in Hermes' .env, written by Hephaestus (``/api/setup/connection-secret``), so browsers stay
subscribed across restarts.
The payload is small (title, text, link, id): no secret form values ever travel here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("hestia_hermes.webpush")

CLIENT = "webui"
_STORE = "api/hermes-store/records"
_TAGS = re.compile(r"<[^>]+>")


PUBLIC_ENV = "HERMES_KEY_VAPID_PUBLIC"
PRIVATE_ENV = "HERMES_KEY_VAPID_PRIVATE"
SUBJECT = "mailto:owner@localhost"


def public_key() -> str:
    return os.getenv(PUBLIC_ENV, "").strip()


def private_key() -> str:
    return os.getenv(PRIVATE_ENV, "").strip()


def configured() -> bool:
    return bool(public_key() and private_key())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_pair() -> tuple[str, str]:
    """A new VAPID pair as the browsers want it: (public = uncompressed P-256 point, private = raw 32 bytes), base64url."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(public), _b64(key.private_numbers().private_value.to_bytes(32, "big"))


def ensure_keys(save, *, retry_seconds: float = 60, tries: int = 60) -> bool:
    """First start: make the pair, use it at once, and have it saved (``save({env: value})`` → True); retried in the
    background until saved, so a restart keeps the same pair. False when the keys were already there."""
    if configured():
        return False
    public, private = generate_pair()
    os.environ[PUBLIC_ENV], os.environ[PRIVATE_ENV] = public, private
    logger.info("event=webpush_keys_generated")

    def _save() -> None:
        for attempt in range(1, tries + 1):
            try:
                if save({PUBLIC_ENV: public, PRIVATE_ENV: private}):
                    logger.info("event=webpush_keys_saved attempt=%d", attempt)
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("[🔄] event=webpush_keys_unsaved attempt=%d error=%s", attempt, type(exc).__name__)
            time.sleep(retry_seconds)
        logger.warning("[🔄] event=webpush_keys_unsaved_gave_up tries=%d — kept in memory until the next start", tries)

    threading.Thread(target=_save, daemon=True, name="webpush-keys-save").start()
    return True


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


def _assistant() -> str:
    """The name the owner gave the assistant: a push with no title is signed with it (docs/work/2026-11-17-client-names)."""
    from hestia_common.i18n import identity_now
    return identity_now().get("assistant") or "Hestia"


def payload_of(body: dict[str, Any]) -> dict[str, Any]:
    text = _TAGS.sub("", str(body.get("message") or ""))
    return {"id": body.get("notification_id"), "title": str(body.get("title") or _assistant())[:120],
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
    claims = {"sub": SUBJECT}
    sent = 0
    for row in subscriptions(archive):
        info = {"endpoint": row["data"]["endpoint"], "keys": row["data"].get("keys") or {}}
        try:
            webpush(subscription_info=info, data=data, vapid_private_key=private_key(),
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
