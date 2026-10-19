"""Regression: every service's tags in the compose files pass Hub registration validation.

A rejected registration (422) only logs a warning in the service and makes it unreachable
through Hub (503 on /route/<svc>/...): Themis (`settings`, `layer:core`) and Metis (`improvement`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from modules.schemas import RegisterServiceRequest

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = ["docker-compose.global.yml", "docker-compose.rpi.yml"]


def _env_value(line: str, name: str) -> str | None:
    match = re.search(rf"\b{name}=([^\s#]+)", line)
    return match.group(1) if match else None


def _services() -> list[tuple[str, str, list[str], list[str]]]:
    found = []
    for compose in _COMPOSE:
        path = _ROOT / compose
        if not path.exists():
            continue
        current, stype, tags, topo = None, "core", None, None
        for line in path.read_text(encoding="utf-8").splitlines() + ["  end:"]:
            if re.match(r"^  [a-z0-9_-]+:\s*$", line):
                if current and (tags is not None or topo is not None):
                    found.append((f"{compose}:{current}", stype, tags or [], topo or []))
                current, stype, tags, topo = line.strip()[:-1], "core", None, None
                continue
            if (value := _env_value(line, "SERVICE_TYPE")) is not None:
                stype = value
            if (value := _env_value(line, "SERVICE_TAGS")) is not None:
                tags = value.split(",")
            if (value := _env_value(line, "SERVICE_TOPOLOGY_TAGS")) is not None:
                topo = value.split(",")
    return found


@pytest.mark.unit
@pytest.mark.parametrize("service,service_type,tags,topology", _services(), ids=lambda v: v if isinstance(v, str) else "")
def test_compose_tags_pass_hub_validation(service, service_type, tags, topology):
    RegisterServiceRequest(name="svc", base_url="http://svc:1", service_type=service_type, tags=tags,
                           topology_tags=topology)


@pytest.mark.unit
def test_themis_default_tags_pass_hub_validation():
    source = (_ROOT / "Hestia-Themis" / "app" / "main.py").read_text(encoding="utf-8")
    tags = re.search(r'"SERVICE_TAGS", "([^"]+)"', source).group(1).split(",")
    topo = re.search(r'"SERVICE_TOPOLOGY_TAGS", "([^"]+)"', source).group(1).split(",")
    RegisterServiceRequest(name="themis", base_url="http://themis:1", tags=tags, topology_tags=topo)


@pytest.mark.unit
def test_hercules_default_tags_pass_hub_validation():
    source = (_ROOT / "Hestia-Hercules" / "app" / "main.py").read_text(encoding="utf-8")
    stype = re.search(r'"SERVICE_TYPE", "([^"]+)"', source).group(1)
    tags = re.search(r'"SERVICE_TAGS", "([^"]+)"', source).group(1).split(",")
    topo = re.search(r'"SERVICE_TOPOLOGY_TAGS", "([^"]+)"', source).group(1).split(",")
    RegisterServiceRequest(name="hercules", base_url="http://hercules:1", service_type=stype, tags=tags,
                           topology_tags=topo)


@pytest.mark.unit
def test_plutus_default_tags_pass_hub_validation():
    """Plutus (finance) was rejected with 422 'Unsupported tag finance' on the first cloud bench run."""
    source = (_ROOT / "Hestia-Plutus" / "app" / "main.py").read_text(encoding="utf-8")
    stype = re.search(r'"SERVICE_TYPE", "([^"]+)"', source).group(1)
    tags = re.search(r'"SERVICE_TAGS", "([^"]+)"', source).group(1).split(",")
    topo = re.search(r'"SERVICE_TOPOLOGY_TAGS",\s*"([^"]+)"', source).group(1).split(",")
    RegisterServiceRequest(name="plutus", base_url="http://plutus:1", service_type=stype, tags=tags,
                           topology_tags=topo)
