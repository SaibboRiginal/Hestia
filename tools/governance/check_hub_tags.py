#!/usr/bin/env python3
"""Every service registers with tags the Hub accepts.

A tag or topology value missing from the Hub vocabulary (``Hestia-Hub/src/modules/schemas.py``) makes the
registration fail with 422: the service only logs a warning and is unreachable through Hub. It broke CI on
three module PRs (Hygieia, Plutus, Echo), so it is checked here too, in seconds, before the test matrix.

Sources checked: ``SERVICE_TYPE`` / ``SERVICE_TAGS`` / ``SERVICE_TOPOLOGY_TAGS`` in the compose files and the
defaults in every ``Hestia-*/app/main.py`` (``ModuleKit(domain=...)`` modules too). Needs pydantic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker-compose.global.yml", "docker-compose.rpi.yml"]


def _env_value(line: str, name: str) -> str | None:
    match = re.search(rf"\b{name}=([^\s#]+)", line)
    return match.group(1) if match else None


def compose_services() -> list[tuple[str, str, list[str], list[str]]]:
    found = []
    for compose in COMPOSE:
        path = ROOT / compose
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


def source_defaults() -> list[tuple[str, str, list[str], list[str]]]:
    found = []
    for path in sorted(ROOT.glob("Hestia-*/app/main.py")):
        source = path.read_text(encoding="utf-8")
        where = str(path.relative_to(ROOT))
        tags = re.search(r'"SERVICE_TAGS",\s*"([^"]+)"', source)
        if tags:
            stype = re.search(r'"SERVICE_TYPE",\s*"([^"]+)"', source)
            topo = re.search(r'"SERVICE_TOPOLOGY_TAGS",\s*"([^"]+)"', source)
            found.append((where, stype.group(1) if stype else "core", tags.group(1).split(","),
                          topo.group(1).split(",") if topo else []))
            continue
        domain = (re.search(r'ModuleKit\([^)]*?domain="([a-z_]+)"', source, re.S)
                  or re.search(r'^DOMAIN = "([a-z_]+)"', source, re.M))
        if "ModuleKit(" in source and domain:
            extra = re.findall(r'tags=\(([^)]*)\)', source)
            words = [t.strip(" '\",") for t in (extra[0].split(",") if extra else [])]
            found.append((where, "module", ["module", domain.group(1)] + [w for w in words if w],
                          ["layer:domain", f"domain:{domain.group(1)}", "status:alpha"]))
    return found


def main() -> int:
    sys.path.insert(0, str(ROOT / "Hestia-Hub" / "src"))
    from modules.schemas import RegisterServiceRequest

    errors: list[str] = []
    rows = compose_services() + source_defaults()
    for where, stype, tags, topo in rows:
        try:
            RegisterServiceRequest(name="svc", base_url="http://svc:1", service_type=stype, tags=tags,
                                   topology_tags=topo)
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError, reported as text
            first = str(exc).splitlines()
            errors.append(f"{where}: " + " | ".join(line.strip() for line in first[1:4]))
    if errors:
        print("check_hub_tags: FAILED (add the value to Hestia-Hub/src/modules/schemas.py)")
        for err in errors:
            print(f"- {err}")
        return 1
    print(f"check_hub_tags: PASSED ({len(rows)} registrations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
