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
    assert it == {"language": "it", "messages": {}, "assistant": "Hestia", "gender": "lei"}
    de = c.get("/api/settings/i18n", params={"lang": "de"}).json()
    assert de["language"] == "de" and de["messages"]["Annulla"] == "Cancel"  # no German catalog yet → English


@pytest.mark.api
def test_i18n_catalog_carries_the_assistant_name_never_the_owner(monkeypatch):
    """«Chiedi a {assistant}» in the WebUI says the chosen name (docs/work/2026-11-16-nome-ovunque)."""
    from fastapi.testclient import TestClient
    from app import main
    from hestia_common import i18n
    values = {"themis.personal.assistant_name": "Leo", "themis.personal.assistant_gender": "lui",
              "themis.personal.owner_name": "Marco", "themis.personal.language": "it"}
    monkeypatch.setattr(i18n, "_reader", values.get)
    out = TestClient(main.app).get("/api/settings/i18n", params={"lang": "it"}).json()
    assert out["assistant"] == "Leo" and out["gender"] == "lui"
    assert "Marco" not in str(out)
