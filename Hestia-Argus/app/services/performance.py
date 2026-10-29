"""Stack performance and storage growth (Cindy D16 + 25, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W3).

Every ``argus.performance.every_cycles`` monitor cycles (central setting) one sample is taken in a background
thread, so the health loop never waits on Docker:

- per module: CPU % and memory from the read-only Docker socket (``stats(one_shot)``, CPU from the delta with the
  previous sample), start time and restart count, plus the ``/health`` response time of the cycle;
- the Hub round trip (``GET /health`` of the Hub);
- storage: database size and blobs per module from Archive ``GET /api/blobs/usage`` (at most once per hour).

History stays in memory (24 h, since Argus started). Over a Themis threshold (memory, CPU for N samples in a row,
slow answers for N samples in a row, data size, growth per day) an alert goes through the usual batched,
deduplicated alert worker (kind ``performance``). Without the Docker socket only response times are measured.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from core import argus_settings as cfg

logger = logging.getLogger(f"hestia_argus.{__name__}")

_DAY = 86400
_STORAGE_EVERY = 3600

_lock = threading.Lock()
_running = threading.Event()
_series: dict[str, deque] = {}          # service → deque of samples
_storage: deque = deque()               # {at, database_bytes, blob_bytes, blob_count}
_last: dict[str, Any] = {"at": None, "hub_ms": None, "services": {}, "storage": None}
_prev_cpu: dict[str, tuple[int, int]] = {}
_streak: dict[str, int] = {}            # "<svc>:cpu" / "<svc>:ms" → samples in a row over the threshold
_state = {"cycle": 0, "storage_at": 0.0}


def reset() -> None:
    with _lock:
        _series.clear()
        _storage.clear()
        _prev_cpu.clear()
        _streak.clear()
        _last.update(at=None, hub_ms=None, services={}, storage=None)
        _state.update(cycle=0, storage_at=0.0)


# ── measuring ───────────────────────────────────────────────────────────────
def _cpu_percent(name: str, stats: dict) -> float | None:
    cpu = stats.get("cpu_stats") or {}
    total = int(((cpu.get("cpu_usage") or {}).get("total_usage")) or 0)
    system = int(cpu.get("system_cpu_usage") or 0)
    cpus = int(cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1)
    pre = stats.get("precpu_stats") or {}
    pre_total = int(((pre.get("cpu_usage") or {}).get("total_usage")) or 0)
    pre_system = int(pre.get("system_cpu_usage") or 0)
    if not pre_system and name in _prev_cpu:      # one_shot: no precpu → our previous sample
        pre_total, pre_system = _prev_cpu[name]
    _prev_cpu[name] = (total, system)
    if not pre_system or system <= pre_system or total < pre_total:
        return None
    return round((total - pre_total) / (system - pre_system) * cpus * 100, 1)


def _memory_mb(stats: dict) -> tuple[float | None, float | None]:
    mem = stats.get("memory_stats") or {}
    usage = mem.get("usage")
    if usage is None:
        return None, None
    cache = int(((mem.get("stats") or {}).get("inactive_file")) or ((mem.get("stats") or {}).get("cache")) or 0)
    limit = mem.get("limit")
    return round((int(usage) - cache) / 1048576, 1), (round(int(limit) / 1048576, 1) if limit else None)


def container_sample(client: Any, service: str) -> dict:
    """Docker numbers of one module (``hestia_<service>``); {} when the container is not there."""
    try:
        container = client.containers.get(f"hestia_{service}")
        try:
            stats = container.stats(stream=False, one_shot=True)
        except TypeError:  # old docker SDK: no one_shot (slower, but has precpu)
            stats = container.stats(stream=False)
        state = (container.attrs or {}).get("State") or {}
        mem, limit = _memory_mb(stats or {})
        return {"cpu": _cpu_percent(service, stats or {}), "mem_mb": mem, "mem_limit_mb": limit,
                "started_at": state.get("StartedAt"), "restarts": (container.attrs or {}).get("RestartCount")}
    except Exception as exc:  # noqa: BLE001 — container missing or socket not readable
        logger.debug("event=argus_perf_container_unavailable service=%s error=%s", service, exc)
        return {}


def _docker():
    try:
        import docker  # type: ignore
        return docker.from_env()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[🔄] event=argus_perf_docker_unavailable error=%s fallback=response_times_only", exc)
        return None


def _hub_ms(hub_api_url: str) -> int | None:
    base = hub_api_url.rstrip("/")
    base = base[:-4] if base.endswith("/api") else base
    t0 = time.perf_counter()
    try:
        requests.get(f"{base}/health", timeout=5)
    except Exception:  # noqa: BLE001
        return None
    return int((time.perf_counter() - t0) * 1000)


def _uptime(started_at: str | None, now: float) -> int | None:
    if not started_at or started_at.startswith("0001"):
        return None
    try:
        start = datetime.fromisoformat(started_at[:26].rstrip("Z") + "+00:00").timestamp()
    except ValueError:
        return None
    return max(0, int(now - start))


# ── alerts ──────────────────────────────────────────────────────────────────
def _over(key: str, over: bool) -> int:
    _streak[key] = _streak.get(key, 0) + 1 if over else 0
    return _streak[key]


def check(sample: dict, storage: dict | None, alert: Callable[[str, str, str], None]) -> list[str]:
    """Threshold checks on one sample; ``alert(service, metric, message)``. Returns the metrics alerted."""
    out: list[str] = []
    mem_max = cfg.get_int(cfg.PERF_MEMORY_MB, 1)
    cpu_max = cfg.get_int(cfg.PERF_CPU, 1)
    ms_max = cfg.get_int(cfg.PERF_RESPONSE_MS, 1)
    need = cfg.get_int(cfg.PERF_CPU_SAMPLES, 1)
    for svc, m in sorted(sample.items()):
        if m.get("mem_mb") is not None and m["mem_mb"] > mem_max:
            alert(svc, "memory", f"Usa {m['mem_mb']:.0f} MB di memoria (limite {mem_max} MB).")
            out.append(f"{svc}:memory")
        if _over(f"{svc}:cpu", m.get("cpu") is not None and m["cpu"] > cpu_max) == need:
            alert(svc, "cpu", f"Processore al {m['cpu']:.0f}% da {need} misure di fila (limite {cpu_max}%).")
            out.append(f"{svc}:cpu")
        if _over(f"{svc}:ms", m.get("ms") is not None and m["ms"] > ms_max) == need:
            alert(svc, "response", f"Risponde lento: {m['ms']} ms da {need} misure di fila (limite {ms_max} ms).")
            out.append(f"{svc}:response")
    if storage and storage.get("database_bytes") is not None:
        total = int(storage["database_bytes"] or 0)
        limit = cfg.get_int(cfg.STORAGE_DB_GB, 1) * 1024 ** 3
        if total > limit:
            alert("archive", "storage_size", f"I dati salvati sono {total / 1024 ** 3:.1f} GB "
                                             f"(limite {cfg.get_int(cfg.STORAGE_DB_GB, 1)} GB).")
            out.append("archive:storage_size")
        growth = storage_growth_day()
        growth_max = cfg.get_int(cfg.STORAGE_GROWTH_MB, 1)
        if growth is not None and growth / 1048576 > growth_max:
            top = sorted((storage.get("blobs_by_module") or {}).items(), key=lambda kv: -kv[1].get("bytes", 0))[:3]
            who = ", ".join(f"{k} {v.get('bytes', 0) / 1048576:.0f} MB" for k, v in top)
            alert("archive", "storage_growth", f"I dati salvati sono cresciuti di {growth / 1048576:.0f} MB "
                                               f"nell'ultimo giorno (limite {growth_max} MB)."
                                               + (f" File più grandi: {who}." if who else ""))
            out.append("archive:storage_growth")
    return out


def storage_growth_day(now: float | None = None) -> int | None:
    """Bytes gained in the last 24 h (database, which includes the blobs), None with < 1 h of history."""
    now = now or time.time()
    with _lock:
        rows = [r for r in _storage if r.get("database_bytes") is not None]
    if len(rows) < 2:
        return None
    first = next((r for r in rows if r["at"] >= now - _DAY), rows[0])
    last = rows[-1]
    if last["at"] - first["at"] < 3600:
        return None
    return int(last["database_bytes"]) - int(first["database_bytes"])


# ── one sample ──────────────────────────────────────────────────────────────
def take_sample(health: dict[str, Any], *, hub_api_url: str, route: Callable[..., tuple[bool, Any]],
                alert: Callable[[str, str, str], None], client: Any = "auto", now: float | None = None) -> dict:
    now = now or time.time()
    client = _docker() if client == "auto" else client
    services: dict[str, dict] = {}
    for name, report in sorted(health.items()):
        m = {"ms": getattr(report, "ms", None), "status": getattr(report, "status", None)}
        if client is not None:
            m.update(container_sample(client, name))
        m["uptime_s"] = _uptime(m.get("started_at"), now)
        services[name] = m
    storage = None
    if now - _state["storage_at"] >= _STORAGE_EVERY:
        ok, payload = route("archive", "api/blobs/usage", timeout=20)
        if ok and isinstance(payload, dict):
            storage = {"at": now, **{k: payload.get(k) for k in ("database_bytes", "blob_bytes", "blob_count",
                                                                  "blobs_by_module")}}
            _state["storage_at"] = now
    hub_ms = _hub_ms(hub_api_url)
    with _lock:
        for name, m in services.items():
            series = _series.setdefault(name, deque())
            series.append({"at": now, "cpu": m.get("cpu"), "mem_mb": m.get("mem_mb"), "ms": m.get("ms")})
            while series and series[0]["at"] < now - _DAY:
                series.popleft()
        if storage:
            _storage.append({k: storage[k] for k in ("at", "database_bytes", "blob_bytes", "blob_count")})
            while _storage and _storage[0]["at"] < now - 7 * _DAY:
                _storage.popleft()
        _last.update(at=now, hub_ms=hub_ms, services=services, storage=storage or _last.get("storage"))
    alerted = check(services, storage, alert)
    logger.info("event=argus_perf_sample services=%d docker=%s hub_ms=%s storage=%s alerts=%d",
                len(services), client is not None, hub_ms, bool(storage), len(alerted))
    return {"services": services, "hub_ms": hub_ms, "storage": storage, "alerts": alerted}


def maybe_sample(health: dict[str, Any], **kwargs) -> bool:
    """Called every monitor cycle: starts a background sample every N cycles (never two at once)."""
    _state["cycle"] += 1
    if (_state["cycle"] - 1) % cfg.get_int(cfg.PERF_EVERY, 1) or _running.is_set():
        return False
    _running.set()

    def _run() -> None:
        try:
            take_sample(health, **kwargs)
        except Exception as exc:  # noqa: BLE001 — never break the monitor
            logger.warning("[🔄] event=argus_perf_sample_failed error=%s fallback=next_cycle", exc)
        finally:
            _running.clear()

    threading.Thread(target=_run, daemon=True, name="argus-perf-sample").start()
    return True


# ── views ───────────────────────────────────────────────────────────────────
def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def snapshot() -> dict:
    with _lock:
        last = {**_last, "services": {k: dict(v) for k, v in (_last.get("services") or {}).items()}}
    storage = last.get("storage")
    return {"at": _iso(last.get("at")), "hub_ms": last.get("hub_ms"), "services": last["services"],
            "storage": ({**storage, "at": _iso(storage.get("at")), "growth_day_bytes": storage_growth_day()}
                        if storage else None),
            "thresholds": {"memory_mb": cfg.get_int(cfg.PERF_MEMORY_MB, 1), "cpu_percent": cfg.get_int(cfg.PERF_CPU, 1),
                           "response_ms": cfg.get_int(cfg.PERF_RESPONSE_MS, 1),
                           "database_gb": cfg.get_int(cfg.STORAGE_DB_GB, 1),
                           "growth_mb_day": cfg.get_int(cfg.STORAGE_GROWTH_MB, 1)}}


def history(service: str | None = None, hours: int = 24, now: float | None = None) -> dict:
    now = now or time.time()
    since = now - max(1, min(int(hours), 24)) * 3600
    with _lock:
        series = {name: [{**s, "at": _iso(s["at"])} for s in rows if s["at"] >= since]
                  for name, rows in _series.items() if not service or name == service}
        storage = [{**s, "at": _iso(s["at"])} for s in _storage if s["at"] >= now - 7 * _DAY]
    return {"hours": hours, "series": series, "storage": storage}
