"""«Da fuori casa» — the WebUI reachable from outside home through a Cloudflare quick tunnel (§4.2, P5b).

Single responsibility: start, stop and read the ``hestia_tunnel`` container. It is created here through the Docker API
(not in compose: ``up-all`` and the installer must never open Hestia to the internet by themselves), on ``hestia_net``,
``restart: unless-stopped`` (on after a reboot until the user turns it off). cloudflared needs no account: it gives a
random ``https://<words>.trycloudflare.com`` address, new at every start. The WebUI asks the tunnel for it (metrics
``/quicktunnel``) and, from that host, always requires the login token.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("hestia_hephaestus.setup.tunnel")

NAME = "hestia_tunnel"
IMAGE = "cloudflare/cloudflared:2024.12.2"
NETWORK = "hestia_net"
METRICS = "http://hestia_tunnel:20241"
TARGET = "http://hestia_webui:19015"
COMMAND = ["tunnel", "--no-autoupdate", "--metrics", "0.0.0.0:20241", "--url", TARGET]
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _client():
    import docker
    return docker.from_env()


def _container(client):
    try:
        return client.containers.get(NAME)
    except Exception:
        return None


def address(client=None, container=None) -> str:
    """The public address now (empty while starting or off): metrics first, the container's log as fallback."""
    try:
        resp = requests.get(f"{METRICS}/quicktunnel", timeout=3)
        host = (resp.json() or {}).get("hostname") if resp.ok else ""
        if host:
            return f"https://{host}"
    except Exception:
        pass
    try:
        box = container or _container(client or _client())
        found = URL_RE.findall((box.logs(tail=200) or b"").decode("utf-8", "replace")) if box else []
        return found[-1] if found else ""
    except Exception as exc:
        logger.warning("[🔄] event=setup_tunnel_address_unknown error=%s", str(exc)[:120])
        return ""


# ── Background start: the first time the cloudflared image is downloaded (a job on the Download page), then the
# container starts and the address arrives. The request answers at once; the screen polls ``status``.
_downloads = None
_starting = {"phase": "", "error": ""}
_slock = threading.Lock()


def init(data_dir: Path | str) -> None:
    """Hephaestus' download manager (source ``docker``: an image pulled with progress), state in ``data_dir``."""
    global _downloads
    from hestia_common.downloads import Downloads
    with _slock:
        if _downloads is None:
            _downloads = Downloads("hephaestus", state_path=Path(data_dir) / "downloads.json", page="")
            _downloads.source("docker", _pull_image)


def downloads():
    return _downloads


def _pull_image(job) -> None:
    """``docker pull`` with the bytes summed over the layers (Docker API stream)."""
    client = _client()
    layers: dict[str, tuple[int, int]] = {}
    repo, _, tag = job.params["image"].partition(":")
    for line in client.api.pull(repo, tag=tag or "latest", stream=True, decode=True):
        if line.get("error"):
            raise RuntimeError(str(line["error"]))
        detail = line.get("progressDetail") or {}
        if line.get("id") and detail.get("total"):
            layers[line["id"]] = (int(detail.get("current") or 0), int(detail["total"]))
            job.progress(sum(c for c, _ in layers.values()), sum(t for _, t in layers.values()))
        else:
            job.check()


def status(client=None) -> dict[str, Any]:
    with _slock:
        phase, error = _starting["phase"], _starting["error"]
    if error:
        return {"on": False, "url": "", "phase": "error", "detail": error}
    if phase:
        return {"on": True, "url": "", "phase": phase,
                "detail": "Scarico il programma di Cloudflare…" if phase == "download" else "Avvio il collegamento…"}
    try:
        client = client or _client()
        box = _container(client)
    except Exception as exc:
        return {"on": False, "url": "", "detail": f"Docker non risponde: {str(exc)[:80]}"}
    on = bool(box) and box.status == "running"
    url = address(client, box) if on else ""
    return {"on": on, "url": url, "phase": "ready" if url else ("address" if on else "")}


def start(client=None, wait: float = 0) -> dict[str, Any]:
    """Turn it on without making the caller wait: a thread downloads the image if needed, creates and starts the
    container; ``status`` tells where it is (download → start → address → ready)."""
    with _slock:
        if _starting["phase"]:
            return status(client)
        _starting.update(phase="start", error="")
    threading.Thread(target=_start_now, args=(client,), name="tunnel-start", daemon=True).start()
    if wait:
        deadline = time.time() + wait
        while time.time() < deadline and status(client).get("phase") not in ("ready", "error"):
            time.sleep(0.2)
    return status(client)


def _start_now(client=None) -> None:
    try:
        client = client or _client()
        box = _container(client)
        if box is None:
            try:
                client.images.get(IMAGE)
            except Exception:
                logger.info("event=setup_tunnel_pull image=%s", IMAGE)
                with _slock:
                    _starting["phase"] = "download"
                if _downloads is not None:
                    _downloads.add(f"docker:{IMAGE}", "Collegamento da fuori casa (Cloudflare)", "docker",
                                   {"image": IMAGE}, size_hint=25_000_000)
                    job = _downloads.wait(f"docker:{IMAGE}", timeout=900)
                    if job.get("state") != "fatto":
                        raise RuntimeError(job.get("error") or "download non riuscito")
                else:
                    client.images.pull(IMAGE)
                with _slock:
                    _starting["phase"] = "start"
            box = client.containers.create(IMAGE, command=COMMAND, name=NAME, network=NETWORK, detach=True,
                                           restart_policy={"Name": "unless-stopped"},
                                           labels={"hestia.role": "tunnel"})
        if box.status != "running":
            box.start()
        logger.info("event=setup_tunnel_started")
        with _slock:
            _starting.update(phase="", error="")
    except Exception as exc:
        logger.warning("[🔄] event=setup_tunnel_start_failed error=%s", str(exc)[:200])
        with _slock:
            _starting.update(phase="", error="Non sono riuscito ad avviarlo: " + str(exc)[:120])


def stop(client=None) -> dict[str, Any]:
    with _slock:
        _starting.update(phase="", error="")
    client = client or _client()
    box = _container(client)
    if box is not None and box.status == "running":
        box.stop(timeout=10)       # unless-stopped: stays off after a reboot too
    logger.info("event=setup_tunnel_stopped")
    return {"on": False, "url": ""}
