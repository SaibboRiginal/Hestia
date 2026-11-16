"""GET /api/settings/i18n: the catalog clients use for their fixed texts (dossier docs/work/2026-11-14-backend-inglese)."""
import pytest


@pytest.mark.api
def test_i18n_catalog_follows_the_language(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main.themis, "owner_language", lambda: "en")
    c = TestClient(main.app)
    en = c.get("/api/settings/i18n").json()
    assert en["language"] == "en" and en["messages"]["Annulla"] == "Cancel"
    it = c.get("/api/settings/i18n", params={"lang": "it"}).json()
    assert it == {"language": "it", "messages": {}}
    de = c.get("/api/settings/i18n", params={"lang": "de"}).json()
    assert de["language"] == "de" and de["messages"]["Annulla"] == "Cancel"  # a language without a catalog → English
