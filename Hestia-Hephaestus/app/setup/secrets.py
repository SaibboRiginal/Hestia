"""Secrets the guided setup may write (docs/work/2026-10-30-setup-un-click §4.2).

Secrets stay where the rules want them, in the ``.env`` files of the repo (mounted at ``/repo``), so a later
``docker compose up`` keeps them. Only the keys of ``WHITELIST`` (and ``ORACLE_KEY_<NAME>``) are accepted, a value is
never logged nor returned, and the affected containers get the new value without a whole-stack restart:
``env_file`` values are read only when a container is *created*, so a plain restart would not see them —
``recreate_with_env`` re-creates the container through the Docker socket with the same image, mounts, ports and
networks and only the changed variables (the old one is kept until the new one runs: on failure it comes back).
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hestia_hephaestus.setup.secrets")


@dataclass(frozen=True)
class Target:
    env_file: str              # relative to the repo
    services: tuple[str, ...]  # containers hestia_<svc> that read it


WHITELIST: dict[str, Target] = {
    "TELEGRAM_BOT_TOKEN": Target("Hestia-Telegram/app/.env", ("telegram",)),
    "ALLOWED_USER_ID": Target("Hestia-Telegram/app/.env", ("telegram",)),
    "CLAUDE_CODE_OAUTH_TOKEN": Target("Hestia-Oracle/app/.env", ("oracle",)),
    "HESTIA_BACKUP_PASSPHRASE": Target(".env", ("archive",)),
    "HF_TOKEN": Target("Hestia-Oracle/app/.env", ("oracle",)),
}
_ORACLE_KEY = re.compile(r"^ORACLE_KEY_[A-Z0-9_]{1,40}$")
_VALUE_OK = re.compile(r"^[\x21-\x7e]{1,4096}$")          # printable ASCII, no spaces, no newlines, no quotes issues
_USER_IDS = re.compile(r"^\d{1,20}(,\d{1,20}){0,9}$")


class SecretRefused(ValueError):
    pass


def target_for(key: str) -> Target:
    key = str(key or "").strip()
    if key in WHITELIST:
        return WHITELIST[key]
    if _ORACLE_KEY.match(key):
        return Target("Hestia-Oracle/app/.env", ("oracle",))
    raise SecretRefused(f"key not allowed: {key[:60]}")


def validate(key: str, value: str) -> str:
    value = str(value or "").strip()
    if not _VALUE_OK.match(value) or "#" in value[:1]:
        raise SecretRefused("value must be one line of printable characters")
    if key == "ALLOWED_USER_ID" and not _USER_IDS.match(value):
        raise SecretRefused("ALLOWED_USER_ID must be numeric ids separated by commas")
    if key == "TELEGRAM_BOT_TOKEN" and not re.match(r"^\d{5,20}:[A-Za-z0-9_-]{20,}$", value):
        raise SecretRefused("this does not look like a BotFather token")
    return value


def is_set(repo: Path, key: str) -> bool:
    """Whether the key has a value in its .env (the value itself is never read out)."""
    try:
        path = repo / target_for(key).env_file
    except SecretRefused:
        return False
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key and value.strip():
            return True
    return False


def write_env(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in an env file: replace the active line, else a commented ``# key=`` line, else append.
    Atomic (temp file + replace); the other lines are kept byte for byte."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    active = re.compile(rf"^\s*{re.escape(key)}\s*=")
    commented = re.compile(rf"^\s*#\s*{re.escape(key)}\s*=")
    index = next((i for i, line in enumerate(lines) if active.match(line)), None)
    if index is None:
        index = next((i for i, line in enumerate(lines) if commented.match(line)), None)
    if index is None:
        lines.append(f"{key}={value}")
    else:
        lines[index] = f"{key}={value}"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    if path.exists():
        os.chmod(tmp, path.stat().st_mode & 0o777)
    os.replace(tmp, path)


def set_secret(repo: Path, key: str, value: str) -> Target:
    target = target_for(key)
    value = validate(key, value)
    write_env(repo / target.env_file, key, value)
    logger.info("event=setup_secret_set key=%s file=%s services=%s", key, target.env_file, ",".join(target.services))
    return target


# ── Re-create a container with changed environment variables ──────────────────

_CONFIG_KEEP = ("Hostname", "Domainname", "User", "ExposedPorts", "Tty", "OpenStdin", "Cmd", "Image", "WorkingDir",
                "Entrypoint", "Labels", "StopSignal", "Healthcheck")


def merged_env(env: list[str], updates: dict[str, str]) -> list[str]:
    out, seen = [], set()
    for item in env or []:
        name = item.split("=", 1)[0]
        if name in updates:
            out.append(f"{name}={updates[name]}")
            seen.add(name)
        else:
            out.append(item)
    out.extend(f"{k}={v}" for k, v in updates.items() if k not in seen)
    return out


def recreate_with_env(service: str, updates: dict[str, str], start: bool = True, client=None) -> tuple[bool, str]:
    """Re-create ``hestia_<service>`` with ``updates`` applied to its environment. Returns (ok, detail)."""
    import docker
    name = f"hestia_{service}"
    api = (client or docker.from_env()).api
    try:
        attrs = api.inspect_container(name)
    except Exception as exc:
        return False, f"container {name} not found: {exc}"
    config = {k: attrs["Config"].get(k) for k in _CONFIG_KEEP if attrs["Config"].get(k) is not None}
    config["Env"] = merged_env(attrs["Config"].get("Env") or [], updates)
    networks = attrs.get("NetworkSettings", {}).get("Networks", {}) or {}
    endpoints = {net: {"Aliases": [a for a in (cfg.get("Aliases") or []) if a != attrs["Id"][:12]]}
                 for net, cfg in networks.items()}
    was_running = bool(attrs.get("State", {}).get("Running"))
    old_name = f"{name}_old_{os.getpid()}"
    try:
        if was_running:
            api.stop(name, timeout=15)
        api.rename(name, old_name)
        created = api.create_container(name=name, host_config=attrs["HostConfig"],
                                       networking_config={"EndpointsConfig": endpoints}, **_create_kwargs(config))
        if start:
            api.start(created["Id"])
    except Exception as exc:
        logger.warning("[🔄] event=setup_recreate_failed service=%s error=%s — restoring the old container",
                       service, str(exc)[:200])
        _restore(api, name, old_name, was_running)
        return False, str(exc)[:300]
    try:
        api.remove_container(old_name, force=True)
    except Exception as exc:
        logger.warning("[🔄] event=setup_old_container_left service=%s error=%s", service, exc)
    logger.info("event=setup_recreated service=%s keys=%s started=%s", service, ",".join(sorted(updates)), start)
    return True, "ok"


def _create_kwargs(config: dict) -> dict:
    """Docker Engine config keys → docker-py ``create_container`` keyword arguments."""
    mapping = {"Image": "image", "Cmd": "command", "Hostname": "hostname", "User": "user", "Env": "environment",
               "WorkingDir": "working_dir", "Entrypoint": "entrypoint", "Labels": "labels", "Tty": "tty",
               "OpenStdin": "stdin_open", "StopSignal": "stop_signal", "Domainname": "domainname",
               "Healthcheck": "healthcheck"}
    out = {mapping[k]: v for k, v in config.items() if k in mapping}
    if isinstance(out.get("healthcheck"), dict):   # Engine keys (Test, StartPeriod) → docker-py's (test, start_period)
        out["healthcheck"] = {re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v for k, v in out["healthcheck"].items()}
    out["use_config_proxy"] = False   # keep the environment exactly as it was, plus the updates
    if config.get("ExposedPorts"):
        out["ports"] = [tuple(p.split("/")) if "/" in p else p for p in config["ExposedPorts"]]
        out["ports"] = [(int(p[0]), p[1]) if isinstance(p, tuple) else int(p) for p in out["ports"]]
    return out


def _restore(api, name: str, old_name: str, was_running: bool) -> None:
    try:
        api.remove_container(name, force=True)
    except Exception:
        pass
    try:
        api.rename(old_name, name)
        if was_running:
            api.start(name)
    except Exception as exc:
        logger.error("event=setup_restore_failed container=%s error=%s", name, exc)
