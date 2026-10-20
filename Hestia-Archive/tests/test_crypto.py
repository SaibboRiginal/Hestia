"""hestia_common.crypto — the one encryption format for files that leave Hestia (backup SPEC §3.2)."""
from __future__ import annotations

import io

import pytest

pytest.importorskip("cryptography")
from hestia_common.crypto import (MAGIC, DecryptError, decrypt_bytes, decrypt_stream, encrypt_bytes,  # noqa: E402
                                  encrypt_stream, is_encrypted)

pytestmark = pytest.mark.unit
FAST = {"log_n": 10}


@pytest.mark.parametrize("size", [0, 1, 1000, 4096, 4097, 3 * 4096])
def test_round_trip_any_size(size):
    data = bytes(range(256)) * (size // 256 + 1)
    data = data[:size]
    enc = encrypt_bytes(data, "parola segreta", chunk=4096, **FAST)
    assert is_encrypted(enc) and enc.startswith(MAGIC)
    assert size < 64 or data[:64] not in enc
    assert decrypt_bytes(enc, "parola segreta") == data


def test_streams():
    data = b"PGDMP" + b"x" * 50_000
    enc = io.BytesIO()
    written = encrypt_stream(io.BytesIO(data), enc, "pw", chunk=8192, **FAST)
    assert written == len(enc.getvalue())
    assert b"PGDMP" not in enc.getvalue()
    out = io.BytesIO()
    assert decrypt_stream(io.BytesIO(enc.getvalue()), out, "pw") == len(data)
    assert out.getvalue() == data


def test_wrong_passphrase():
    enc = encrypt_bytes(b"diario", "giusta", **FAST)
    with pytest.raises(DecryptError):
        decrypt_bytes(enc, "sbagliata")


def test_tampered_byte():
    enc = bytearray(encrypt_bytes(b"a" * 10_000, "pw", chunk=4096, **FAST))
    enc[-30] ^= 1
    with pytest.raises(DecryptError):
        decrypt_bytes(bytes(enc), "pw")


def test_truncated_at_chunk_boundary_is_detected():
    data = b"b" * (3 * 4096)
    enc = encrypt_bytes(data, "pw", chunk=4096, **FAST)
    header = len(MAGIC) + 31
    one_chunk = 4 + 4096 + 16
    with pytest.raises(DecryptError):
        decrypt_bytes(enc[:header + 2 * one_chunk], "pw")      # drops the last chunk exactly
    with pytest.raises(DecryptError):
        decrypt_bytes(enc[:-5], "pw")


def test_not_a_hestia_file():
    with pytest.raises(DecryptError):
        decrypt_bytes(b"PGDMP\x01\x02", "pw")


def test_same_data_encrypts_differently():
    assert encrypt_bytes(b"x", "pw", **FAST) != encrypt_bytes(b"x", "pw", **FAST)


def test_empty_passphrase_refused():
    with pytest.raises(ValueError):
        encrypt_bytes(b"x", "", **FAST)
