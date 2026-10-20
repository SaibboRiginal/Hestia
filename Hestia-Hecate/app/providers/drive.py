"""Google Drive files, confined to Hestia's own ``.hestia`` folder (scope ``drive.file``).

SPEC docs/work/2026-10-20-backup-drive §3.1. With ``drive.file`` Google shows Hestia only the files it created:
the rest of Marko's Drive stays invisible. Callers name a subfolder (``backup``, ``export``…) under the
``.hestia`` root; both are created on first use and found again by their ``appProperties``.

Big files travel in chunks so the Hub envelope stays small: uploads use Drive's resumable sessions (one per
``upload_id``, chunks of a multiple of 256 KiB except the last), downloads use HTTP ranges.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger("hestia_hecate.drive")

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_NAME = ".hestia"
FIELDS = "id,name,size,createdTime,modifiedTime,mimeType,appProperties"
UPLOAD_TTL = 6 * 3600
_FOLDER_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,40}$")


class DriveError(Exception):
    def __init__(self, message: str, status: int = 502, code: str = "drive_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def _view(f: dict) -> dict:
    return {"id": f.get("id"), "name": f.get("name"), "size": int(f.get("size") or 0),
            "created_at": f.get("createdTime"), "modified_at": f.get("modifiedTime"),
            "app_properties": f.get("appProperties") or {}}


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveFiles:
    """Thin Drive v3 client. ``session_factory`` returns an authorized ``requests``-like session or raises
    ``DriveError`` (no token, missing scope)."""

    def __init__(self, session_factory: Callable[[], Any]):
        self._session_factory = session_factory
        self._folders: dict[str, str] = {}
        self._uploads: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── plumbing ────────────────────────────────────────────────────────────
    def _session(self):
        return self._session_factory()

    def _check(self, resp, what: str):
        if resp.status_code in (401, 403):
            text = getattr(resp, "text", "")[:300]
            if "insufficient" in text.lower() or "scope" in text.lower():
                raise DriveError("Google Drive non autorizzato: ricollega Google", 409, "drive_scope_missing")
            if "accessNotConfigured" in text or "has not been used" in text or "disabled" in text:
                raise DriveError("Google Drive API non abilitata nel progetto Google", 409, "drive_api_disabled")
            raise DriveError(f"{what}: accesso negato ({resp.status_code})", 409, "drive_forbidden")
        if resp.status_code == 404:
            raise DriveError(f"{what}: non trovato", 404, "not_found")
        if resp.status_code >= 400:
            raise DriveError(f"{what}: Google ha risposto {resp.status_code} {getattr(resp, 'text', '')[:200]}")
        return resp

    def reset(self) -> None:
        """Forget cached folder ids (new token / account)."""
        with self._lock:
            self._folders.clear()

    # ── folders ─────────────────────────────────────────────────────────────
    def _find_or_create(self, name: str, marker: str, parent: str | None) -> str:
        s = self._session()
        q = (f"mimeType='{FOLDER_MIME}' and trashed=false and "
             f"appProperties has {{ key='hestia' and value='{_q(marker)}' }}")
        if parent:
            q += f" and '{parent}' in parents"
        found = self._check(s.get(API, params={"q": q, "fields": "files(id,name)", "spaces": "drive"}),
                            "cartella").json().get("files") or []
        if found:
            return found[0]["id"]
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME, "appProperties": {"hestia": marker}}
        if parent:
            body["parents"] = [parent]
        created = self._check(s.post(API, json=body, params={"fields": "id"}), "crea cartella").json()
        logger.info("event=drive_folder_created name=%s", name)
        return created["id"]

    def folder_id(self, folder: str) -> str:
        folder = (folder or "").strip().lower()
        if not _FOLDER_RE.match(folder):
            raise DriveError(f"cartella non valida: {folder!r}", 422, "bad_folder")
        with self._lock:
            if folder in self._folders:
                return self._folders[folder]
            root = self._folders.get("") or self._find_or_create(ROOT_NAME, "root", None)
            self._folders[""] = root
            fid = self._find_or_create(folder, f"folder:{folder}", root)
            self._folders[folder] = fid
            return fid

    # ── files ───────────────────────────────────────────────────────────────
    def status(self) -> dict:
        try:
            self.folder_id("backup")
            return {"connected": True, "scope_ok": True, "error": ""}
        except DriveError as exc:
            return {"connected": exc.code not in ("no_token",), "scope_ok": exc.code != "drive_scope_missing",
                    "error": str(exc), "code": exc.code}

    def list(self, folder: str) -> list[dict]:
        fid = self.folder_id(folder)
        s = self._session()
        out, token = [], None
        while True:
            params = {"q": f"'{fid}' in parents and trashed=false", "fields": f"nextPageToken,files({FIELDS})",
                      "orderBy": "createdTime desc", "pageSize": 200}
            if token:
                params["pageToken"] = token
            data = self._check(s.get(API, params=params), "elenco").json()
            out += [_view(f) for f in data.get("files") or []]
            token = data.get("nextPageToken")
            if not token:
                return out

    def get(self, file_id: str) -> dict:
        return _view(self._check(self._session().get(f"{API}/{file_id}", params={"fields": FIELDS}), "file").json())

    def update(self, file_id: str, app_properties: dict) -> dict:
        body = {"appProperties": {str(k): (None if v is None else str(v)) for k, v in (app_properties or {}).items()}}
        resp = self._session().patch(f"{API}/{file_id}", json=body, params={"fields": FIELDS})
        return _view(self._check(resp, "aggiorna file").json())

    def trash(self, file_id: str) -> None:
        self._check(self._session().patch(f"{API}/{file_id}", json={"trashed": True}, params={"fields": "id"}),
                    "cestina file")
        logger.info("event=drive_delete file=%s", file_id)

    def read(self, file_id: str, offset: int, length: int) -> tuple[bytes, int]:
        """Bytes ``[offset, offset+length)`` and the file size."""
        meta = self.get(file_id)
        size = meta["size"]
        if offset >= size:
            return b"", size
        end = min(size, offset + max(1, int(length))) - 1
        resp = self._session().get(f"{API}/{file_id}", params={"alt": "media"},
                                   headers={"Range": f"bytes={offset}-{end}"})
        data = self._check(resp, "scarica file").content
        logger.info("event=drive_download file=%s offset=%d bytes=%d", file_id, offset, len(data))
        return data, size

    # ── resumable upload ────────────────────────────────────────────────────
    def upload_start(self, folder: str, name: str, size: int, mime: str = "application/octet-stream",
                     app_properties: dict | None = None) -> str:
        if size <= 0:
            raise DriveError("file vuoto", 422, "empty")
        fid = self.folder_id(folder)
        meta = {"name": name, "parents": [fid], "mimeType": mime,
                "appProperties": {str(k): str(v) for k, v in (app_properties or {}).items()}}
        resp = self._session().post(UPLOAD, params={"uploadType": "resumable", "fields": FIELDS}, json=meta,
                                    headers={"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)})
        url = self._check(resp, "avvia caricamento").headers.get("Location")
        if not url:
            raise DriveError("Google non ha dato l'indirizzo di caricamento")
        upload_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._uploads.items() if now - v["at"] > UPLOAD_TTL]:
                self._uploads.pop(k, None)
            self._uploads[upload_id] = {"url": url, "size": int(size), "received": 0, "at": now, "name": name,
                                        "folder": folder}
        logger.info("event=drive_upload_start folder=%s name=%s bytes=%d", folder, name, size)
        return upload_id

    def upload_chunk(self, upload_id: str, offset: int, data: bytes) -> dict:
        with self._lock:
            up = self._uploads.get(upload_id)
        if not up:
            raise DriveError("caricamento sconosciuto o scaduto", 404, "unknown_upload")
        if offset != up["received"]:
            raise DriveError(f"posizione attesa {up['received']}, ricevuta {offset}", 409, "bad_offset")
        last = offset + len(data) >= up["size"]
        if not data or (not last and len(data) % (256 * 1024)):
            raise DriveError("i pezzi devono essere multipli di 256 KiB (tranne l'ultimo)", 422, "bad_chunk")
        end = offset + len(data) - 1
        resp = self._session().put(up["url"], data=data, headers={
            "Content-Length": str(len(data)), "Content-Range": f"bytes {offset}-{end}/{up['size']}"})
        if resp.status_code == 308:
            up["received"] = end + 1
            return {"received": up["received"], "done": False}
        f = self._check(resp, "carica pezzo").json()
        with self._lock:
            self._uploads.pop(upload_id, None)
        logger.info("event=drive_upload folder=%s name=%s bytes=%d", up["folder"], up["name"], up["size"])
        return {"received": up["size"], "done": True, "file": _view(f)}


def google_session_factory():
    """Authorized session from Hecate's Google token; ``DriveError`` when missing or without ``drive.file``."""
    from providers.google import load_google_credentials
    creds, error = load_google_credentials()
    if creds is None:
        raise DriveError(error or "Google non collegato", 409, "no_token")
    scopes = set(getattr(creds, "scopes", None) or getattr(creds, "granted_scopes", None) or [])
    if scopes and DRIVE_FILE_SCOPE not in scopes and "https://www.googleapis.com/auth/drive" not in scopes:
        raise DriveError("Google Drive non autorizzato: ricollega Google", 409, "drive_scope_missing")
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(creds)


drive_files = DriveFiles(google_session_factory)
