from app.main import detect_gateway_providers


def _providers_index(rows: list[dict]) -> dict[str, dict]:
    return {str(row.get("provider")): row for row in rows}


def test_detect_gateway_providers_empty(monkeypatch):
    keys = [
        "GOOGLE_TOKEN_JSON",
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "OUTLOOK_CLIENT_ID",
        "OUTLOOK_CLIENT_SECRET",
        "OUTLOOK_TENANT_ID",
        "OUTLOOK_REFRESH_TOKEN",
        "HECATE_ENABLE_PROVIDER_GOOGLE",
        "HECATE_ENABLE_PROVIDER_MICROSOFT",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    providers = detect_gateway_providers()
    assert providers == []


def test_detect_gateway_providers_configured_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "y")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "z")
    monkeypatch.delenv("HECATE_ENABLE_PROVIDER_GOOGLE", raising=False)

    providers = _providers_index(detect_gateway_providers())
    assert "google" in providers
    assert providers["google"]["configured"] is True
    assert providers["google"]["auth_status"] == "configured"


def test_detect_gateway_providers_configured_google_token_json(monkeypatch):
    monkeypatch.setenv(
        "GOOGLE_TOKEN_JSON",
        '{"token":"x","refresh_token":"y","client_id":"z","client_secret":"w"}',
    )
    monkeypatch.delenv("HECATE_ENABLE_PROVIDER_GOOGLE", raising=False)

    providers = _providers_index(detect_gateway_providers())
    assert "google" in providers
    assert providers["google"]["configured"] is True
    assert providers["google"]["auth_status"] == "configured"
