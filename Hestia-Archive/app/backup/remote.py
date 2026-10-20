"""Google Drive through Hecate (``/api/gateway/drive/*``), only via Hub — the folder is ``.hestia/backup``."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import requests

FOLDER = "backup"
CHUNK = 2 * 1024 * 1024          # multiple of 256 KiB (Drive resumable rule)


class RemoteError(RuntimeError):
    def __init__(self, message: str, code: str = "drive_error", status: int = 0):
        super().__init__(message)
        self.code, self.status = code, status


class DriveRemote:
    def __init__(self, hub_api_url: str, session: Any = None):
        self.base = hub_api_url.rstrip("/")
        self.http = session or requests.Session()

    def _call(self, method: str, path: str, *, body: Any = None, query: dict | None = None, timeout: float = 60):
        try:
            resp = self.http.post(f"{self.base}/route/hecate/api/gateway/drive/{path}",
                                  json={"method": method, "headers": {}, "query": query or {}, "body": body,
                                        "timeout_seconds": timeout}, timeout=timeout + 5)
            resp.raise_for_status()
            routed = resp.json() or {}
        except Exception as exc:
            raise RemoteError(f"Google Drive non raggiungibile ({exc})", "unreachable") from exc
        status, payload = int(routed.get("status_code", 500)), routed.get("payload")
        if status >= 400:
            detail = (payload or {}).get("detail") if isinstance(payload, dict) else None
            detail = detail if isinstance(detail, dict) else {}
            raise RemoteError(detail.get("message") or f"Google Drive ha risposto {status}",
                              detail.get("error") or "drive_error", status)
        return payload or {}

    def status(self) -> dict:
        try:
            return self._call("GET", "status", timeout=20)
        except RemoteError as exc:
            return {"connected": False, "scope_ok": False, "error": str(exc), "code": exc.code}

    def list(self) -> list[dict]:
        return list(self._call("GET", "files", query={"folder": FOLDER}).get("files") or [])

    def upload(self, path: Path, name: str, app_properties: dict) -> dict:
        size = path.stat().st_size
        upload_id = self._call("POST", "upload/start", body={
            "folder": FOLDER, "name": name, "size": size, "mime": "application/octet-stream",
            "app_properties": app_properties})["upload_id"]
        offset, out = 0, {}
        with open(path, "rb") as f:
            while offset < size:
                block = f.read(CHUNK)
                out = self._call("POST", f"upload/{upload_id}/chunk", timeout=120,
                                 body={"offset": offset, "data_b64": base64.b64encode(block).decode("ascii")})
                offset = int(out.get("received", offset + len(block)))
        if not out.get("done") or not out.get("file"):
            raise RemoteError("caricamento non completato")
        return out["file"]

    def download(self, file_id: str, path: Path) -> int:
        offset = 0
        with open(path, "wb") as f:
            while True:
                out = self._call("GET", f"files/{file_id}/chunk", query={"offset": offset, "length": CHUNK},
                                 timeout=120)
                block = base64.b64decode(out.get("data_b64") or "")
                f.write(block)
                offset += len(block)
                if out.get("eof") or not block:
                    return offset

    def update(self, file_id: str, app_properties: dict) -> dict:
        return self._call("PATCH", f"files/{file_id}", body={"app_properties": app_properties}).get("file") or {}

    def trash(self, file_id: str) -> None:
        self._call("DELETE", f"files/{file_id}")
