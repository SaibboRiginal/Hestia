from app.main import detect_gateway_providers


def _providers_index(rows: list[dict]) -> dict[str, dict]:
    return {str(row.get("provider")): row for row in rows}


def test_detect_gateway_providers_empty(monkeypatch):
    keys = [
        "GOOGLE_TOKEN_JSON",
        "GOOGLE_CREDENTIALS_JSON",
        "HECATE_KEY_GOOGLE_CLIENT_ID",
        "HECATE_KEY_GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "HECATE_KEY_OUTLOOK_CLIENT_ID",
        "HECATE_KEY_OUTLOOK_CLIENT_SECRET",
        "HECATE_KEY_OUTLOOK_TENANT",
        "OUTLOOK_REFRESH_TOKEN",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    providers = detect_gateway_providers()
    assert providers == []


def test_detect_gateway_providers_configured_google(monkeypatch):
    monkeypatch.setenv("HECATE_KEY_GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("HECATE_KEY_GOOGLE_CLIENT_SECRET", "y")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "z")

    providers = _providers_index(detect_gateway_providers())
    assert "google" in providers
    assert providers["google"]["configured"] is True
    assert providers["google"]["auth_status"] == "configured"


def test_detect_gateway_providers_configured_google_token_json(monkeypatch):
    monkeypatch.setenv(
        "GOOGLE_TOKEN_JSON",
        '{"token":"x","refresh_token":"y","client_id":"z","client_secret":"w"}',
    )

    providers = _providers_index(detect_gateway_providers())
    assert "google" in providers
    assert providers["google"]["configured"] is True
    assert providers["google"]["auth_status"] == "configured"
