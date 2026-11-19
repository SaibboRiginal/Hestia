"""Provider limits learned from the provider's own answers (dossier docs/work/2026-11-18-real-test-problems, E).

Nothing is declared or hardcoded: when a provider answers «limit reached» (429) and says which limit (Gemini
``QuotaFailure``: ``quotaId`` …RequestsPerMinute… / …RequestsPerDay… and ``quotaValue``), the limit is learned for that
provider/model. Every call is counted (``note_call``, from ``llm_usage.step``), so the next time the count reaches the
learned limit the step is skipped *before* the request (``ahead``) until its window resets: the chain goes on to the
next step without spending a failed call.

A learned limit is trusted for one day, then forgotten: if the provider changed it, the next 429 teaches the new one
(«it breaks? it gets fixed»). The reactive path stays exactly as before: any 429 still marks the pair exhausted until the
provider's hint (``llm_chains.mark_exhausted``).

The exhausted pairs and the learned limits are kept in Archive (``oracle-store``, kind ``llm_quota``) so a restart
neither forgets «no quota until 09:00» nor tries a spent model again. Counts are not stored: after a restart at most
one extra 429 per pair, which the reactive path handles.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("hestia_oracle.llm_limits")

STORE = "api/oracle-store/records"
KIND = "llm_quota"
TRUST_SECONDS = 24 * 3600        # a learned limit is re-learned after a day (providers change them)

_lock = threading.Lock()
_limits: dict[tuple[str, str], dict] = {}      # (provider, model) → {"minute": n, "day": n, "learned_at": epoch}
_minute: dict[tuple[str, str], deque] = {}     # call times of the last minute
_day: dict[tuple[str, str], list] = {}         # [day start epoch, calls since]
_loaded = False
_loading = False
_retry_at = 0.0                                 # Archive unreachable: next load attempt

# Gemini error details, as the SDK prints them: 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier',
# 'quotaValue': '250' (JSON or Python repr; any order of the other fields in between).
_VIOLATION = re.compile(r"quota_?id['\"]?\s*[:=]\s*['\"]([A-Za-z0-9_-]+)['\"].{0,600}?quota_?value['\"]?\s*[:=]\s*['\"]?(\d+)",
                        re.IGNORECASE | re.DOTALL)


def _midnight_pacific(now: float) -> float:
    """Start of the next day where Google counts daily quotas (midnight Pacific)."""
    try:
        from zoneinfo import ZoneInfo
        local = datetime.fromtimestamp(now, ZoneInfo("America/Los_Angeles"))
        return (local + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0).timestamp()
    except Exception:
        return now + 3600


def _day_start(now: float) -> float:
    return _midnight_pacific(now) - 86400


def parse(text: str) -> dict[str, int]:
    """Request limits named in a provider error: ``{"minute": 10, "day": 250}`` (only those it names)."""
    out: dict[str, int] = {}
    for quota_id, value in _VIOLATION.findall(text or ""):
        low = quota_id.lower()
        if "request" not in low:      # token limits: the reactive path handles them
            continue
        window = "minute" if "perminute" in low else "day" if "perday" in low else ""
        if window:
            out[window] = min(int(value), out.get(window, int(value)))
    return out


# ── counting ─────────────────────────────────────────────────────────────────

def note_call(provider: str, model: str, now: float | None = None) -> None:
    """One request to *provider*/*model* is starting."""
    now = time.time() if now is None else now
    key = (provider, model)
    with _lock:
        q = _minute.setdefault(key, deque())
        q.append(now)
        while q and q[0] <= now - 60:
            q.popleft()
        day = _day.setdefault(key, [_day_start(now), 0])
        if now >= day[0] + 86400:
            day[0], day[1] = _day_start(now), 0
        day[1] += 1


def ahead(provider: str, model: str, now: float | None = None) -> float:
    """When the pair can be used again if a learned limit is already reached in its window (0 = usable)."""
    _ensure_loaded()
    now = time.time() if now is None else now
    key = (provider, model)
    with _lock:
        lim = _limits.get(key)
        if not lim:
            return 0.0
        if now - float(lim.get("learned_at") or 0) > TRUST_SECONDS:
            _limits.pop(key, None)
            return 0.0
        day = _day.get(key)
        if lim.get("day") and day and now < day[0] + 86400 and day[1] >= int(lim["day"]):
            return day[0] + 86400
        q = _minute.get(key)
        if lim.get("minute") and q:
            recent = [t for t in q if t > now - 60]
            if len(recent) >= int(lim["minute"]):
                return recent[0] + 60
    return 0.0


def learn(provider: str, model: str, text: str, now: float | None = None) -> dict[str, int]:
    """Learn the request limits a 429 names; the count of that window is set to the limit (it is reached now)."""
    found = parse(text)
    if not found:
        return {}
    now = time.time() if now is None else now
    key = (provider, model)
    with _lock:
        prev = _limits.get(key) or {}
        _limits[key] = {**{k: v for k, v in prev.items() if k in ("minute", "day")}, **found, "learned_at": now}
        if "day" in found:
            _day[key] = [_day_start(now), max(found["day"], (_day.get(key) or [0, 0])[1])]
    logger.info("event=llm_limit_learned provider=%s model=%s limits=%s", provider, model, found)
    save(provider, model)
    return found


def learned(provider: str, model: str) -> dict:
    """What is known about the pair (WebUI): learned limits and calls counted in their windows."""
    key = (provider, model)
    now = time.time()
    with _lock:
        lim = dict(_limits.get(key) or {})
        day = _day.get(key) or [0, 0]
        q = _minute.get(key) or deque()
        if not lim:
            return {}
        return {"minute": lim.get("minute"), "day": lim.get("day"),
                "used_minute": sum(1 for t in q if t > now - 60),
                "used_day": day[1] if now < day[0] + 86400 else 0}


def forget(provider: str = "", model: str = "") -> None:
    """Drop learned limits and counts (all, or one provider / pair: «Try again now»)."""
    with _lock:
        for store in (_limits, _minute, _day):
            for key in [k for k in store if not provider or (k[0] == provider and (not model or k[1] == model))]:
                del store[key]


# ── persistence (Archive oracle-store) ───────────────────────────────────────

def _hub():
    from core.services.hub_client import HubClient
    return HubClient(os.getenv("HUB_API_URL", "http://hestia_hub:19001/api"))


def _send(rows: list[dict]) -> None:
    ok, res = _hub().route_to_service("archive", STORE, "PUT", body={"rows": rows}, timeout=6)
    if not ok:
        raise RuntimeError(str(res)[:160])


def save(provider: str, model: str) -> None:
    """Store the pair's state (exhausted until, learned limits) in the background."""
    from core.services import llm_chains
    with _lock:
        lim = dict(_limits.get((provider, model)) or {})
    until = llm_chains.exhausted_raw(provider, model)
    row = {"kind": KIND, "id": f"{provider}|{model}"[:120], "data": {"provider": provider, "model": model,
           "exhausted_until": until, "limits": lim},
           "updated_at": datetime.now(timezone.utc).isoformat(), "deleted": not lim and not until}

    def run():
        try:
            _send([row])
        except Exception as exc:
            logger.warning("[🔄] event=llm_quota_store_failed provider=%s model=%s error=%s", provider, model,
                           str(exc)[:160])
    threading.Thread(target=run, name="llm-quota-save", daemon=True).start()


def _load() -> None:
    global _loaded, _loading
    from core.services import llm_chains
    try:
        ok, res = _hub().route_to_service("archive", STORE, "GET", query={"kind": KIND}, timeout=6)
        rows = (res or {}).get("rows") if ok and isinstance(res, dict) else None
        if rows is None:
            raise RuntimeError(str(res)[:160])
        now = time.time()
        for r in rows:
            d = r.get("data") or {}
            if r.get("deleted") or not d.get("provider"):
                continue
            key = (str(d["provider"]), str(d.get("model") or ""))
            until = float(d.get("exhausted_until") or 0)
            if until > now:
                llm_chains.restore_exhausted(key[0], key[1], until)
            lim = d.get("limits") or {}
            if lim and now - float(lim.get("learned_at") or 0) <= TRUST_SECONDS:
                with _lock:
                    _limits.setdefault(key, lim)
        _loaded = True
        logger.info("event=llm_quota_loaded rows=%d", len(rows))
    except Exception as exc:
        global _retry_at
        _retry_at = time.time() + 60
        logger.warning("[🔄] event=llm_quota_load_failed error=%s retry_in_s=60", str(exc)[:160])
    finally:
        _loading = False


def _ensure_loaded() -> None:
    """First use loads the stored state in the background (a call never waits for Archive)."""
    global _loading
    if _loaded or _loading or time.time() < _retry_at:
        return
    _loading = True
    threading.Thread(target=_load, name="llm-quota-load", daemon=True).start()
