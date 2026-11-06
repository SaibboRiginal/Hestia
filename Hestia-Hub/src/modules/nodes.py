"""Machines of one Hestia — central and satellites (docs/work/2026-10-30-setup-un-click §4.0).

Single responsibility: pairing and the per-machine join token. The central's Hub shows a pairing code (6 digits,
10 minutes, 5 tries); the satellite's installer sends it with its name and LAN address and gets a token. From then on
the satellite's Hub (relay mode, ``relay.py``) registers the satellite's modules here with that token, and this Hub
routes to them at the satellite's address. «Scollega» revokes the token and forgets the satellite's modules.

Stored in Hub's own volume (``/code/data/nodes.json``), like the registry snapshot: Hub's own table, not business data.
Only a sha256 of each token is kept.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(f"hestia_hub.{__name__}")

NODES_PATH = Path("/code/data/nodes.json")
CODE_TTL = 600
CODE_TRIES = 5
ROLES = ("satellite",)
NODE_HEADER = "X-Hestia-Node-Token"


class NodeError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Nodes:
    def __init__(self, path: Path | str = NODES_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._code: dict[str, Any] = {}
        self._nodes: dict[str, dict[str, Any]] = self._load()

    # ── pairing ──────────────────────────────────────────────────────────────
    def new_code(self) -> dict[str, Any]:
        with self._lock:
            self._code = {"code": f"{secrets.randbelow(10**6):06d}", "expires": time.time() + CODE_TTL, "tries": 0}
        logger.info("event=hub_pair_code_issued ttl=%s", CODE_TTL)
        return {"code": self._code["code"], "expires_in": CODE_TTL}

    def join(self, code: str, name: str, address: str, role: str = "satellite") -> dict[str, Any]:
        name = str(name or "").strip()[:40] or "satellite"
        address = str(address or "").strip()
        if not address or any(c in address for c in "/:@ ") or len(address) > 120:
            raise NodeError("address must be a bare host name or IP")
        if role not in ROLES:
            raise NodeError(f"role must be one of {', '.join(ROLES)}")
        with self._lock:
            if not self._code or self._code["expires"] < time.time():
                raise NodeError("no active pairing code", 403)
            if not secrets.compare_digest(str(code).strip(), self._code["code"]):
                self._code["tries"] += 1
                if self._code["tries"] >= CODE_TRIES:
                    self._code = {}
                    logger.warning("event=hub_pair_code_burned reason=too_many_tries")
                raise NodeError("wrong pairing code", 403)
            self._code = {}
            token = secrets.token_urlsafe(32)
            node_id = secrets.token_hex(4)
            self._nodes[node_id] = {"id": node_id, "name": name, "role": role, "address": address,
                                    "token_sha256": _hash(token), "joined_at": time.time(), "last_seen": None}
            self._save()
        logger.info("event=hub_node_joined node=%s name=%s address=%s", node_id, name, address)
        return {"node_id": node_id, "token": token, "name": name}

    # ── tokens ───────────────────────────────────────────────────────────────
    def check(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        digest = _hash(token)
        with self._lock:
            for node in self._nodes.values():
                if secrets.compare_digest(node["token_sha256"], digest):
                    node["last_seen"] = time.time()
                    return dict(node)
        return None

    def admit(self, token: str, base_url: str) -> dict[str, Any]:
        """A registration sent with a node token: the token must be valid and the module must live at that node's
        address (a satellite cannot register a module somewhere else)."""
        node = self.check(token)
        if not node:
            raise NodeError("unknown or revoked machine", 401)
        host = (urlsplit(base_url).hostname or "").lower()
        if host != node["address"].lower():
            raise NodeError("a satellite registers only modules at its own address", 403)
        return node

    def revoke(self, node_id: str) -> dict[str, Any]:
        with self._lock:
            node = self._nodes.pop(node_id, None)
            if not node:
                raise NodeError("machine not found", 404)
            self._save()
        logger.info("event=hub_node_revoked node=%s name=%s", node_id, node["name"])
        return node

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in n.items() if k != "token_sha256"} for n in self._nodes.values()]

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            return {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id") and r.get("token_sha256")}
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning("[🔄] event=hub_nodes_unreadable error=%s fallback=empty", exc)
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(list(self._nodes.values())), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            logger.warning("[🔄] event=hub_nodes_not_saved error=%s", exc)
