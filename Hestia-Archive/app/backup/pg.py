"""Postgres tools for the backup: one-snapshot dump with row counts, restore into a scratch database, swap.

Archive is the only DB owner (it connects as the stack's Postgres superuser), so it may create, rename and drop
databases. ``pg_dump``/``pg_restore`` come from the image's ``postgresql-client`` packages; the major version
matching the server is preferred (``/usr/lib/postgresql/<major>/bin``), else the newest installed.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger("hestia_archive.backup")

PG_LIB = Path(os.getenv("ARCHIVE_PG_BIN_ROOT", "/usr/lib/postgresql"))


class PgError(RuntimeError):
    pass


class Pg:
    def __init__(self, database_url: str):
        u = urlparse(database_url)
        if not u.scheme.startswith("postgres"):
            raise PgError("backup needs Postgres")
        self.host, self.port = u.hostname or "localhost", int(u.port or 5432)
        self.user, self.password = unquote(u.username or ""), unquote(u.password or "")
        self.dbname = (u.path or "/").lstrip("/") or "postgres"

    # ── connections ─────────────────────────────────────────────────────────
    def connect(self, dbname: str | None = None, *, autocommit: bool = False):
        import psycopg2
        conn = psycopg2.connect(host=self.host, port=self.port, user=self.user, password=self.password,
                                dbname=dbname or self.dbname, connect_timeout=10)
        conn.autocommit = autocommit
        return conn

    @contextmanager
    def admin(self):
        """Autocommit connection to the maintenance database (CREATE/DROP/ALTER DATABASE)."""
        conn = self.connect("postgres", autocommit=True)
        try:
            yield conn.cursor()
        finally:
            conn.close()

    def env(self) -> dict:
        return {**os.environ, "PGPASSWORD": self.password, "PGHOST": self.host, "PGPORT": str(self.port),
                "PGUSER": self.user, "PGCONNECT_TIMEOUT": "10"}

    # ── versions and binaries ───────────────────────────────────────────────
    def server_major(self) -> int:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute("SHOW server_version_num")
            return int(cur.fetchone()[0]) // 10000
        finally:
            conn.close()

    def server_version(self) -> str:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute("SHOW server_version")
            return str(cur.fetchone()[0])
        finally:
            conn.close()

    def binary(self, name: str, major: int | None = None) -> str:
        installed = sorted((int(p.name) for p in PG_LIB.glob("*") if p.name.isdigit() and (p / "bin" / name).exists()),
                           reverse=True) if PG_LIB.is_dir() else []
        if major in installed:
            return str(PG_LIB / str(major) / "bin" / name)
        newer = [m for m in installed if major is None or m >= major]
        if newer:
            return str(PG_LIB / str(min(newer) if major else newer[0]) / "bin" / name)
        found = shutil.which(name)
        if not found:
            raise PgError(f"{name} not installed in the Archive image")
        return found

    def _run(self, args: list[str], step: str) -> None:
        proc = subprocess.run(args, env=self.env(), capture_output=True, text=True)
        if proc.returncode != 0:
            raise PgError(f"{step}: {(proc.stderr or proc.stdout or '').strip()[-600:]}")

    # ── tables ──────────────────────────────────────────────────────────────
    @staticmethod
    def _tables(cur) -> list[str]:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                    "AND table_type = 'BASE TABLE' ORDER BY table_name")
        return [r[0] for r in cur.fetchall()]

    @classmethod
    def _counts(cls, cur) -> dict[str, int]:
        out = {}
        for t in cls._tables(cur):
            cur.execute(f'SELECT count(*) FROM public."{t}"')
            out[t] = int(cur.fetchone()[0])
        return out

    def counts(self, dbname: str | None = None) -> dict[str, int]:
        conn = self.connect(dbname)
        try:
            return self._counts(conn.cursor())
        finally:
            conn.close()

    # ── dump / restore ──────────────────────────────────────────────────────
    def dump(self, path: Path) -> dict[str, int]:
        """``pg_dump -Fc`` of the live database; row counts read from the very same snapshot."""
        major = self.server_major()
        conn = self.connect()
        try:
            conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
            cur = conn.cursor()
            cur.execute("SELECT pg_export_snapshot()")
            snapshot = cur.fetchone()[0]
            counts = self._counts(cur)
            self._run([self.binary("pg_dump", major), "-Fc", "-Z", "6", "--snapshot", snapshot, "-d", self.dbname,
                       "-f", str(path)], "pg_dump")
            return counts
        finally:
            conn.rollback()
            conn.close()

    def exists(self, dbname: str) -> bool:
        with self.admin() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            return cur.fetchone() is not None

    def drop(self, dbname: str) -> None:
        _check_name(dbname)
        if dbname == self.dbname:
            raise PgError("refusing to drop the live database")
        with self.admin() as cur:
            self._terminate(cur, dbname)
            cur.execute(f'DROP DATABASE IF EXISTS "{dbname}"')

    def restore_into(self, dbname: str, dump_path: Path) -> None:
        """Fresh ``dbname`` (dropped first if left over) filled from the dump; any error → PgError."""
        self.drop(dbname)
        with self.admin() as cur:
            cur.execute(f'CREATE DATABASE "{dbname}"')
        self._run([self.binary("pg_restore", self.server_major()), "--no-owner", "--no-privileges",
                   "--exit-on-error", "-d", dbname, str(dump_path)], "pg_restore")

    @staticmethod
    def _terminate(cur, dbname: str) -> None:
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                    "AND pid <> pg_backend_pid()", (dbname,))

    def swap(self, live: str, incoming: str, keep_as: str) -> None:
        """``live`` → ``keep_as`` (an old ``keep_as`` is dropped), ``incoming`` → ``live``. On a failure of the
        second rename the first is undone, so the live name always exists."""
        for n in (live, incoming, keep_as):
            _check_name(n)
        with self.admin() as cur:
            for n in (live, incoming, keep_as):
                self._terminate(cur, n)
            cur.execute(f'DROP DATABASE IF EXISTS "{keep_as}"')
            cur.execute(f'ALTER DATABASE "{live}" RENAME TO "{keep_as}"')
            try:
                cur.execute(f'ALTER DATABASE "{incoming}" RENAME TO "{live}"')
            except Exception:
                cur.execute(f'ALTER DATABASE "{keep_as}" RENAME TO "{live}"')
                raise

    def exchange(self, live: str, other: str) -> None:
        """Swap the names of two databases (undo of a rollback; doing it twice is a no-op)."""
        tmp = f"{live}_swap_tmp"
        for n in (live, other, tmp):
            _check_name(n)
        with self.admin() as cur:
            for n in (live, other):
                self._terminate(cur, n)
            cur.execute(f'DROP DATABASE IF EXISTS "{tmp}"')
            cur.execute(f'ALTER DATABASE "{live}" RENAME TO "{tmp}"')
            try:
                cur.execute(f'ALTER DATABASE "{other}" RENAME TO "{live}"')
            except Exception:
                cur.execute(f'ALTER DATABASE "{tmp}" RENAME TO "{live}"')
                raise
            cur.execute(f'ALTER DATABASE "{tmp}" RENAME TO "{other}"')


_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise PgError(f"bad database name {name!r}")
