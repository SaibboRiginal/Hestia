"""Fakes for the backup tests: Google Drive (through Hecate) kept in memory."""
from __future__ import annotations

from pathlib import Path

from app.backup.remote import RemoteError


class FakeRemote:
    def __init__(self):
        self.files: dict[str, dict] = {}
        self.data: dict[str, bytes] = {}
        self.down: str = ""          # "" | "unreachable" | "drive_scope_missing"
        self.n = 0

    def _fail(self):
        if self.down:
            raise RemoteError("Drive giù", self.down)

    def status(self):
        return {"connected": not self.down, "scope_ok": self.down != "drive_scope_missing"}

    def list(self):
        self._fail()
        return sorted(self.files.values(), key=lambda f: f["created_at"], reverse=True)

    def upload(self, path: Path, name: str, app_properties: dict):
        self._fail()
        self.n += 1
        fid = f"d{self.n}"
        self.data[fid] = Path(path).read_bytes()
        self.files[fid] = {"id": fid, "name": name, "size": len(self.data[fid]),
                           "created_at": app_properties.get("created_at"), "app_properties": dict(app_properties)}
        return self.files[fid]

    def download(self, file_id: str, path: Path) -> int:
        self._fail()
        Path(path).write_bytes(self.data[file_id])
        return len(self.data[file_id])

    def update(self, file_id: str, app_properties: dict):
        self._fail()
        self.files[file_id]["app_properties"].update(app_properties)
        return self.files[file_id]

    def trash(self, file_id: str):
        self._fail()
        self.files.pop(file_id)
        self.data.pop(file_id)
