"""Google Drive files in the `.hestia` folder (backup SPEC §3.1) — against an in-memory fake of Drive v3."""
from __future__ import annotations

import base64
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.main as hecate_main
from providers.drive import API, FOLDER_MIME, UPLOAD, DriveError, DriveFiles

pytestmark = pytest.mark.unit
KIB256 = 256 * 1024


class Resp:
    def __init__(self, status=200, json=None, content=b"", headers=None, text=""):
        self.status_code, self._json, self.content = status, json, content
        self.headers, self.text = headers or {}, text or ""

    def json(self):
        return self._json


class FakeDrive:
    """Just enough of Drive v3: folders by appProperties, resumable uploads, ranges, patch, trash."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.data: dict[str, bytes] = {}
        self.sessions: dict[str, dict] = {}
        self.n = 0
        self.calls: list[tuple] = []

    def _id(self):
        self.n += 1
        return f"f{self.n}"

    def _meta(self, f):
        out = {k: f[k] for k in ("id", "name", "mimeType", "appProperties", "createdTime") if k in f}
        if f["id"] in self.data:
            out["size"] = str(len(self.data[f["id"]]))
        return out

    def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params))
        if url == API:
            q = params["q"]
            items = [f for f in self.files.values() if not f.get("trashed")]
            m = re.search(r"value='([^']+)'", q)
            if m:
                items = [f for f in items if f.get("mimeType") == FOLDER_MIME
                         and f.get("appProperties", {}).get("hestia") == m.group(1)]
            m = re.search(r"'([^']+)' in parents", q)
            if m:
                items = [f for f in items if m.group(1) in f.get("parents", [])]
            return Resp(json={"files": [self._meta(f) for f in items]})
        fid = url.rsplit("/", 1)[1]
        if fid not in self.files:
            return Resp(404, text="not found")
        if (params or {}).get("alt") == "media":
            a, b = map(int, headers["Range"].split("=")[1].split("-"))
            return Resp(206, content=self.data[fid][a:b + 1])
        return Resp(json=self._meta(self.files[fid]))

    def post(self, url, json=None, params=None, headers=None):
        self.calls.append(("POST", url, params))
        if url == API:
            fid = self._id()
            self.files[fid] = {**json, "id": fid}
            return Resp(json={"id": fid})
        if url == UPLOAD:
            sid = f"s{len(self.sessions) + 1}"
            self.sessions[sid] = {"meta": json, "size": int(headers["X-Upload-Content-Length"]), "buf": b""}
            return Resp(200, headers={"Location": f"https://upload/{sid}"})
        raise AssertionError(url)

    def put(self, url, data=None, headers=None):
        sess = self.sessions[url.rsplit("/", 1)[1]]
        a, rest = headers["Content-Range"].split(" ")[1].split("-")
        assert int(a) == len(sess["buf"])
        sess["buf"] += data
        if len(sess["buf"]) < sess["size"]:
            return Resp(308)
        fid = self._id()
        self.files[fid] = {**sess["meta"], "id": fid, "createdTime": "2026-10-20T03:30:00Z"}
        self.data[fid] = sess["buf"]
        return Resp(200, json=self._meta(self.files[fid]))

    def patch(self, url, json=None, params=None):
        fid = url.rsplit("/", 1)[1]
        f = self.files[fid]
        if "appProperties" in json:
            props = dict(f.get("appProperties") or {})
            for k, v in json["appProperties"].items():
                if v is None:
                    props.pop(k, None)
                else:
                    props[k] = v
            f["appProperties"] = props
        if json.get("trashed"):
            f["trashed"] = True
        return Resp(json=self._meta(f))


@pytest.fixture
def fake():
    return FakeDrive()


@pytest.fixture
def drive(fake):
    return DriveFiles(lambda: fake)


def _upload(drive, data: bytes, name="b.enc", chunk=KIB256):
    uid = drive.upload_start("backup", name, len(data), app_properties={"hestia": "backup", "sha256": "x"})
    off, out = 0, None
    while off < len(data):
        out = drive.upload_chunk(uid, off, data[off:off + chunk])
        off = out["received"]
    return out


def test_folders_created_once_and_reused(drive, fake):
    a = drive.folder_id("backup")
    drive.reset()
    assert drive.folder_id("backup") == a                 # found again by appProperties, not recreated
    folders = [f for f in fake.files.values() if f["mimeType"] == FOLDER_MIME]
    assert sorted(f["name"] for f in folders) == [".hestia", "backup"]
    root = next(f for f in folders if f["name"] == ".hestia")
    assert next(f for f in folders if f["name"] == "backup")["parents"] == [root["id"]]


def test_bad_folder_name(drive):
    with pytest.raises(DriveError):
        drive.folder_id("../etc")


def test_resumable_upload_list_and_ranges(drive):
    data = bytes(range(256)) * (KIB256 * 3 // 256) + b"tail"
    out = _upload(drive, data)
    assert out["done"] and out["file"]["size"] == len(data)
    assert out["file"]["app_properties"]["sha256"] == "x"
    files = drive.list("backup")
    assert [f["name"] for f in files] == ["b.enc"]
    got, off = b"", 0
    while True:
        part, size = drive.read(files[0]["id"], off, KIB256)
        if not part:
            break
        got += part
        off += len(part)
    assert got == data and size == len(data)


def test_chunk_rules(drive):
    uid = drive.upload_start("backup", "x", KIB256 * 2)
    with pytest.raises(DriveError) as e:
        drive.upload_chunk(uid, 0, b"x" * 1000)            # not a multiple of 256 KiB and not the last
    assert e.value.code == "bad_chunk"
    with pytest.raises(DriveError) as e:
        drive.upload_chunk(uid, 5, b"x" * KIB256)
    assert e.value.code == "bad_offset"
    with pytest.raises(DriveError) as e:
        drive.upload_chunk("nope", 0, b"x")
    assert e.value.code == "unknown_upload"


def test_update_and_trash(drive):
    fid = _upload(drive, b"abc")["file"]["id"]
    assert drive.update(fid, {"verify": "ok"})["app_properties"]["verify"] == "ok"
    drive.trash(fid)
    assert drive.list("backup") == []


def test_scope_error_mapped():
    class Denied:
        def get(self, *a, **k):
            return Resp(403, text="Request had insufficient authentication scopes.")
    st = DriveFiles(lambda: Denied()).status()
    assert st["scope_ok"] is False and st["code"] == "drive_scope_missing"


def test_no_token_status():
    def boom():
        raise DriveError("Google non collegato", 409, "no_token")
    st = DriveFiles(boom).status()
    assert st["connected"] is False


# ── endpoints ────────────────────────────────────────────────────────────────
@pytest.fixture
def client(drive):
    with patch.object(hecate_main, "drive_files", drive):
        yield TestClient(hecate_main.app, raise_server_exceptions=False)


def test_endpoints_round_trip(client):
    data = b"z" * (KIB256 + 10)
    r = client.post("/api/gateway/drive/upload/start", json={"folder": "backup", "name": "a.enc", "size": len(data),
                                                              "app_properties": {"hestia": "backup"}})
    uid = r.json()["upload_id"]
    r = client.post(f"/api/gateway/drive/upload/{uid}/chunk",
                    json={"offset": 0, "data_b64": base64.b64encode(data[:KIB256]).decode()})
    assert r.json()["done"] is False
    r = client.post(f"/api/gateway/drive/upload/{uid}/chunk",
                    json={"offset": KIB256, "data_b64": base64.b64encode(data[KIB256:]).decode()})
    fid = r.json()["file"]["id"]
    files = client.get("/api/gateway/drive/files", params={"folder": "backup"}).json()["files"]
    assert files[0]["id"] == fid
    r = client.get(f"/api/gateway/drive/files/{fid}/chunk", params={"offset": KIB256, "length": 100}).json()
    assert base64.b64decode(r["data_b64"]) == data[KIB256:] and r["eof"] is True
    assert client.patch(f"/api/gateway/drive/files/{fid}", json={"app_properties": {"verify": "ok"}}).status_code == 200
    assert client.delete(f"/api/gateway/drive/files/{fid}").status_code == 200
    assert client.get("/api/gateway/drive/status").json()["connected"] is True


def test_endpoint_errors(client):
    r = client.post("/api/gateway/drive/upload/nope/chunk", json={"offset": 0, "data_b64": "eA=="})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "unknown_upload"
    assert client.post("/api/gateway/drive/upload/x/chunk", json={"offset": 0, "data_b64": "%%"}).status_code == 422
    assert client.get("/api/gateway/drive/files", params={"folder": "Bad Folder"}).status_code == 422
