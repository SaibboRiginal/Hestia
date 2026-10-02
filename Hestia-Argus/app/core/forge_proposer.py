"""Turn recurring errors into Forge fix proposals.

Argus observes; Hephaestus/Forge executes.  When the same error signature from
one service shows up ``ARGUS_FORGE_PROPOSE_THRESHOLD`` times inside the
window, Argus hands the fix to Forge (via Hub).  Forge's permission mode
(ask | auto | full_auto) decides whether it codes right away or waits for the user.  One proposal per signature per
cooldown, so the user is never spammed.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time

import requests

logger = logging.getLogger("hestia_argus.forge_proposer")

ENABLED = os.getenv("ARGUS_FORGE_PROPOSALS_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
THRESHOLD = max(1, int(os.getenv("ARGUS_FORGE_PROPOSE_THRESHOLD", "3")))
WINDOW_SECONDS = int(os.getenv("ARGUS_FORGE_PROPOSE_WINDOW_SECONDS", "3600"))
COOLDOWN_SECONDS = int(os.getenv("ARGUS_FORGE_PROPOSE_COOLDOWN_SECONDS", "86400"))
_LEVELS = {"ERROR", "CRITICAL"}
_VOLATILE = re.compile(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b|\d+(\.\d+)?|'[^']*'|\"[^\"]*\"", re.IGNORECASE)

_hits: dict[str, list[float]] = {}
_proposed_at: dict[str, float] = {}
_samples: dict[str, str] = {}
_lock = threading.Lock()


def signature(service: str, message: str) -> str:
    """Stable fingerprint: numbers, ids and quoted values stripped."""
    lines = [ln.strip() for ln in str(message or "").splitlines() if ln.strip()]
    # Prefer the exception line of a traceback (last line), else the first line.
    key_line = lines[-1] if any("Traceback" in ln for ln in lines) else (lines[0] if lines else "")
    norm = _VOLATILE.sub("#", key_line)[:300]
    return hashlib.sha1(f"{service}|{norm}".encode()).hexdigest()[:16]


def observe(service: str, level: str, message: str) -> str | None:
    """Record an error event.  Returns the signature when a proposal is due."""
    if not ENABLED or str(level).upper() not in _LEVELS or service in {"hephaestus", "argus"}:
        return None
    sig = signature(service, message)
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get(sig, []) if now - t < WINDOW_SECONDS] + [now]
        _hits[sig] = hits
        _samples[sig] = str(message)[:3000]
        if len(hits) < THRESHOLD or now - _proposed_at.get(sig, 0) < COOLDOWN_SECONDS:
            return None
        _proposed_at[sig] = now
    return sig


def propose(hub_api_url: str, service: str, sig: str) -> bool:
    with _lock:
        sample = _samples.get(sig, "")
        count = len(_hits.get(sig, []))
    body = {
        "request": (f"Fix recurring error in service '{service}' (seen {count}x in "
                    f"{WINDOW_SECONDS // 60} min). Find root cause, fix, add regression test."),
        "services": [service],
        "source": "argus",
        "requested_by": "argus.monitor",
        # No auto_start: Forge applies the user's permission mode.
        "context": f"signature={sig}\nlog:\n{sample}",
    }
    try:
        resp = requests.post(
            f"{hub_api_url.rstrip('/')}/route/hephaestus/api/hephaestus/forge/tasks",
            json={"method": "POST", "headers": {}, "query": {}, "body": body, "timeout_seconds": 10},
            timeout=12)
        status = int((resp.json() or {}).get("status_code", 500)) if resp.ok else resp.status_code
        ok = status < 400
    except Exception as exc:
        logger.warning("[🔄] event=argus_forge_proposal_failed service=%s sig=%s error=%s", service, sig, exc)
        ok = False
    if not ok:
        with _lock:
            _proposed_at.pop(sig, None)  # retry on next occurrence
    logger.info("event=argus_forge_proposal service=%s sig=%s ok=%s", service, sig, ok)
    return ok
