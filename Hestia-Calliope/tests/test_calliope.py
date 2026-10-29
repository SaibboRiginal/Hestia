"""Calliope (Documenti): HTML → blocks, PDF/Word/Excel with themes, final check, blobs, endpoints. Markers: unit, api"""
import base64
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, Store

from app.core.parse import parse, text_of
from app.core.render import THEMES, check, render
from app.core.service import Documents, filename

pytestmark = pytest.mark.unit

HTML = ("<h1>Riepilogo</h1><p>Ciao <b>Marko</b>, il <i>mese</i> è chiuso.</p><ol><li>Affitto</li><li>Spesa</li></ol>"
        "<h2>Ottobre</h2><table><tr><th>Voce</th><th>Euro</th></tr><tr><td>Affitto</td><td>650,00</td></tr></table>")


def test_parse_blocks():
    blocks = parse(HTML)
    assert [b["type"] for b in blocks] == ["h", "p", "list", "h", "table"]
    assert blocks[1]["runs"][1] == ("Marko", True, False) and blocks[2]["ordered"] is True
    assert "650,00" in text_of(blocks)
    assert [b["type"] for b in parse("uno\n\ndue")] == ["p", "p"]


@pytest.mark.parametrize("fmt", ["pdf", "docx", "xlsx"])
@pytest.mark.parametrize("theme", list(THEMES))
def test_every_format_and_theme_passes_the_check(fmt, theme):
    data = render(fmt, parse(HTML), "Spese di ottobre", theme)
    verdict = check(fmt, data, "Spese di ottobre", ["Affitto"])
    assert verdict["ok"], verdict
    assert not check(fmt, data, "Spese di ottobre", ["Bolletta inesistente"])["ok"]


def test_create_keeps_blob_and_record():
    hub = FakeArchive()
    docs = Documents(Store(hub, "office-store", min_refresh_seconds=0), hub)
    out = docs.create("Lettera al condominio", "<p>Gentile amministratore,</p><p>scrivo per...</p>", "docx",
                      must_contain=["amministratore"])
    assert out["created"] and out["name"] == "Lettera-al-condominio.docx" and hub.blobs
    d, data = docs.file(out["id"])
    assert data.startswith(b"PK") and docs.list()[0]["title"] == "Lettera al condominio"
    bad = docs.create("Nota", "<p>testo</p>", "pdf", must_contain=["non c'è"])
    assert bad["created"] is False and "non c'è" in bad["error"]
    with pytest.raises(Invalid):
        docs.create("Nota", "", "pdf")
    docs.delete(out["id"])
    assert not hub.blobs and filename("Ciao/ mondo!", "pdf") == "Ciao-mondo.pdf"


@pytest.mark.api
def test_endpoints_and_tool(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub = FakeArchive()
    monkeypatch.setattr(main, "docs", Documents(Store(hub, "office-store", min_refresh_seconds=0), hub))
    c = TestClient(main.app)
    out = c.post("/api/office/tools/crea", json={"title": "Tabella", "html": HTML, "format": "xlsx"}).json()
    assert out["created"] and out["display"]["files"][0]["mime"].endswith("sheet")
    r = c.get(f"/api/office/{out['id']}/file")
    assert r.status_code == 200 and r.content.startswith(b"PK")
    assert c.get("/api/office").json()["items"][0]["format"] == "xlsx"
    assert base64.b64decode(hub.blobs[out["display"]["files"][0]["blob_id"]]["data_b64"]) == r.content
