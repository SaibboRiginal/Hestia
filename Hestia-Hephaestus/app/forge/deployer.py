"""Forge deploy planner + built-in deployer (docker SDK, no compose needed).

Most services mount their code as a volume (``./Hestia-X/app:/code``), so after a
merge a container *restart* activates the change. Some changes need an image
rebuild instead (Dockerfile / requirements, the compiled WebUI): those cannot be
done from inside a container safely, so the user is told what to run.

``HEPHAESTUS_FORGE_DEPLOY_CMD``:
- ``builtin`` (default in docker-compose.global.yml): restart ``hestia_<svc>``
  containers through the Docker socket (``/var/run/docker.sock`` mounted).
- any shell command with ``{services}`` → run as before (custom setups).
- empty → no deploy, the user restarts manually.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("hestia_hephaestus.forge.deployer")

# Image-built services: a restart does NOT pick up code changes.
IMAGE_ONLY = {"webui"}
NO_CONTAINER = {"shared", "swagger", "atlas"}   # atlas runs on the host
REBUILD_FILES = ("Dockerfile", "requirements.txt", "package.json", "package-lock.json", ".csproj")


@dataclass
class DeployPlan:
    restart: list[str] = field(default_factory=list)
    rebuild: list[str] = field(default_factory=list)
    restart_self: bool = False

    def summary(self) -> str:
        parts = []
        if self.restart or self.restart_self:
            parts.append("riavvio: " + ", ".join(self.restart + (["hephaestus"] if self.restart_self else [])))
        if self.rebuild:
            parts.append("da ricostruire a mano: " + ", ".join(self.rebuild))
        return "; ".join(parts) or "nessun servizio da riavviare"


def all_services(repo: Path) -> list[str]:
    return sorted(p.name[len("Hestia-"):].lower() for p in repo.glob("Hestia-*")
                  if p.is_dir() and p.name[len("Hestia-"):].lower() not in NO_CONTAINER | {"dummy"})


def plan(repo: Path, changed_files: list[str]) -> DeployPlan:
    touched: set[str] = set()
    rebuild: set[str] = set()
    shared = False
    for path in changed_files:
        top = path.split("/", 1)[0]
        if not top.startswith("Hestia-"):
            continue
        name = top[len("Hestia-"):].lower()
        if name == "shared":
            shared = True
            continue
        if name in NO_CONTAINER:
            continue
        touched.add(name)
        if name in IMAGE_ONLY or path.endswith(REBUILD_FILES):
            rebuild.add(name)
    if shared:   # hestia_common is mounted in every Python service
        touched |= set(all_services(repo)) - IMAGE_ONLY
    restart = sorted(touched - rebuild)
    p = DeployPlan(restart=[s for s in restart if s != "hephaestus"], rebuild=sorted(rebuild))
    p.restart_self = "hephaestus" in restart
    return p


def restart_containers(services: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Restart ``hestia_<svc>`` containers via the Docker socket."""
    try:
        import docker  # type: ignore
        client = docker.from_env()
    except Exception as exc:
        return False, f"docker unavailable (mount /var/run/docker.sock): {exc}"
    ok, lines = True, []
    for name in services:
        try:
            client.containers.get(f"hestia_{name}").restart(timeout=timeout)
            lines.append(f"restarted hestia_{name}")
        except Exception as exc:
            ok = False
            lines.append(f"hestia_{name}: {exc}")
            logger.warning("[🔄] event=forge_restart_failed service=%s error=%s", name, exc)
    return ok, "\n".join(lines)
