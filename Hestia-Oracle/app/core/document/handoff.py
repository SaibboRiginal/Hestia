"""Chat attachments a domain module knows how to take (e.g. a bank statement PDF → Spese).

Generic: Oracle knows no domain. A module declares in its Hub capabilities
``attachment_handlers: [{mime: [...], match: [...], min_hits, path, label}]``. When a file sent in chat has a matching
mime and its text (or the user's message) contains the module's words, Oracle stores the file in Archive blobs
(``owner_module=chat``) and hands the blob id to the module (``POST /route/<svc>/<path>``). The module answers
``{handled, text}``; that text is the chat reply and goes in the history, so the next turn («sì») reaches the module's
tools with the ids the reply carries. No match or any failure → the normal document analysis (nothing is lost).
SPEC docs/work/2026-10-19-email-push-spese §4 (P4).
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any

logger = logging.getLogger(f"hestia_oracle.{__name__}")

_CACHE_SECONDS = 60.0


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip().lower() for v in value or [] if str(v).strip()]


class AttachmentHandoff:
    def __init__(self, hub_client) -> None:
        self._hub = hub_client
        self._cache: list[dict] = []
        self._at = 0.0

    def handlers(self) -> list[dict]:
        if self._cache and time.time() - self._at < _CACHE_SECONDS:
            return self._cache
        data = self._hub.hub_get("registry/services", default={}) or {}
        out = []
        for svc in data.get("services", []) if isinstance(data, dict) else []:
            caps = svc.get("capabilities") if isinstance(svc.get("capabilities"), dict) else {}
            for h in caps.get("attachment_handlers") or []:
                if isinstance(h, dict) and h.get("path"):
                    out.append({"service": str(svc.get("name") or "").strip().lower(), "path": str(h["path"]),
                                "mime": _list(h.get("mime")), "match": _list(h.get("match")),
                                "min_hits": max(1, int(h.get("min_hits") or 2)), "label": str(h.get("label") or "")})
        self._cache, self._at = out, time.time()
        return out

    @staticmethod
    def matches(handler: dict, mime: str, text: str, message: str) -> bool:
        if handler["mime"] and mime not in handler["mime"]:
            return False
        words = handler["match"]
        if not words:
            return False
        msg, body = (message or "").lower(), (text or "")[:20000].lower()
        if any(w in msg for w in words):
            return True
        return sum(1 for w in words if w in body) >= handler["min_hits"]

    def pick(self, mime: str, text: str, message: str) -> dict | None:
        try:
            return next((h for h in self.handlers() if self.matches(h, mime, text, message)), None)
        except Exception as exc:
            logger.warning("[🔄] event=attachment_handlers_lookup_failed error=%s fallback=analysis", exc)
            return None

    def run(self, handler: dict, *, file_bytes: bytes, mime: str, filename: str | None, message: str,
            session_id: str) -> dict | None:
        """Store the file (blob owner chat), give its id to the module. None → caller falls back to analysis."""
        try:
            routed = self._hub.post("/blobs", {
                "owner_module": "chat", "content_type": mime, "data_base64": base64.b64encode(file_bytes).decode(),
                "meta": {"name": (filename or "")[:120], "session_id": session_id, "for": handler["service"]}},
                timeout=20) or {}
            blob_id = (routed.get("payload") or {}).get("blob_id")
        except Exception as exc:
            logger.warning("[🔄] event=attachment_blob_save_failed service=%s error=%s fallback=analysis",
                           handler["service"], exc)
            return None
        if not blob_id:
            return None
        ok, payload = self._hub.route_to_service(
            handler["service"], handler["path"], "POST", timeout=60,
            body={"blob_id": blob_id, "filename": filename, "mime": mime, "message": message,
                  "session_id": session_id})
        if not ok or not isinstance(payload, dict) or not payload.get("handled") or not payload.get("text"):
            logger.warning("[🔄] event=attachment_handoff_declined service=%s ok=%s fallback=analysis",
                           handler["service"], ok)
            return None
        logger.info("event=attachment_handoff_done service=%s blob=%s", handler["service"], blob_id)
        return {**payload, "blob_id": blob_id, "service": handler["service"]}
