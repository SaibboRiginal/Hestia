"""Backup service (SPEC docs/work/2026-10-20-backup-drive §3.3–3.4) with a fake Postgres and a fake Drive."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("cryptography")
_ARCHIVE_ROOT = Path(__file__).parents[1]
if str(_ARCHIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE_ROOT))
sys.modules.setdefault("pgvector", MagicMock())
sys.modules.setdefault("pgvector.sqlalchemy", MagicMock())

from app.backup.container import seal  # noqa: E402
from app.backup.service import BackupFailed, BackupService, plan_retention  # noqa: E402

from .backup_fakes import FakeRemote  # noqa: E402

pytestmark = pytest.mark.unit


class FakePg:
    dbname = "hestia_memory"

    def __init__(self):
        self.counts_live = {"diary": 3, "blobs": 1}
        self.restored: dict[str, dict] = {}
        self.dbs = {"hestia_memory"}
        self.swaps: list[tuple] = []

    def server_version(self):
        return "15.4"

    def dump(self, path: Path):
        path.write_bytes(b"PGDMP" + repr(sorted(self.counts_live.items())).encode())
        return dict(self.counts_live)

    def restore_into(self, dbname, dump_path):
        data = Path(dump_path).read_bytes()
        assert data.startswith(b"PGDMP")
        self.restored[dbname] = dict(eval(data[5:].decode()))
        self.dbs.add(dbname)

    def counts(self, dbname=None):
        return dict(self.restored.get(dbname, self.counts_live))

    def drop(self, dbname):
        self.dbs.discard(dbname)
        self.restored.pop(dbname, None)

    def exists(self, dbname):
        return dbname in self.dbs

    def swap(self, live, incoming, keep_as):
        self.swaps.append(("swap", live, incoming, keep_as))
        self.dbs.discard(incoming)
        self.dbs.add(keep_as)
        self.counts_live = self.restored.pop(incoming)

    def exchange(self, live, other):
        self.swaps.append(("exchange", live, other))


@pytest.fixture
def env(tmp_path):
    pg, remote, notes, hooks = FakePg(), FakeRemote(), [], []
    cfg = {"archive.backup.keep_daily": 3, "archive.backup.keep_monthly": 3}
    svc = BackupService(pg=pg, remote=remote, workdir=tmp_path, passphrase=lambda: cfg.get("pw", "segreta"),
                        setting=lambda k, d=None: cfg.get(k, d), notify=notes.append,
                        migrate=lambda db: hooks.append(("migrate", db)), before_swap=lambda: hooks.append("before"),
                        after_swap=lambda: hooks.append("after"))
    return svc, pg, remote, notes, hooks, cfg


def test_backup_lands_encrypted_on_drive(env):
    svc, pg, remote, notes, _, _ = env
    last = svc.run()
    (fid, f), = remote.files.items()
    assert f["name"] == last["name"] and f["name"].startswith("hestia-backup-") and f["name"].endswith(".enc")
    assert not remote.data[fid].startswith(b"PGDMP") and b"PGDMP" not in remote.data[fid]
    assert f["app_properties"]["hestia"] == "backup" and len(f["app_properties"]["sha256"]) == 64
    assert svc.state()["last_backup"]["uploaded"] is True and last["rows"] == 4
    assert not list((svc.workdir / "pending").glob("*.enc")) and notes == []


def test_drive_down_keeps_local_copy_then_uploads(env):
    svc, pg, remote, notes, _, _ = env
    remote.down = "drive_scope_missing"
    svc.run()
    assert len(list((svc.workdir / "pending").glob("*.enc"))) == 1
    assert notes[-1]["title"] == "Backup in attesa" and notes[-1]["actions"]
    assert svc.state()["problem"]["code"] == "drive"
    hist = svc.history()
    assert hist["error"] and hist["pending"]
    remote.down = ""
    pg.counts_live["diary"] = 4
    (svc.workdir / "pending" / "hestia-backup-2000-01-01-0330.enc").write_bytes(b"old")
    svc.run()
    assert len(remote.files) == 3 and not list((svc.workdir / "pending").glob("*.enc"))
    assert notes[-1].get("closes") and svc.state()["problem"] is None


def test_pending_kept_at_most_three(env):
    svc, _, remote, _, _, _ = env
    remote.down = "unreachable"
    for i in range(5):
        p = svc.workdir / "pending" / f"hestia-backup-2026-10-0{i + 1}-0330.enc"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    svc.run()
    assert len(list((svc.workdir / "pending").glob("*.enc"))) == 3


def test_missing_passphrase_is_a_problem(env):
    svc, _, remote, notes, _, cfg = env
    cfg["pw"] = ""
    with pytest.raises(BackupFailed):
        svc.run()
    assert remote.files == {} and notes[-1]["level"] == "error" and "passphrase" in notes[-1]["text"]


def _f(i, iso):
    return {"id": f"f{i}", "name": f"b{i}", "created_at": iso, "app_properties": {"hestia": "backup", "created_at": iso}}


def test_retention_keeps_daily_and_first_of_each_month():
    files = [_f(1, "2026-07-01T01:30:00+00:00"), _f(2, "2026-07-15T01:30:00+00:00"),
             _f(3, "2026-08-02T01:30:00+00:00"), _f(4, "2026-09-03T01:30:00+00:00"),
             _f(5, "2026-09-20T01:30:00+00:00"), _f(6, "2026-10-18T01:30:00+00:00"),
             _f(7, "2026-10-19T01:30:00+00:00"), _f(8, "2026-10-20T01:30:00+00:00"),
             {"id": "other", "name": "x", "created_at": "2020-01-01", "app_properties": {}}]
    monthly, trash = plan_retention(files, 3, 3, ZoneInfo("Europe/Rome"))
    assert monthly == {"f6", "f4", "f3"}                 # first of Oct, Sep, Aug
    assert trash == {"f1", "f2", "f5"}                  # 'other' is not a backup: never touched
    _, trash = plan_retention(files, 1, 0, ZoneInfo("Europe/Rome"))
    assert "f8" not in trash and len(trash) == 7


def test_retention_runs_after_backup(env):
    svc, _, remote, _, _, cfg = env
    cfg["archive.backup.keep_daily"], cfg["archive.backup.keep_monthly"] = 1, 0
    for i in range(3):
        remote.files[f"o{i}"] = _f(i, f"2026-10-0{i + 1}T01:30:00+00:00") | {"id": f"o{i}"}
        remote.data[f"o{i}"] = b"x"
    svc.run()
    assert len(remote.files) == 1


def test_verify_ok_and_marked(env):
    svc, pg, remote, notes, _, _ = env
    svc.run()
    out = svc.verify()
    assert out["ok"] and out["rows"] == 4
    f = next(iter(remote.files.values()))
    assert f["app_properties"]["verify"] == "ok" and "hestia_restore_check" not in pg.dbs


def test_verify_detects_tampering(env):
    svc, pg, remote, notes, _, _ = env
    svc.run()
    fid = next(iter(remote.files))
    remote.data[fid] = remote.data[fid][:-3] + b"xyz"
    with pytest.raises(BackupFailed):
        svc.verify()
    assert remote.files[fid]["app_properties"]["verify"] == "fail"
    assert notes[-1]["title"] == "Verifica del backup fallita"
    assert svc.state()["problem"]["code"] == "verify"
    svc.run()                                            # a good backup does not hide the failed check
    assert svc.state()["problem"]["code"] == "verify"


def test_verify_wrong_passphrase(env, tmp_path):
    svc, pg, remote, notes, _, cfg = env
    dump = tmp_path / "d"
    dump.write_bytes(b"PGDMP[]")
    enc = tmp_path / "e"
    seal(dump, {"counts": {}}, enc, "altra")
    remote.upload(enc, "hestia-backup-x.enc", {"hestia": "backup", "created_at": "2026-10-20T01:00:00+00:00"})
    with pytest.raises(BackupFailed) as e:
        svc.verify()
    assert e.value.step == "decrypt"


def test_restore_swaps_and_undo(env):
    svc, pg, remote, notes, hooks, _ = env
    svc.run()
    fid = next(iter(remote.files))
    pg.counts_live = {"diary": 9, "blobs": 1}            # later changes
    info = svc.restore(fid)
    assert info["ok"] and pg.counts_live == {"diary": 3, "blobs": 1}
    assert pg.swaps[-1] == ("swap", "hestia_memory", "hestia_memory_restore", "hestia_memory_prev")
    assert hooks == [("migrate", "hestia_memory_restore"), "before", "after"]
    assert notes[-1]["title"] == "Dati ripristinati" and svc.undo_available()
    out = svc.undo()
    assert out["undone"] is True and pg.swaps[-1] == ("exchange", "hestia_memory", "hestia_memory_prev")


def test_restore_failure_changes_nothing(env):
    svc, pg, remote, notes, hooks, _ = env
    svc.run()
    fid = next(iter(remote.files))
    pg.counts = lambda dbname=None: {"diary": 0}          # restored data incomplete
    with pytest.raises(BackupFailed):
        svc.restore(fid)
    assert pg.swaps == [] and "before" not in hooks and "hestia_memory_restore" not in pg.dbs
    assert svc.state()["last_restore"]["ok"] is False


def test_one_job_at_a_time(env):
    svc, *_ = env
    import threading
    gate = threading.Event()
    svc.start("backup", gate.wait)
    from app.backup.service import JobBusy
    with pytest.raises(JobBusy):
        svc.start("verify", lambda: None)
    gate.set()
    svc.wait(5)
    assert svc.job() is None


def test_restore_from_a_file_copied_in_by_hand(env):
    svc, pg, remote, notes, hooks, _ = env
    svc.run()
    fid = next(iter(remote.files))
    svc.import_dir.mkdir(parents=True)
    (svc.import_dir / "hestia-backup-a-mano.enc").write_bytes(remote.data[fid])
    pg.counts_live = {"diary": 9, "blobs": 1}
    info = svc.restore(local="../hestia-backup-a-mano.enc")         # only the name counts, no path escapes
    assert info["ok"] and info["name"] == "hestia-backup-a-mano.enc" and pg.counts_live == {"diary": 3, "blobs": 1}
    with pytest.raises(BackupFailed):
        svc.restore(local="manca.enc")
    with pytest.raises(BackupFailed):
        svc.restore()


def test_cli_restore_needs_the_confirm_word(monkeypatch):
    from app.backup import cli

    calls = []
    monkeypatch.setattr(cli, "_call", lambda m, p, b=None: calls.append((m, p, b)) or
                        {"items": [{"id": "f1", "name": "hestia-backup-2026-10-20-033000.enc"}]})
    monkeypatch.setattr("builtins.input", lambda _prompt: "si")
    with pytest.raises(SystemExit):
        cli.main(["restore", "hestia-backup-2026-10-20-033000.enc"])
    assert all(p != "/restore" for _, p, _ in calls)
    monkeypatch.setattr(cli, "_wait", lambda: {"last_restore": {"ok": True, "name": "x"}})
    cli.main(["restore", "hestia-backup-2026-10-20-033000.enc", "--yes"])
    assert ("POST", "/restore", {"file_id": "f1", "confirm": True}) in calls
