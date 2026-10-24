"""Reply / quote = context (docs/work/2026-10-23-telegram-da-zero §5.10)."""
from __future__ import annotations

import pytest

from core.services import quoted_context


@pytest.mark.unit
def test_instruction_names_who_wrote_it_and_keeps_it_short():
    line = quoted_context.instruction({"text": "Domani  piove\nalle 18", "from": "assistant", "at": "2026-10-24T18:30:00"})
    assert line == "RISPONDE A tuo messaggio (2026-10-24 18:30): «Domani piove alle 18». Il messaggio dell'utente si riferisce a questo."
    long = quoted_context.instruction({"text": "parola " * 400, "from": "notification"})
    assert "tua notifica" in long and len(long) < quoted_context.MAX_CHARS + 120


@pytest.mark.unit
def test_nothing_usable_leaves_instructions_alone():
    assert quoted_context.instruction(None) == "" and quoted_context.instruction({"text": "  "}) == ""
    assert quoted_context.with_instructions("tono", {"text": ""}) == "tono"


@pytest.mark.api
def test_chat_endpoint_adds_the_quote_but_saves_only_the_user_text(monkeypatch):
    import main
    seen = {}

    def fake_chat(message, session_id, **kw):
        seen.update(message=message, instructions=kw.get("client_instructions"))
        yield '{"type":"final","reply":"ok"}\n'

    monkeypatch.setattr(main.engine, "chat", fake_chat)
    monkeypatch.setattr(main, "_no_usable_model", lambda: False)
    from fastapi.testclient import TestClient
    res = TestClient(main.app).post("/api/chat", json={"message": "spostalo a giovedì", "session_id": "s1",
                                                       "client": "telegram",
                                                       "quoted": {"text": "Dentista domani 18:30", "from": "notification"}})
    assert res.status_code == 200
    assert seen["message"] == "spostalo a giovedì"
    assert "«Dentista domani 18:30»" in seen["instructions"]
