"""Chronos rows in Archive ``/api/chronos-store`` (routine results for the recap, «Lascia così» choices).

Best effort: a failed write logs ``[🔄]`` and the value stays in memory; the next start reloads what was written.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from core import archive_client

logger = logging.getLogger("hestia_chronos.life_store")
_PATH = "api/chronos-store/records"


def put(kind: str, row_id: str, data: dict, *, at: str | None = None, ref_id: str | None = None,
        background: bool = True) -> None:
    row = {"kind": kind, "id": str(row_id)[:120], "ref_id": ref_id, "at": at, "data": data,
           "updated_at": datetime.now(timezone.utc).isoformat(), "deleted": False}

    def _write() -> None:
        if archive_client._route_archive("PUT", _PATH, body={"rows": [row]}, timeout=8) is None:
            logger.warning("[🔄] event=chronos_store_write_failed kind=%s id=%s fallback=memory", kind, row_id)

    if background:
        threading.Thread(target=_write, daemon=True, name="chronos-store").start()
    else:
        _write()


def load(kind: str, *, at_from: str | None = None, limit: int = 200) -> list[dict]:
    query = {"kind": kind, "order": "at", "limit": limit}
    if at_from:
        query["at_from"] = at_from
    out = archive_client._route_archive("GET", _PATH, query=query, timeout=8)
    return [r for r in ((out or {}).get("rows") or []) if isinstance(r, dict)] if isinstance(out, dict) else []
