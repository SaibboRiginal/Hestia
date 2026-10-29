"""Phone notifications (Cindy 32, feed phone.notification from Hecate): bank app notification → transaction to
review, once. Markers: unit"""
import pytest

from app.core import phone

from .test_plutus import _clean_settings, pl  # noqa: F401 — fixtures

pytestmark = pytest.mark.unit


def test_parse_bank_notifications():
    out = phone.parse("Banca", "Pagamento con carta", "Pagamento di 12,50 € presso ESSELUNGA il 29/10")
    assert out == {"kind": "expense", "amount": 12.5, "currency": "EUR", "merchant": "ESSELUNGA"}
    assert phone.parse("Satispay", "Hai ricevuto 20 €", "da Luca")["kind"] == "income"
    assert phone.parse("Chat", "Luca", "ci vediamo alle 8") is None
    assert phone.parse("Banca", "Saldo", "Il saldo è 1.234,00 €") is None


def test_notification_becomes_one_transaction(pl):  # noqa: F811
    item = {"app": "Banca", "title": "Pagamento con carta", "text": "Pagamento di 12,50 € presso ESSELUNGA",
            "at": "2026-10-29T18:30:00+01:00"}
    first = pl.process_phone(item)
    assert first["status"] == "added" and first["amount"] == -12.5
    tx = pl.store.data("tx", first["tx_id"])
    assert tx["status"] == "to_review" and tx["source"] == "phone" and tx["date"] == "2026-10-29"
    assert pl.process_phone(item)["status"] == "duplicate"
    assert pl.process_phone({"app": "Chat", "text": "ciao"})["status"] == "ignored"
