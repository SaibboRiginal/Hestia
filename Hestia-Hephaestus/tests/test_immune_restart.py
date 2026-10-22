"""Immune system hands (docs/work/2026-10-19-oracle-offline v3 B): guarded container restart + health check."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core import container_restart


class _Forge:
    def __init__(self, deploying=(), unhealthy=()):
        self._deploying, self._unhealthy = set(deploying), list(unhealthy)

    def deploying_services(self):
        return self._deploying

    def unhealthy(self, services):
        return [s for s in services if s in self._unhealthy]


@pytest.fixture
def restarted(monkeypatch):
    calls = []
    monkeypatch.setattr(container_restart.deployer, "restart_containers",
                        lambda services: calls.append(services) or (True, "restarted hestia_" + services[0]))
    return calls


@pytest.mark.unit
def test_restart_then_healthy(restarted):
    out = container_restart.restart("hecate", _Forge(), "argus.immune", 1)
    assert restarted == [["hecate"]] and out["status"] == "ok" and out["healthy"] is True


@pytest.mark.unit
def test_restart_but_still_unhealthy(restarted):
    out = container_restart.restart("hecate", _Forge(unhealthy=["hecate"]))
    assert out["restarted"] is True and out["healthy"] is False


@pytest.mark.unit
@pytest.mark.parametrize("name", ["hephaestus", "../etc", "Hecate;rm", ""])
def test_refuses_self_and_bad_names(restarted, name):
    assert container_restart.restart(name, _Forge())["status"] == "refused"
    assert restarted == []


@pytest.mark.unit
def test_skips_a_service_forge_is_deploying(restarted):
    assert container_restart.restart("scout", _Forge(deploying=["scout"]))["status"] == "skipped"
    assert restarted == []


@pytest.mark.unit
def test_endpoint_routes_to_restart(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.hephaestus_router import create_hephaestus_router
    seen = {}
    monkeypatch.setattr(container_restart, "restart",
                        lambda service, forge, reason="", attempt=0: seen.update(s=service, a=attempt) or {"status": "ok"})
    app = FastAPI()
    app.include_router(create_hephaestus_router(MagicMock(), forge=_Forge()))
    res = TestClient(app).post("/api/hephaestus/restart", json={"service": "hecate", "attempt": 2})
    assert res.json() == {"status": "ok"} and seen == {"s": "hecate", "a": 2}
