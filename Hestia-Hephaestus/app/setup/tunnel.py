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
import time
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


def status(client=None) -> dict[str, Any]:
    try:
        client = client or _client()
        box = _container(client)
    except Exception as exc:
        return {"on": False, "url": "", "detail": f"Docker non risponde: {str(exc)[:80]}"}
    on = bool(box) and box.status == "running"
    return {"on": on, "url": address(client, box) if on else ""}


def start(client=None, wait: float = 40) -> dict[str, Any]:
    client = client or _client()
    box = _container(client)
    if box is None:
        try:
            client.images.get(IMAGE)
        except Exception:
            logger.info("event=setup_tunnel_pull image=%s", IMAGE)
            client.images.pull(IMAGE)
        box = client.containers.create(IMAGE, command=COMMAND, name=NAME, network=NETWORK, detach=True,
                                       restart_policy={"Name": "unless-stopped"},
                                       labels={"hestia.role": "tunnel"})
    if box.status != "running":
        box.start()
    logger.info("event=setup_tunnel_started")
    deadline = time.time() + wait
    url = ""
    while not url and time.time() < deadline:
        time.sleep(2)
        box.reload()
        if box.status != "running":
            break
        url = address(client, box)
    if not url:
        logger.warning("[🔄] event=setup_tunnel_no_address status=%s", box.status)
        return {"on": box.status == "running", "url": "",
                "detail": "Il collegamento sta partendo: l'indirizzo compare tra poco."}
    return {"on": True, "url": url}


def stop(client=None) -> dict[str, Any]:
    client = client or _client()
    box = _container(client)
    if box is not None and box.status == "running":
        box.stop(timeout=10)       # unless-stopped: stays off after a reboot too
    logger.info("event=setup_tunnel_stopped")
    return {"on": False, "url": ""}
