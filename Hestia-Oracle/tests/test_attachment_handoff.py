"""Chat attachments handed to the module that declares them (generic: Oracle knows no domain).

Markers: unit
"""
import json
from unittest.mock import MagicMock

import pytest

from core.document.analyser import DocumentAnalyser
from core.document.handoff import AttachmentHandoff

pytestmark = pytest.mark.unit

_SERVICES = {"services": [
    {"name": "plutus", "capabilities": {"attachment_handlers": [
        {"mime": ["application/pdf"], "match": ["lista movimenti", "saldo finale", "iban"], "min_hits": 2,
         "path": "/api/finance/attachments", "label": "Estratto conto"}]}},
    {"name": "scout", "capabilities": {}}]}


def _hub(handled=True):
    hub = MagicMock()
    hub.hub_get.return_value = _SERVICES
    hub.post.return_value = {"status_code": 200, "payload": {"blob_id": "abc"}}
    hub.route_to_service.return_value = (True, {"handled": handled, "text": "Li registro? (import_id imp_1)",
                                                "import_id": "imp_1"})
    return hub


def test_matches_by_text_hits_or_message_word():
    h = AttachmentHandoff(_hub()).handlers()[0]
    assert h["service"] == "plutus"
    assert AttachmentHandoff.matches(h, "application/pdf", "Lista movimenti ... Saldo finale 10,00", "")
    assert not AttachmentHandoff.matches(h, "application/pdf", "solo lista movimenti", "")
    assert AttachmentHandoff.matches(h, "application/pdf", "", "ecco la lista movimenti di ottobre")
    assert not AttachmentHandoff.matches(h, "image/png", "lista movimenti saldo finale", "")


def test_run_stores_blob_and_hands_id():
    hub = _hub()
    ho = AttachmentHandoff(hub)
    out = ho.run(ho.handlers()[0], file_bytes=b"%PDF-1.4", mime="application/pdf", filename="m.pdf",
                 message="", session_id="s1")
    assert out["import_id"] == "imp_1" and out["blob_id"] == "abc"
    assert hub.post.call_args[0][1]["owner_module"] == "chat"
    svc, path, method = hub.route_to_service.call_args[0]
    assert (svc, path, method) == ("plutus", "/api/finance/attachments", "POST")
    assert hub.route_to_service.call_args[1]["body"]["blob_id"] == "abc"


def _analyser(hub):
    analyst = MagicMock()
    analyst.ask_with_attachment.return_value = "analisi normale"
    return DocumentAnalyser(hub_client=hub, archiver=MagicMock(), analyst=analyst,
                            style_contract_fn=lambda: ""), analyst


def _final(lines):
    return [json.loads(l) for chunk in lines for l in chunk.splitlines() if l.strip()][-1]


def test_analyser_uses_handoff(monkeypatch):
    monkeypatch.setattr("core.document.analyser.extract_text", lambda b, m: "Lista movimenti\nSaldo finale 1,00")
    an, analyst = _analyser(_hub())
    final = _final(an.analyse(b"%PDF-1.4", "application/pdf", "", "s1", filename="m.pdf"))
    assert "import_id imp_1" in json.dumps(final) and not analyst.ask_with_attachment.called


def test_analyser_falls_back_when_module_declines(monkeypatch):
    monkeypatch.setattr("core.document.analyser.extract_text", lambda b, m: "Lista movimenti\nSaldo finale 1,00")
    an, analyst = _analyser(_hub(handled=False))
    final = _final(an.analyse(b"%PDF-1.4", "application/pdf", "", "s1", filename="m.pdf"))
    assert "analisi normale" in json.dumps(final) and analyst.ask_with_attachment.called
