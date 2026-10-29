"""Esporta / importa / ripristina from Telegram (dossier docs/work/2026-10-24-tutto-brainstorm-cindy F)."""
from __future__ import annotations

import base64

import pytest

from telegram_bot import transfer_actions as ta

pytestmark = pytest.mark.unit

_BLOCK = {"module": "plutus", "format": 1, "sections": {"spese": {"records": [{"id": 1}, {"id": 2}]}}}


@pytest.fixture
def hub(monkeypatch):
    calls = []

    def route(service, path, method="GET", *, query=None, body=None, timeout=20):
        calls.append((service, path, method, body))
        if path == "api/transfer/export":
            return True, _BLOCK
        if path == "api/transfer/import":
            return True, {"sections": {"spese": {"added": 2 if body["dry_run"] else 2, "updated": 0}}}
        if path == "api/backup/list":
            return True, {"items": [{"id": "f1", "size": 3 * 1048576, "created_at": "2026-10-28T03:30:00+00:00"}]}
        if path == "api/backup/restore":
            return True, {"status": "started"}
        return False, None

    monkeypatch.setattr(ta.catalog, "route", route)
    monkeypatch.setattr(ta, "modules", lambda: {"plutus": {"label": "Spese"}})
    ta._pending.clear()
    return calls


def test_export_sends_a_hestia_file(hub):
    out = ta.esporta(1, {})
    name, data = out.document
    assert name.endswith(".hestia")
    assert ta.decode(data)["modules"]["plutus"] == _BLOCK
    assert "2 elementi" in out.html


def test_import_previews_then_applies_with_a_copy_of_before(hub):
    raw = ta.encode({"hestia": "transfer", "format": 1, "modules": {"plutus": _BLOCK}, "files": {}})
    preview = ta.importa(1, {"file": {"data_b64": base64.b64encode(raw).decode()}})
    assert [c[3]["dry_run"] for c in hub if c[1] == "api/transfer/import"] == [True]
    token = preview.actions[0].args["token"]
    done = ta.importa_conferma(1, {"token": token})
    imports = [c[3] for c in hub if c[1] == "api/transfer/import"]
    assert imports[-1]["dry_run"] is False and imports[-1]["mode"] == "merge"
    assert done.document and ta.decode(done.document[1])["modules"]["plutus"] == _BLOCK
    with pytest.raises(ta.TransferError):
        ta.importa_conferma(1, {"token": token})          # one use only


def test_import_rejects_other_files_and_other_chats(hub):
    with pytest.raises(ta.TransferError):
        ta.importa(1, {"file": {"data_b64": base64.b64encode(b"ciao").decode()}})
    raw = ta.encode({"hestia": "transfer", "format": 1, "modules": {"plutus": _BLOCK}, "files": {}})
    token = ta.importa(1, {"file": {"data_b64": base64.b64encode(raw).decode()}}).actions[0].args["token"]
    with pytest.raises(ta.TransferError):
        ta.importa_conferma(2, {"token": token})


def test_restore_lists_and_confirms(hub):
    out = ta.ripristina(1, {})
    assert out.actions[0].tool == "ripristina_conferma" and out.actions[0].args == {"file_id": "f1"}
    ta.ripristina_conferma(1, {"file_id": "f1"})
    assert ("archive", "api/backup/restore", "POST", {"file_id": "f1", "confirm": True}) in hub
