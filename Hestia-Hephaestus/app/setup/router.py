"""HTTP door of the guided setup: ``/api/setup/*`` (called by the WebUI through the Hub, and by Telegram for the
one-time code). Values of secrets go in, never out: responses only say whether a key is set."""
from __future__ import annotations

import logging
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import secrets, tunnel
from .service import STEPS, SetupService

logger = logging.getLogger("hestia_hephaestus.setup.router")


class Step(BaseModel):
    step: str


class BrainTest(BaseModel):
    provider: str
    model: str = ""
    key: str = ""


class BrainApply(BaseModel):
    recipe: str
    local_model: str = ""
    cloud: list[str] = Field(default_factory=list)
    keys: dict[str, str] = Field(default_factory=dict)
    claude_token: str = ""


class Model(BaseModel):
    model: str


class Token(BaseModel):
    token: str


class Claim(BaseModel):
    code: str
    user_id: str


class Tunnel(BaseModel):
    on: bool = True


class Machine(BaseModel):
    id: str = ""
    address: str = ""
    name: str = ""


class Passphrase(BaseModel):
    passphrase: str = Field(min_length=12)


def hub_caller(hub_api_url: str):
    def call(service: str, path: str, method: str = "GET", body: dict | None = None, query: dict | None = None,
             timeout: float = 30) -> dict:
        resp = requests.post(f"{hub_api_url}/route/{service}/{path.lstrip('/')}",
                             json={"method": method, "headers": {}, "query": query or {}, "body": body,
                                   "timeout_seconds": timeout}, timeout=timeout + 5)
        resp.raise_for_status()
        routed = resp.json() or {}
        status = int(routed.get("status_code", 500))
        payload = routed.get("payload")
        if status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise HTTPException(status_code=502 if status >= 500 else status, detail=str(detail or status))
        return payload if isinstance(payload, dict) else {"payload": payload}
    return call


