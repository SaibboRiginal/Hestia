"""Keeping audio and usage rows in Archive (dossier §7.4, §6).

Rule: **never throw away what cannot be made again; keep what can be made again only while it is useful.**

- Bytes: Archive blobs (owner ``echo``). Index: Archive ``/api/echo-store`` rows ``kind=audio`` (id = blob id,
  ``ref_id`` = message or notification id, ``parent_id`` = session id, ``data`` = class, use, text, size,
  duration, last listen).
- Classes: ``recording`` (Marko's voice: never deleted automatically), ``file`` (audio sent in chat: kept like a
  document), ``generated`` (replies: ``echo.audio.generated_days`` after the last listen), ``notification``
  (lives as long as its notification).
- Usage: rows ``kind=usage`` (one per operation) for the panel.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .hub import Hub

logger = logging.getLogger("hestia_echo.keep")

STORE = "api/echo-store/records"
CLASSES = ("recording", "file", "generated", "notification")
REGENERABLE = ("generated", "notification")


def now() -> datetime:
    return datetime.now(timezone.utc)


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode()).hexdigest()[:16]


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Keep:
    def __init__(self, hub: Hub, get: Callable[[str, Any], Any], notify: Callable[[dict], None] | None = None):
        self.hub = hub
        self.get = get
        self.notify = notify or (lambda event: None)

    # ── rows ─────────────────────────────────────────────────────────────────
    def _put(self, rows: list[dict]) -> None:
        self.hub.ok("archive", "PUT", STORE, body={"rows": rows}, timeout=15)

    def _rows(self, **query) -> list[dict]:
        data = self.hub.ok("archive", "GET", STORE, query={k: v for k, v in query.items() if v not in (None, "")},
                           timeout=15)
        return list((data or {}).get("rows") or [])

    # ── audio ────────────────────────────────────────────────────────────────
    def save(self, cls: str, data: bytes, mime: str, meta: dict) -> str:
        """Store bytes + index row; returns the blob id."""
        if cls not in CLASSES:
            cls = "generated"
        out = self.hub.ok("archive", "POST", "api/blobs", body={
            "owner_module": "echo", "content_type": mime, "data_base64": base64.b64encode(data).decode(),
            "meta": {"class": cls, **{k: v for k, v in meta.items() if k in ("use_case", "session_id")}}}, timeout=30)
        blob_id = str(out["blob_id"])
        stamp = now().isoformat()
        ref = str(meta.get("message_id") or meta.get("notification_id") or "")
        self._put([{"kind": "audio", "id": blob_id, "ref_id": ref or None,
                    "parent_id": str(meta.get("session_id") or "") or None, "at": stamp, "updated_at": stamp,
                    "data": {"class": cls, "mime": mime, "size": len(data), "last_played": stamp,
                             "text_hash": text_hash(meta.get("text") or "") if cls in REGENERABLE else "",
                             **{k: meta.get(k) for k in ("use_case", "client", "duration_s", "text", "voice",
                                                         "provider", "message_id", "notification_id", "session_id")
                                if meta.get(k) not in (None, "")}}}])
        logger.info("event=voice_audio_kept class=%s blob=%s bytes=%d", cls, blob_id, len(data))
        return blob_id

    def find(self, ref_id: str, *, cls: str = "", text: str = "") -> dict | None:
        """Kept audio of a message/notification (for generated audio: the one made from this exact text)."""
        if not ref_id:
            return None
        h = text_hash(text) if text else ""
        for row in reversed(self._rows(kind="audio", ref_id=ref_id)):
            d = row.get("data") or {}
            if cls and d.get("class") != cls:
                continue
            if h and d.get("class") in REGENERABLE and d.get("text_hash") != h:
                continue
            return row
        return None

    def read(self, blob_id: str) -> tuple[bytes, str]:
        out = self.hub.ok("archive", "GET", f"api/blobs/{blob_id}/base64", timeout=30)
        return base64.b64decode(out["data_b64"]), str(out.get("mime") or "audio/ogg")

    def touch(self, row: dict) -> None:
        stamp = now().isoformat()
        try:
            self._put([{**{k: row.get(k) for k in ("kind", "id", "ref_id", "parent_id", "at")}, "updated_at": stamp,
                        "data": {**(row.get("data") or {}), "last_played": stamp}}])
        except Exception as exc:
            logger.debug("event=voice_audio_touch_failed blob=%s error=%s", row.get("id"), exc)

    def delete(self, row: dict) -> None:
        try:
            self.hub.ok("archive", "DELETE", f"api/blobs/{row['id']}", timeout=15)
        except Exception as exc:
            logger.warning("[🔄] event=voice_blob_delete_failed blob=%s error=%s", row.get("id"), exc)
        self._put([{**{k: row.get(k) for k in ("kind", "id", "ref_id", "parent_id", "at")},
                    "data": row.get("data") or {}, "updated_at": now().isoformat(), "deleted": True}])

    def forget(self, *, notification_id: str = "", message_id: str = "") -> int:
        """Drop regenerable audio of a removed notification/message (recordings are never dropped here)."""
        ref = notification_id or message_id
        gone = 0
        for row in self._rows(kind="audio", ref_id=ref):
            if (row.get("data") or {}).get("class") in REGENERABLE:
                self.delete(row)
                gone += 1
        return gone

    def list(self, cls: str = "", limit: int = 200) -> list[dict]:
        rows = self._rows(kind="audio", order="-at", limit=5000)
        if cls:
            rows = [r for r in rows if (r.get("data") or {}).get("class") == cls]
        return rows[:limit]

    def space(self) -> dict:
        rows = self._rows(kind="audio", limit=20000)
        by: dict[str, dict] = {c: {"count": 0, "bytes": 0} for c in CLASSES}
        for r in rows:
            d = r.get("data") or {}
            c = by.setdefault(str(d.get("class") or "generated"), {"count": 0, "bytes": 0})
            c["count"] += 1
            c["bytes"] += int(d.get("size") or 0)
        total = sum(c["bytes"] for c in by.values())
        return {"classes": by, "total_bytes": total,
                "limit_bytes": int(float(self.get("echo.audio.space_mb", 2048) or 2048) * 1024 * 1024)}

    def cleanup(self) -> dict:
        """Daily agenda job: expired generated audio, then the space rule (oldest regenerable first)."""
        rows = self._rows(kind="audio", limit=20000)
        days = float(self.get("echo.audio.generated_days", 30) or 30)
        limit = int(float(self.get("echo.audio.space_mb", 2048) or 2048) * 1024 * 1024)
        cutoff = now() - timedelta(days=days)
        expired, kept = [], []
        for r in rows:
            d = r.get("data") or {}
            last = _dt(d.get("last_played")) or _dt(r.get("at")) or now()
            (expired if d.get("class") == "generated" and last < cutoff else kept).append(r)
        for r in expired:
            self.delete(r)
        total = sum(int((r.get("data") or {}).get("size") or 0) for r in kept)
        dropped_for_space = 0
        regen = sorted((r for r in kept if (r.get("data") or {}).get("class") in REGENERABLE),
                       key=lambda r: (r.get("data") or {}).get("last_played") or r.get("at") or "")
        for r in regen:
            if total <= limit:
                break
            total -= int((r.get("data") or {}).get("size") or 0)
            self.delete(r)
            dropped_for_space += 1
        warned = False
        if total > limit:
            # Only what cannot be made again is left: never dropped, Marko decides.
            warned = True
            self.notify({"title": "Spazio per gli audio", "text":
                         f"Le tue registrazioni occupano {total / 1048576:.0f} MB, più del limite di "
                         f"{limit / 1048576:.0f} MB. Non le cancello: alza il limite o scaricale e togli quelle che "
                         f"non ti servono."})
        out = {"expired": len(expired), "dropped_for_space": dropped_for_space, "total_bytes": total,
               "limit_bytes": limit, "warned": warned}
        logger.info("event=voice_audio_cleanup expired=%d dropped=%d total=%d limit=%d warned=%s", len(expired),
                    dropped_for_space, total, limit, warned)
        return out

    # ── usage ────────────────────────────────────────────────────────────────
    def usage_add(self, row: dict) -> None:
        stamp = now().isoformat()
        try:
            self._put([{"kind": "usage", "id": uuid.uuid4().hex, "at": stamp, "updated_at": stamp, "data": row}])
        except Exception as exc:
            logger.debug("event=voice_usage_write_failed error=%s", exc)

    def usage(self, days: int = 30) -> list[dict]:
        since = (now() - timedelta(days=max(1, days))).isoformat()
        return [{"at": r.get("at"), **(r.get("data") or {})}
                for r in self._rows(kind="usage", at_from=since, order="-at", limit=20000)]
