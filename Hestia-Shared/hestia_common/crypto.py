"""Passphrase encryption for files that leave Hestia (Drive backups, exported ``.hestia`` files).

One format for every caller (SPEC docs/work/2026-10-20-backup-drive §3.2): scrypt derives a key from the
passphrase, AES-256-GCM seals the data in chunks (streaming: a backup of hundreds of MB never sits in memory).

    from hestia_common.crypto import encrypt_stream, decrypt_stream, encrypt_bytes, decrypt_bytes

    with open("dump", "rb") as src, open("dump.enc", "wb") as dst:
        encrypt_stream(src, dst, passphrase)
    data = decrypt_bytes(blob, passphrase)          # raises DecryptError on a wrong passphrase or a damaged file

Layout: ``HESTIA-ENC1\\n`` · salt(16) · log2 N(1) · r(1) · p(1) · chunk size(4) · nonce prefix(8), then chunks
``length(4) · ciphertext+tag``. Nonce = prefix + chunk counter; the authenticated data is the header plus a
"last chunk" flag, so a reordered, truncated or extended file fails to open.
"""
from __future__ import annotations

import io
import os
import struct
from typing import BinaryIO

MAGIC = b"HESTIA-ENC1\n"
CHUNK = 1024 * 1024
_HEADER = struct.Struct(">16sBBBI8s")
_LEN = struct.Struct(">I")
_TAG = 16


class DecryptError(ValueError):
    """Wrong passphrase, or the file is damaged, truncated or not a Hestia encrypted file."""


def _aes(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _derive(passphrase: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if not passphrase:
        raise ValueError("empty passphrase")
    return Scrypt(salt=salt, length=32, n=1 << log_n, r=r, p=p).derive(passphrase.encode("utf-8"))


def is_encrypted(head: bytes) -> bool:
    return head.startswith(MAGIC)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str, *, chunk: int = CHUNK, log_n: int = 16,
                   r: int = 8, p: int = 1) -> int:
    """Encrypt ``src`` into ``dst``; returns the bytes written."""
    salt, prefix = os.urandom(16), os.urandom(8)
    header = MAGIC + _HEADER.pack(salt, log_n, r, p, chunk, prefix)
    aes = _aes(_derive(passphrase, salt, log_n, r, p))
    dst.write(header)
    written, counter = len(header), 0
    block = src.read(chunk)
    while True:
        nxt = src.read(chunk) if len(block) == chunk else b""
        last = not nxt
        sealed = aes.encrypt(prefix + struct.pack(">I", counter), block, header + (b"\x01" if last else b"\x00"))
        dst.write(_LEN.pack(len(sealed)) + sealed)
        written += _LEN.size + len(sealed)
        counter += 1
        if last:
            return written
        block = nxt


def _read_exact(src: BinaryIO, n: int) -> bytes:
    data = src.read(n)
    if len(data) != n:
        raise DecryptError("file truncated")
    return data


def decrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str) -> int:
    """Decrypt ``src`` into ``dst``; returns the plaintext bytes. Raises ``DecryptError``."""
    if src.read(len(MAGIC)) != MAGIC:
        raise DecryptError("not a Hestia encrypted file")
    raw = _read_exact(src, _HEADER.size)
    salt, log_n, r, p, chunk, prefix = _HEADER.unpack(raw)
    if not (10 <= log_n <= 22 and chunk > 0):
        raise DecryptError("bad header")
    header = MAGIC + raw
    aes = _aes(_derive(passphrase, salt, log_n, r, p))
    from cryptography.exceptions import InvalidTag
    out, counter = 0, 0
    pending = src.read(_LEN.size)
    while True:
        if len(pending) != _LEN.size:
            raise DecryptError("file truncated")
        size = _LEN.unpack(pending)[0]
        if size < _TAG or size > chunk + _TAG:
            raise DecryptError("bad chunk")
        sealed = _read_exact(src, size)
        pending = src.read(_LEN.size)
        last = not pending
        try:
            block = aes.decrypt(prefix + struct.pack(">I", counter), sealed, header + (b"\x01" if last else b"\x00"))
        except InvalidTag:
            raise DecryptError("wrong passphrase or damaged file") from None
        dst.write(block)
        out += len(block)
        counter += 1
        if last:
            return out


def encrypt_bytes(data: bytes, passphrase: str, **kw) -> bytes:
    dst = io.BytesIO()
    encrypt_stream(io.BytesIO(data), dst, passphrase, **kw)
    return dst.getvalue()


def decrypt_bytes(data: bytes, passphrase: str) -> bytes:
    dst = io.BytesIO()
    decrypt_stream(io.BytesIO(data), dst, passphrase)
    return dst.getvalue()