def create_setup_router(repo: Path, data_dir: Path, hub_api_url: str) -> tuple[APIRouter, SetupService]:
    service = SetupService(repo, data_dir, hub_call=hub_caller(hub_api_url))
    router = APIRouter(prefix="/api/setup", tags=["setup"])

    def refused(exc: secrets.SecretRefused):
        raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/state")
    def state():
        return {"status": "ok", **service.state()}

    @router.post("/later")
    def later(req: Step):
        if req.step not in STEPS:
            raise HTTPException(status_code=400, detail=f"step must be one of {', '.join(STEPS)}")
        return {"status": "ok", **service.mark(req.step, later=True)}

    @router.post("/complete")
    def complete():
        return {"status": "ok", **service.mark(completed=True)}

    # ── Cervello ──
    @router.get("/brain/catalog")
    def brain_catalog():
        hw = service.hardware()
        return service.oracle("GET", "/api/llm/setup/catalog",
                              query={"vram_gb": hw.get("vram_gb") or 0, "ram_gb": hw.get("ram_gb") or 0})

    @router.post("/brain/test")
    def brain_test(req: BrainTest):
        if req.key:
            try:
                done = service.set_secrets({f"ORACLE_KEY_{req.provider.upper().replace('-', '_')}": req.key})
            except secrets.SecretRefused as exc:
                refused(exc)
            if not done["services"].get("oracle", {}).get("recreated"):
                return {"status": "ok", "ok": False, "detail": "Non sono riuscito a salvare la chiave."}
            service._wait_oracle()
        return service.oracle("POST", "/api/llm/setup/test", body={"provider": req.provider, "model": req.model},
                              timeout=60)

    @router.post("/brain/apply")
    def brain_apply(req: BrainApply):
        try:
            result = service.apply_brain(req.recipe, req.local_model, req.cloud, req.keys, req.claude_token)
        except secrets.SecretRefused as exc:
            refused(exc)
        return {"status": "ok", **result}

    @router.post("/brain/pull")
    def brain_pull(req: Model):
        return service.oracle("POST", "/api/llm/setup/pull", body={"model": req.model})

    @router.get("/brain/pulls")
    def brain_pulls():
        return service.oracle("GET", "/api/llm/setup/pulls")

    # ── Telegram ──
    @router.post("/telegram/token")
    def telegram_token(req: Token):
        try:
            done = service.set_secrets({"TELEGRAM_BOT_TOKEN": req.token})
        except secrets.SecretRefused as exc:
            refused(exc)
        ok = done["services"].get("telegram", {}).get("recreated", False)
        return {"status": "ok", "ok": ok, **(service.new_code() if ok else {"detail": "Il bot non è ripartito."})}

    @router.post("/telegram/code")
    def telegram_code():
        if not secrets.is_set(repo, "TELEGRAM_BOT_TOKEN"):
            raise HTTPException(status_code=409, detail="bot token not set yet")
        return {"status": "ok", **service.new_code()}

    @router.post("/telegram/claim")
    def telegram_claim(req: Claim):
        try:
            return {"status": "ok", **service.claim(req.code, req.user_id)}
        except secrets.SecretRefused as exc:
            refused(exc)

    # ── Macchine: central and satellites (Hub /api/nodes, §4.0) ──
    def hub_own(method: str, path: str) -> dict:
        resp = requests.request(method, f"{hub_api_url}/{path}", timeout=10)
        if resp.status_code >= 400:
            detail = (resp.json() or {}).get("detail") if "json" in resp.headers.get("content-type", "") else ""
            raise HTTPException(status_code=resp.status_code, detail=str(detail or resp.status_code))
        return resp.json()

    @router.get("/machines")
    def machines():
        """This machine (role, hardware) and every satellite with its modules."""
        try:
            brain = service.oracle("GET", "/api/llm/setup/machine", timeout=8)
        except Exception as exc:                       # the brain off: the page still lists the machines
            logger.warning("[🔄] event=setup_machines_brain_unknown error=%s", str(exc)[:120])
            brain = {}
        return {"status": "ok", "this": {"role": service.role(), "hardware": service.hardware()},
                "nodes": hub_own("GET", "nodes").get("nodes", []), "brain_on": (brain or {}).get("address", "")}

    @router.post("/machines/pair")
    def machines_pair():
        """A pairing code for a new satellite, with the command to run on it."""
        out = hub_own("POST", "nodes/pair")
        return {"status": "ok", "code": out["code"], "expires_in": out["expires_in"],
                "central": service.hardware().get("lan_ip", "")}

    @router.post("/machines/revoke")
    def machines_revoke(req: Machine):
        if not req.id.isalnum():
            raise HTTPException(status_code=400, detail="id required")
        return {"status": "ok", **hub_own("DELETE", f"nodes/{req.id}")}

    @router.post("/machines/brain")
    def machines_brain(req: Machine):
        """Local models on that satellite's video card (empty address = back on this machine)."""
        return service.oracle("POST", "/api/llm/setup/machine", body={"address": req.address, "name": req.name})

    # ── Da fuori casa (Cloudflare quick tunnel, setup/tunnel.py) ──
    @router.get("/tunnel")
    def tunnel_status():
        """Whether the WebUI is reachable from outside home, and at which address."""
        return {"status": "ok", **tunnel.status()}

    @router.post("/tunnel")
    def tunnel_switch(req: Tunnel):
        """Turn the outside address on (waits up to 40 s for it) or off; the WebUI then asks the login token there."""
        try:
            out = tunnel.start() if req.on else tunnel.stop()
        except Exception as exc:
            logger.warning("[🔄] event=setup_tunnel_failed on=%s error=%s", req.on, str(exc)[:200])
            raise HTTPException(status_code=502, detail="Non sono riuscito a cambiare il collegamento da fuori casa: "
                                                        "controlla che Docker sia acceso e riprova.")
        service.mark("fuori")
        return {"status": "ok", **out}

    # ── Backup ──
    @router.post("/backup")
    def backup(req: Passphrase):
        try:
            done = service.set_secrets({"HESTIA_BACKUP_PASSPHRASE": req.passphrase})
        except secrets.SecretRefused as exc:
            refused(exc)
        service.mark("backup")
        return {"status": "ok", "ok": done["services"].get("archive", {}).get("recreated", False)}

    return router, service
