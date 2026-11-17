"""GET /api/settings/i18n: the catalog clients use for their fixed texts (dossier docs/work/2026-11-14-backend-inglese).

Source texts are English: Italian gets the it catalog, English (and a language without a catalog) gets an empty map."""
import pytest


@pytest.mark.api
def test_i18n_catalog_follows_the_language(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main.themis, "owner_language", lambda: "it")
    c = TestClient(main.app)
    it = c.get("/api/settings/i18n").json()
    assert it["language"] == "it" and it["messages"]["Cancel"] == "Annulla"
    en = c.get("/api/settings/i18n", params={"lang": "en"}).json()
    assert en == {"language": "en", "messages": {}, "assistant": "Hestia", "gender": "she"}
    de = c.get("/api/settings/i18n", params={"lang": "de"}).json()
    assert de["language"] == "de" and de["messages"] == {}   # a language without a catalog → the English source


@pytest.mark.api
def test_i18n_catalog_carries_the_assistant_name_never_the_owner(monkeypatch):
    """«Ask {assistant}» in the WebUI says the chosen name (docs/work/2026-11-16-nome-ovunque)."""
    from fastapi.testclient import TestClient
    from app import main
    from hestia_common import i18n
    values = {"themis.personal.assistant_name": "Leo", "themis.personal.assistant_gender": "he",
              "themis.personal.owner_name": "Marco", "themis.personal.language": "it"}
    monkeypatch.setattr(i18n, "_reader", values.get)
    out = TestClient(main.app).get("/api/settings/i18n", params={"lang": "it"}).json()
    assert out["assistant"] == "Leo" and out["gender"] == "he"
    assert "Marco" not in str(out)
