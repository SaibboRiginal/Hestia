"""Google OAuth loopback + PKCE flow (replaces the OOB flow Google blocked in 2023)."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import app.main as hecate_main
from core import google_oauth


@pytest.fixture()
def client():
    return TestClient(hecate_main.app, raise_server_exceptions=False)


@pytest.fixture()
def google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.setattr(hecate_main, "_refresh_calendar_registry",
                        lambda: {"active": ["google"], "unavailable": {}})


def _token_response(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {
        "access_token": "ya29.access",
        "refresh_token": "1//refresh",
        "expires_in": 3599,
        "scope": "https://www.googleapis.com/auth/calendar",
        "token_type": "Bearer",
    }
    resp.text = json.dumps(resp.json.return_value)
    return resp


@pytest.mark.unit
def test_initiate_never_uses_oob(client, google_env):
    resp = client.post("/api/gateway/auth/initiate/google")
    assert resp.status_code == 200
    data = resp.json()
    qs = parse_qs(urlparse(data["auth_url"]).query)
    assert "oob" not in data["auth_url"]
    assert qs["redirect_uri"] == [google_oauth.DEFAULT_REDIRECT_URI]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["state"][0]


@pytest.mark.unit
def test_initiate_respects_custom_redirect(client, google_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8765/cb")
    data = client.post("/api/gateway/auth/initiate/google").json()
    assert parse_qs(urlparse(data["auth_url"]).query)["redirect_uri"] == ["http://127.0.0.1:8765/cb"]


@pytest.mark.unit
def test_initiate_missing_client_creds(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    resp = client.post("/api/gateway/auth/initiate/google")
    assert resp.status_code == 400
    assert "Desktop app" in resp.json()["detail"]["hint"]


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("4/0AbCd", ("4/0AbCd", None, None)),
    ("http://localhost:19003/api/gateway/auth/callback/google?state=S1&code=4/xyz&scope=a",
     ("4/xyz", "S1", None)),
    ("?code=abc&state=S2", ("abc", "S2", None)),
    ("http://localhost/?error=access_denied&state=S3", ("", "S3", "access_denied")),
    ("  'C0DE'  ", ("C0DE", None, None)),
])
def test_parse_code_input(raw, expected):
    assert google_oauth.parse_code_input(raw) == expected


@pytest.mark.unit
def test_complete_with_pasted_url_persists_token(client, google_env, monkeypatch):
    auth_url = client.post("/api/gateway/auth/initiate/google").json()["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    post = MagicMock(return_value=_token_response())
    monkeypatch.setattr(google_oauth.requests, "post", post)

    pasted = f"http://localhost:19003/api/gateway/auth/callback/google?state={state}&code=4/abc"
    resp = client.post("/api/gateway/auth/complete/google", json={"code": pasted})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "authorized"
    sent = post.call_args.kwargs["data"]
    assert sent["code"] == "4/abc"
    assert sent["grant_type"] == "authorization_code"
    assert sent["redirect_uri"] == google_oauth.DEFAULT_REDIRECT_URI
    assert len(sent["code_verifier"]) >= 43
    stored = json.loads(open(os.environ["GOOGLE_TOKEN_FILE"]).read())
    assert stored["refresh_token"] == "1//refresh"
    assert stored["expiry"].endswith("Z")
    # pending flow consumed
    assert google_oauth.pending() is None


@pytest.mark.unit
def test_complete_rejects_state_mismatch(client, google_env, monkeypatch):
    client.post("/api/gateway/auth/initiate/google")
    monkeypatch.setattr(google_oauth.requests, "post", MagicMock())
    resp = client.post("/api/gateway/auth/complete/google",
                       json={"code": "http://localhost/?state=WRONG&code=x"})
    assert resp.status_code == 400
    assert "state mismatch" in resp.json()["detail"]["error"]


@pytest.mark.unit
def test_complete_reports_google_error_with_hint(client, google_env, monkeypatch):
    client.post("/api/gateway/auth/initiate/google")
    monkeypatch.setattr(google_oauth.requests, "post", MagicMock(return_value=_token_response(
        400, {"error": "redirect_uri_mismatch", "error_description": "Bad Request"})))
    resp = client.post("/api/gateway/auth/complete/google", json={"code": "abc"})
    assert resp.status_code == 400
    assert "Desktop app" in resp.json()["detail"]["hint"]


@pytest.mark.unit
def test_complete_without_refresh_token(client, google_env, monkeypatch):
    client.post("/api/gateway/auth/initiate/google")
    monkeypatch.setattr(google_oauth.requests, "post", MagicMock(return_value=_token_response(
        200, {"access_token": "a", "expires_in": 3600})))
    resp = client.post("/api/gateway/auth/complete/google", json={"code": "abc"})
    assert resp.status_code == 400
    assert "refresh_token" in resp.json()["detail"]["error"]


@pytest.mark.unit
def test_pending_flow_survives_restart(client, google_env):
    client.post("/api/gateway/auth/initiate/google")
    # Simulate a new process: in-memory dict is gone, disk session remains.
    hecate_main._pending_auth.clear()
    assert google_oauth.pending() is not None
    assert client.get("/api/gateway/auth/poll/google").json()["status"] == "pending"


@pytest.mark.unit
def test_callback_endpoint_completes_flow(client, google_env, monkeypatch):
    auth_url = client.post("/api/gateway/auth/initiate/google").json()["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    monkeypatch.setattr(google_oauth.requests, "post", MagicMock(return_value=_token_response()))
    resp = client.get(f"/api/gateway/auth/callback/google?code=4/abc&state={state}")
    assert resp.status_code == 200
    assert "collegato" in resp.text


@pytest.mark.unit
def test_callback_endpoint_shows_error(client, google_env):
    client.post("/api/gateway/auth/initiate/google")
    resp = client.get("/api/gateway/auth/callback/google?error=access_denied")
    assert resp.status_code == 400
    assert "access_denied" in resp.text


@pytest.mark.unit
def test_token_file_counts_as_configured(monkeypatch):
    with open(os.environ["GOOGLE_TOKEN_FILE"], "w") as fh:
        json.dump({"refresh_token": "1//x"}, fh)
    providers = {p["provider"] for p in hecate_main.detect_gateway_providers()}
    assert "google" in providers


@pytest.mark.unit
def test_provider_falls_back_from_dead_file_token_to_env(monkeypatch):
    """A revoked token in the file must not hide a valid env refresh token."""
    from providers import google as gp

    with open(os.environ["GOOGLE_TOKEN_FILE"], "w") as fh:
        json.dump({"refresh_token": "dead"}, fh)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "alive")

    tried = []

    def fake_refresh(self, request):
        tried.append(self.refresh_token)
        if self.refresh_token == "dead":
            raise Exception("invalid_grant: Token has been expired or revoked.")
        self.token = "ya29.new"

    monkeypatch.setattr(gp.Credentials, "refresh", fake_refresh)
    monkeypatch.setattr(gp, "build", lambda *a, **k: object())
    provider = gp.GoogleCalendarProvider()
    assert provider.is_available()
    assert tried == ["dead", "alive"]
    stored = json.loads(open(os.environ["GOOGLE_TOKEN_FILE"]).read())
    assert stored["refresh_token"] == "alive"


@pytest.mark.unit
def test_provider_error_explains_testing_mode(monkeypatch):
    from providers import google as gp

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "dead")

    def fake_refresh(self, request):
        raise Exception("invalid_grant")

    monkeypatch.setattr(gp.Credentials, "refresh", fake_refresh)
    provider = gp.GoogleCalendarProvider()
    assert not provider.is_available()
    assert "In production" in provider._init_error
