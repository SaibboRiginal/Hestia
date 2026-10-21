"""Backup endpoints (SPEC docs/work/2026-10-20-backup-drive §3.3–3.4). Long jobs answer at once and run in the
background; ``GET /api/backup/status`` shows the step. Used by the agenda (run, verify) and by the Backup panel
in the settings (Archive's plugin element ``archive-backup-panel``)."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..backup.service import BackupService, JobBusy


class VerifyReq(BaseModel):
    file_id: Optional[str] = None


class RestoreReq(BaseModel):
    file_id: Optional[str] = None        # a backup on Drive (history)
    local: Optional[str] = None          # or a file copied into the backup volume's import/ folder (CLI)
    confirm: bool = False


class UndoReq(BaseModel):
    confirm: bool = False


def build_router(service: BackupService, *, passphrase_set, drive_status, settings_view, drive_connect) -> APIRouter:
    router = APIRouter(prefix="/api/backup", tags=["backup"])
    cache: dict = {"at": 0.0, "drive": None}

    def _drive(fresh: bool = False) -> dict:
        if fresh or cache["drive"] is None or time.monotonic() - cache["at"] > 60:
            cache["drive"], cache["at"] = drive_status(), time.monotonic()
        return cache["drive"]

    def _start(kind: str, fn, *args) -> dict:
        try:
            return {"status": "started", **service.start(kind, fn, *args)}
        except JobBusy as exc:
            raise HTTPException(status_code=409, detail={"error": "busy", "job": str(exc),
                                                         "message": "c'è già un'operazione di backup in corso"})

    @router.get("/status")
    def status(fresh: bool = False):
        st = service.state()
        return {"job": service.job(), "last_backup": st.get("last_backup"), "last_verify": st.get("last_verify"),
                "last_restore": st.get("last_restore"), "problem": st.get("problem"),
                "passphrase_set": bool(passphrase_set()), "drive": _drive(fresh),
                "undo_available": service.undo_available() if service.job() is None else False,
                "settings": settings_view()}

    @router.post("/drive/connect")
    def connect_drive():
        """Starts Google's authorization (owned by the provider gateway) so the panel can open the link."""
        out = drive_connect()
        cache["drive"] = None
        return out

    @router.get("/list")
    def history():
        return service.history()

    @router.post("/run")
    def run():
        return _start("backup", service.run)

    @router.post("/verify")
    def verify(req: VerifyReq | None = None):
        return _start("verify", service.verify, (req.file_id if req else None))

    @router.post("/restore")
    def restore(req: RestoreReq):
        if not req.confirm:
            raise HTTPException(status_code=422, detail={"error": "confirm",
                                                         "message": "conferma il ripristino (confirm=true)"})
        if not (req.file_id or req.local):
            raise HTTPException(status_code=422, detail={"error": "file", "message": "indica file_id oppure local"})
        return _start("restore", service.restore, req.file_id, req.local)

    @router.post("/undo")
    def undo(req: UndoReq):
        if not req.confirm:
            raise HTTPException(status_code=422, detail={"error": "confirm",
                                                         "message": "conferma l'annullamento (confirm=true)"})
        if not service.undo_available():
            raise HTTPException(status_code=404, detail={"error": "nothing_to_undo",
                                                         "message": "non c'è un ripristino da annullare"})
        return _start("undo", service.undo)

    return router
