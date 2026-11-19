"""Turn recurring errors — and recurring fallbacks — into Forge fix proposals.

Argus observes; Hephaestus/Forge executes.  When the same error signature from
one service shows up ``argus.forge.threshold`` times inside the
``argus.forge.window`` (central settings), Argus hands the fix to Forge (via Hub).  Forge's permission mode
(ask | auto | full_auto) decides whether it codes right away or waits for the user.  One proposal per signature per
cooldown, so the user is never spammed.

A recurring **fallback** counts too (dossier docs/work/2026-11-18-real-test-problems F): a ``[🔄]`` line (the code took its
recovery path) is a WARNING, but when it keeps coming the main path stopped working — usually something outside
changed (a provider's answer, an API, a model). Nothing is declared in advance: «it breaks? it gets fixed».

The task gets a ``title`` written for the owner (in his language, without module names or code; one short model call,
a plain sentence when the model does not answer) and an ``origin`` (what, where, how often, when, a redacted sample)
that the Development page shows as «Where it comes from».
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time

import requests

from core import argus_settings as cfg
from hestia_common.redact import redact

logger = logging.getLogger("hestia_argus.forge_proposer")

_LEVELS = {"ERROR", "CRITICAL"}
FALLBACK_MARK = "[🔄]"
_VOLATILE = re.compile(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b|\d+(\.\d+)?|'[^']*'|\"[^\"]*\"", re.IGNORECASE)

_hits: dict[str, list[float]] = {}
_proposed_at: dict[str, float] = {}
_samples: dict[str, str] = {}
_first_seen: dict[str, float] = {}
_kinds: dict[str, str] = {}
_lock = threading.Lock()


def signature(service: str, message: str) -> str:
    """Stable fingerprint: numbers, ids and quoted values stripped."""
    lines = [ln.strip() for ln in str(message or "").splitlines() if ln.strip()]
    # Prefer the exception line of a traceback (last line), else the first line.
    key_line = lines[-1] if any("Traceback" in ln for ln in lines) else (lines[0] if lines else "")
    norm = _VOLATILE.sub("#", key_line)[:300]
    return hashlib.sha1(f"{service}|{norm}".encode()).hexdigest()[:16]


def kind_of(level: str, message: str) -> str:
    """``error`` (ERROR/CRITICAL), ``fallback`` (a recovery path ``[🔄]`` at any level), else "" (not watched)."""
    if str(level).upper() in _LEVELS:
        return "error"
    return "fallback" if FALLBACK_MARK in str(message or "") else ""


def observe(service: str, level: str, message: str) -> str | None:
    """Record an error or fallback event.  Returns the signature when a proposal is due."""
    kind = kind_of(level, message)
    if not cfg.get_bool(cfg.FORGE_ENABLED) or not kind or service in {"hephaestus", "argus"}:
        return None
    sig = signature(service, message)
    now = time.time()
    window = cfg.get_int(cfg.FORGE_WINDOW, 1)
    threshold = cfg.get_int(cfg.FORGE_THRESHOLD, 1)
    cooldown = cfg.get_int(cfg.FORGE_COOLDOWN, 0)
    with _lock:
        hits = [t for t in _hits.get(sig, []) if now - t < window] + [now]
        _hits[sig] = hits
        _samples[sig] = str(message)[:3000]
        _kinds[sig] = kind
        if len(hits) == 1:
            _first_seen[sig] = now
        if len(hits) < threshold or now - _proposed_at.get(sig, 0) < cooldown:
            return None
        _proposed_at[sig] = now
    return sig


def _key_line(message: str) -> str:
    lines = [ln.strip() for ln in str(message or "").splitlines() if ln.strip()]
    return (lines[-1] if any("Traceback" in ln for ln in lines) else (lines[0] if lines else ""))[:400]


def title_for(service: str, kind: str, sample: str) -> str:
    """A short title for the owner, in his language: what keeps going wrong, in plain words. One model call (the
    model writes it from the redacted log line); a plain sentence when the model does not answer."""
    from hestia_common.areas import module_label
    from hestia_common.i18n import t as tr
    area = tr(module_label(service))
    from core import oracle_client
    prompt = ("Title for the owner of the assistant, max 12 words: what keeps going wrong. Plain words, no code, "
              "no module or file names, no quotes. "
              + ("It is a backup path used again and again: the normal way stopped working. " if kind == "fallback" else "")
              + f"Area: {area}. Log line: {_key_line(sample)}")
    try:
        text = oracle_client.analyze(prompt, voice=True)
    except Exception as exc:
        logger.warning("[🔄] event=argus_forge_title_failed service=%s error=%s", service, exc)
        text = ""
    text = " ".join(str(text or "").split()).strip(" \"'«»*#")
    if 6 <= len(text) <= 140:
        return text
    return tr("«{0}» keeps using its backup way", area) if kind == "fallback" else tr("Something keeps going wrong in «{0}»", area)


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else ""


def propose(hub_api_url: str, service: str, sig: str) -> bool:
    """Hand the fix to Forge. Runs off the monitor loop (one short model call for the title)."""
    from hestia_common.areas import module_label
    with _lock:
        sample = _samples.get(sig, "")
        hits = list(_hits.get(sig, []))
        kind = _kinds.get(sig, "error")
        first = _first_seen.get(sig, hits[0] if hits else 0.0)
    count = len(hits)
    minutes = cfg.get_int(cfg.FORGE_WINDOW, 1) // 60
    clean = redact(sample)
    if kind == "fallback":
        request = (f"A fallback path ([🔄]) keeps running in service '{service}' (seen {count}x in {minutes} min): the "
                   "main path stopped working, probably because something it depends on changed (a provider's answer, "
                   "an API, a model). Find why the main path broke, fix it so the fallback is the exception again, "
                   "add a regression test.")
    else:
        request = (f"Fix recurring error in service '{service}' (seen {count}x in {minutes} min). "
                   "Find root cause, fix, add regression test.")
    body = {
        "request": request,
        "title": title_for(service, kind, clean),
        "origin": {"kind": f"recurring_{kind}", "service": service, "area": module_label(service), "count": count,
                   "window_minutes": minutes, "first_seen": _iso(first), "last_seen": _iso(hits[-1] if hits else 0.0),
                   "line": _key_line(clean)[:300], "sample": clean[:1500], "signature": sig},
        "services": [service],
        "source": "argus",
        "requested_by": "argus.monitor",
        # No auto_start: Forge applies the user's permission mode.
        # Logs leave for a model (Forge engine): secrets and personal data out first (Cindy 19).
        "context": f"signature={sig}\nlog:\n{clean}",
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
