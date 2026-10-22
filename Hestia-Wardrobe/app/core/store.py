"""Wardrobe data: an in-memory mirror of ``wardrobe_records`` kept in step with Archive by sync cursor.

Archive (``/api/wardrobe-store``, via Hub) is the only database; this mirror makes statistics and suggestions instant and
keeps reads working when Archive is briefly away (``[🔄]`` stale reads). Every write goes to Archive first.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from .hub import Hub, HubError

logger = logging.getLogger("hestia_wardrobe.store")

KINDS = ("piece", "outfit", "wear", "taxonomy", "collection", "reminder", "photo")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class StoreUnavailable(RuntimeError):
    pass


class Store:
    def __init__(self, hub: Hub, *, min_refresh_seconds: float = 2.0):
        self.hub = hub
        self.rows: dict[tuple[str, str], dict] = {}
        self.cursor = 0
        self.loaded = False
        self.epoch: str | None = None   # Archive data epoch (changes on a backup rollback)
        self.revision = 0              # bumps on every local change (statistics cache key)
        self._lock = threading.RLock()
        self._last_refresh = 0.0
        self._min_refresh = min_refresh_seconds

    # ── reading ─────────────────────────────────────────────────────────────
    def refresh(self, force: bool = False) -> bool:
        """Pull rows changed since the cursor. False when Archive is unreachable (mirror stays as is)."""
        with self._lock:
            if not force and self.loaded and time.monotonic() - self._last_refresh < self._min_refresh:
                return True
            try:
                query = {"since_seq": self.cursor, "limit": 20000} if self.loaded else {"include_deleted": "true",
                                                                                     "limit": 20000}
                while True:
                    data = self.hub.ok("archive", "GET", "api/wardrobe-store/records", query=query, timeout=15)
                    epoch = (data or {}).get("epoch")
                    if epoch and self.epoch and epoch != self.epoch:
                        # Archive's database was replaced (backup rollback): drop the mirror and reload it all.
                        logger.warning("[🔄] event=wardrobe_mirror_reset reason=data_epoch")
                        self.rows.clear()
                        self.cursor, self.loaded, self.epoch = 0, False, epoch
                        self.revision += 1
                        query = {"include_deleted": "true", "limit": 20000}
                        continue
                    self.epoch = epoch or self.epoch
                    rows = (data or {}).get("rows") or []
                    for r in rows:
                        self._put(r)
                    if rows:
                        self.cursor = max(self.cursor, max(int(r.get("seq") or 0) for r in rows))
                    if len(rows) < 20000:
                        break
                    query = {"since_seq": self.cursor, "limit": 20000}
                if not self.loaded:
                    logger.info("event=wardrobe_mirror_loaded rows=%d cursor=%d", len(self.rows), self.cursor)
                self.loaded = True
                self._last_refresh = time.monotonic()
                return True
            except Exception as exc:
                logger.warning("[🔄] event=wardrobe_mirror_refresh_failed error=%s fallback=stale_mirror", exc)
                return False

    def _put(self, r: dict) -> None:
        key = (r["kind"], r["id"])
        old = self.rows.get(key)
        if old and (parse_dt(old.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)) > \
                (parse_dt(r.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)):
            return
        self.rows[key] = r
        self.revision += 1

    def get(self, kind: str, id: str, *, deleted: bool = False) -> dict | None:
        row = self.rows.get((kind, id))
        if row is None or (row.get("deleted") and not deleted):
            return None
        return row

    def data(self, kind: str, id: str) -> dict | None:
        row = self.get(kind, id)
        return {**row["data"], "id": row["id"]} if row else None

    def all(self, kind: str, *, deleted: bool = False) -> list[dict]:
        return [r for (k, _), r in self.rows.items() if k == kind and (deleted or not r.get("deleted"))]

    def items(self, kind: str) -> list[dict]:
        """Live rows of a kind as plain dicts (data + id + at)."""
        return [{**r["data"], "id": r["id"]} for r in self.all(kind)]

    def changes_since(self, cursor: int) -> list[dict]:
        return sorted((r for r in self.rows.values() if int(r.get("seq") or 0) > cursor), key=lambda r: r["seq"])

    # ── writing ─────────────────────────────────────────────────────────────
    def write(self, rows: Iterable[dict]) -> dict:
        """Write rows ``{kind, id, parent_id?, ref_id?, at?, data, updated_at?, deleted?}`` to Archive and the
        mirror. Returns Archive's ``{applied, stale, cursor}``; raises StoreUnavailable when unreachable."""
        rows = [dict(r) for r in rows]
        if not rows:
            return {"applied": [], "stale": [], "cursor": self.cursor}
        for r in rows:
            r.setdefault("updated_at", now_iso())
            r.setdefault("data", {})
            r.setdefault("deleted", False)
            if isinstance(r.get("at"), datetime):
                r["at"] = r["at"].isoformat()
        try:
            out = {"applied": [], "stale": []}
            for i in range(0, len(rows), 2000):
                part = self.hub.ok("archive", "PUT", "api/wardrobe-store/records", body={"rows": rows[i:i + 2000]},
                                   timeout=20) or {}
                out["applied"] += part.get("applied") or []
                out["stale"] += part.get("stale") or []
                out["cursor"] = part.get("cursor", self.cursor)
        except (HubError, OSError, Exception) as exc:
            logger.warning("[🔄] event=wardrobe_write_failed rows=%d error=%s", len(rows), exc)
            raise StoreUnavailable(str(exc)) from exc
        seqs = {(a["kind"], a["id"]): a["seq"] for a in out["applied"]}
        with self._lock:
            for r in rows:
                seq = seqs.get((r["kind"], r["id"]))
                if seq is not None:
                    self._put({**r, "seq": seq})
            for s in out["stale"]:
                self._put(s)
        self.refresh(force=True)        # advance the cursor over our own writes (and anything in between)
        return out

    def upsert(self, kind: str, id: str, data: dict, *, parent_id: str | None = None, ref_id: str | None = None,
               at: Any = None, deleted: bool = False) -> dict:
        self.write([{"kind": kind, "id": id, "parent_id": parent_id, "ref_id": ref_id,
                     "at": at.isoformat() if isinstance(at, datetime) else at, "data": data, "deleted": deleted}])
        return {**data, "id": id}

    def delete(self, kind: str, id: str) -> bool:
        row = self.get(kind, id)
        if not row:
            return False
        self.write([{**{k: row.get(k) for k in ("kind", "id", "parent_id", "ref_id", "at", "data")}, "deleted": True}])
        return True
