"""Stack performance and storage growth alerts (Cindy D16 + 25)."""
from __future__ import annotations

import pytest

from schemas.reports import HealthReport
from services import performance

pytestmark = pytest.mark.unit


class _Container:
    def __init__(self, usage, total, system, mem):
        self._stats = {"cpu_stats": {"cpu_usage": {"total_usage": total}, "system_cpu_usage": system,
                                     "online_cpus": 2},
                       "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
                       "memory_stats": {"usage": mem, "limit": 4 * 1048576 * 1024, "stats": {"inactive_file": 0}}}
        self.attrs = {"State": {"StartedAt": "2026-10-24T10:00:00.123456789Z"}, "RestartCount": 1}

    def stats(self, stream=False, one_shot=True):
        return self._stats


class _Client:
    def __init__(self, containers):
        self.containers = self
        self._c = containers

    def get(self, name):
        if name not in self._c:
            raise KeyError(name)
        return self._c[name]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    performance.reset()
    monkeypatch.setattr(performance, "_hub_ms", lambda url: 12)
    yield
    performance.reset()


def _health(ms=50):
    return {"chronos": HealthReport(service="chronos", status="up", ms=ms)}


def test_cpu_from_delta_between_one_shot_samples():
    stats1 = {"cpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 10000, "online_cpus": 2}}
    stats2 = {"cpu_stats": {"cpu_usage": {"total_usage": 1500}, "system_cpu_usage": 11000, "online_cpus": 2}}
    assert performance._cpu_percent("x", stats1) is None
    assert performance._cpu_percent("x", stats2) == 100.0   # 500/1000 × 2 cpus


def test_sample_records_docker_numbers_and_storage():
    client = _Client({"hestia_chronos": _Container(0, 0, 0, 300 * 1048576)})
    route = lambda svc, path, **kw: (True, {"database_bytes": 1024 ** 3, "blob_bytes": 10, "blob_count": 1,
                                            "blobs_by_module": {"wardrobe": {"count": 1, "bytes": 10}}})
    alerts = []
    out = performance.take_sample(_health(), hub_api_url="http://hub/api", route=route,
                                  alert=lambda *a: alerts.append(a), client=client, now=1_800_000_000)
    m = out["services"]["chronos"]
    assert m["mem_mb"] == 300.0 and m["restarts"] == 1 and m["ms"] == 50 and m["uptime_s"] > 0
    snap = performance.snapshot()
    assert snap["hub_ms"] == 12 and snap["storage"]["database_bytes"] == 1024 ** 3
    assert performance.history()["series"]["chronos"]
    assert alerts == []


def test_memory_and_slow_answers_alert(monkeypatch):
    client = _Client({"hestia_chronos": _Container(0, 0, 0, 5000 * 1048576)})
    alerts = []
    for i in range(3):
        performance.take_sample(_health(ms=9000), hub_api_url="http://hub/api", route=lambda *a, **k: (False, None),
                                alert=lambda s, m, t: alerts.append(m), client=client, now=1_800_000_000 + i)
    assert alerts.count("memory") == 3      # deduplication is the alert worker's job (cooldown)
    assert alerts.count("response") == 1    # only when the streak reaches the threshold


def test_without_docker_only_response_times():
    out = performance.take_sample(_health(ms=70), hub_api_url="http://hub/api", route=lambda *a, **k: (False, None),
                                  alert=lambda *a: None, client=None, now=1_800_000_000)
    assert out["services"]["chronos"]["ms"] == 70 and "mem_mb" not in out["services"]["chronos"]


def test_storage_growth_alert():
    sizes = iter([1 * 1024 ** 3, 2 * 1024 ** 3])
    alerts = []
    for i in range(2):
        size = next(sizes)
        route = lambda svc, path, size=size, **kw: (True, {"database_bytes": size, "blob_bytes": 0, "blob_count": 0,
                                                           "blobs_by_module": {}})
        performance.take_sample({}, hub_api_url="http://hub/api", route=route, alert=lambda s, m, t: alerts.append(m),
                                client=None, now=1_800_000_000 + i * 7200)
    assert performance.storage_growth_day(now=1_800_000_000 + 7200) == 1024 ** 3
    assert "storage_growth" in alerts


def test_performance_routes_exist():
    import main as argus_main
    paths = argus_main.app.openapi()["paths"]
    assert "/api/argus/performance" in paths and "/api/argus/performance/history" in paths
