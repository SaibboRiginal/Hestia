"""Backup against a real Postgres (pg_dump/pg_restore, scratch database, rename swap, undo).

Needs ``ARCHIVE_TEST_PG_URL`` (a Postgres with pgvector the test may fill and rename, e.g. the cloud bench's
``postgresql://hestia_admin:pw@localhost:55432/hestia_memory``) and the client tools; skipped otherwise.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

_ARCHIVE_ROOT = Path(__file__).parents[1]
if str(_ARCHIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ARCHIVE_ROOT))

URL = os.getenv("ARCHIVE_TEST_PG_URL", "")
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not URL or not shutil.which("pg_dump"), reason="needs ARCHIVE_TEST_PG_URL + pg_dump")]


def test_backup_verify_restore_undo_on_postgres(tmp_path):
    from sqlalchemy import create_engine, text

    from app import schema
    from app.backup.pg import Pg
    from app.backup.service import BackupService

    from .backup_fakes import FakeRemote

    engine = create_engine(URL)
    schema.migrate(engine)

    def rows() -> int:
        with engine.connect() as c:
            return int(c.execute(text("SELECT count(*) FROM bk_probe")).scalar())

    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS bk_probe"))
        c.execute(text("CREATE TABLE bk_probe (id int, note text)"))
        c.execute(text("INSERT INTO bk_probe SELECT g, 'diario ' || g FROM generate_series(1, 3) g"))

    pg, remote, notes = Pg(URL), FakeRemote(), []
    svc = BackupService(pg=pg, remote=remote, workdir=tmp_path, passphrase=lambda: "segreta", setting=lambda k, d=None: d,
                        notify=notes.append,
                        migrate=lambda db: schema.migrate(create_engine(engine.url.set(database=db))),
                        before_swap=engine.dispose, after_swap=engine.dispose)
    svc.run()
    (fid, f), = remote.files.items()
    assert b"diario" not in remote.data[fid]
    assert svc.verify()["ok"] and not pg.exists(svc.CHECK_DB)

    with engine.begin() as c:
        c.execute(text("INSERT INTO bk_probe VALUES (4, 'dopo'), (5, 'dopo')"))
    assert rows() == 5
    svc.restore(fid)
    assert rows() == 3 and pg.exists(svc.previous)
    svc.undo()
    assert rows() == 5
    svc.undo()                                          # undo of the undo: back to the restored data
    assert rows() == 3
    pg.drop(svc.previous)
    engine.dispose()
