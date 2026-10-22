"""Backup file = ``HESTIA-BACKUP1\\n`` · manifest length (8 bytes) · JSON manifest · ``pg_dump -Fc`` archive,
the whole of it encrypted with ``hestia_common.crypto`` (SPEC docs/work/2026-10-20-backup-drive §3.3).

The manifest (created_at, Postgres version, row count per table) travels inside the encrypted file, so the
verification and a rollback can compare counts without trusting anything outside it.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import BinaryIO

from hestia_common.crypto import decrypt_stream, encrypt_stream

MAGIC = b"HESTIA-BACKUP1\n"
_LEN = struct.Struct(">Q")
_MAX_MANIFEST = 4 * 1024 * 1024


class ContainerError(ValueError):
    pass


class _Concat:
    """Read-only file object over a bytes prefix followed by a file."""

    def __init__(self, prefix: bytes, tail: BinaryIO):
        self._prefix, self._tail = prefix, tail

    def read(self, n: int = -1) -> bytes:
        if self._prefix:
            if n < 0 or n >= len(self._prefix):
                head, self._prefix = self._prefix, b""
                return head + self._tail.read(-1 if n < 0 else n - len(head))
            head, self._prefix = self._prefix[:n], self._prefix[n:]
            return head
        return self._tail.read(n)


class _Split:
    """Write target that parses the header and manifest, then streams the rest into ``dump``."""

    def __init__(self, dump: BinaryIO):
        self._buf = b""
        self.manifest: dict | None = None
        self._dump = dump

    def write(self, data: bytes) -> int:
        if self.manifest is not None:
            self._dump.write(data)
            return len(data)
        self._buf += data
        head = len(MAGIC) + _LEN.size
        if len(self._buf) < head:
            return len(data)
        if not self._buf.startswith(MAGIC):
            raise ContainerError("not a Hestia backup")
        size = _LEN.unpack(self._buf[len(MAGIC):head])[0]
        if size > _MAX_MANIFEST:
            raise ContainerError("manifest too big")
        if len(self._buf) < head + size:
            return len(data)
        self.manifest = json.loads(self._buf[head:head + size].decode("utf-8"))
        self._dump.write(self._buf[head + size:])
        self._buf = b""
        return len(data)


def seal(dump_path: Path, manifest: dict, out_path: Path, passphrase: str) -> str:
    """Encrypt manifest + dump into ``out_path``; returns the sha256 of the encrypted file."""
    raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
    with open(dump_path, "rb") as dump, open(out_path, "wb") as out:
        encrypt_stream(_Concat(MAGIC + _LEN.pack(len(raw)) + raw, dump), out, passphrase)
    return sha256_file(out_path)


def unseal(enc_path: Path, dump_path: Path, passphrase: str) -> dict:
    """Decrypt ``enc_path``: the dump goes to ``dump_path``, the manifest is returned."""
    with open(enc_path, "rb") as src, open(dump_path, "wb") as dump:
        split = _Split(dump)
        decrypt_stream(src, split, passphrase)
    if split.manifest is None:
        raise ContainerError("backup without manifest")
    return split.manifest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
