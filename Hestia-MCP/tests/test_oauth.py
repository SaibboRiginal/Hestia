"""Tests — OAuth 2.1 for claude.ai / ChatGPT connectors (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B3)."""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

import core.oauth as oauth_mod
from core.oauth import OAuthServer, pkce_s256, valid_redirect
from test_external import FakeArchive, _rpc, rig  # noqa: F401  (fixture)

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
BASE = "https://hestia.example"


class FakeOAuthArchive(FakeArchive):
    """FakeArchive + the OAuth routes of Archive's mcp-access store."""

    def __init__(self):
        super().__init__()
        self.clients: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}

    def __call__(self, method, path, body=None):
        base = "api/mcp-access-store/"
        rest = path[len(base):]
        if rest == "oauth/clients" and method == "POST":
            self.clients[body["client_id"]] = dict(body)
            return 200, {"client_id": body["client_id"]}
        if rest == "oauth/clients":
            return 200, {"clients": list(self.clients.values())}
        if rest.startswith("oauth/clients/"):
            client_id, _, action = rest[len("oauth/clients/"):].partition("/")
            row = self.clients.get(client_id)
            if row is None:
                return 404, {"detail": "client not found"}
            if action == "check-secret":
                return 200, {"ok": bool(row["secret_hash"]) and row["secret_hash"] == body["secret_hash"]}
            return 200, {**{k: v for k, v in row.items() if k != "secret_hash"},
                         "has_secret": bool(row["secret_hash"])}
        if rest == "oauth/codes":
            self.codes[body["code_hash"]] = {**body, "used": False, "access_id": None}
            return 200, {"status": "ok"}
        if rest == "oauth/codes/consume":
            row = self.codes.get(body["code_hash"])
            if row is None:
                return 404, {"detail": "unknown code"}
            reused = row["used"]
            if not reused:
                row.update(used=True, access_id=body["access_id"])
            return 200, {**{k: v for k, v in row.items() if k not in ("used", "code_hash")}, "reused": reused}
        if rest.startswith("accesses/by-refresh/"):
            digest = rest.rsplit("/", 1)[1]
            for row in self.rows.values():
                if row.get("refresh_hash") == digest:
                    return 200, {**row, "reused": False}
            for row in self.rows.values():
                if row.get("prev_refresh_hash") == digest:
                    return 200, {**row, "reused": True}
            return 404, {"detail": "unknown refresh token"}
        if rest.startswith("accesses/") and rest.endswith("/rotate"):
            row = self.rows[rest.split("/")[1]]
            if row.get("refresh_hash") != body["old_refresh_hash"]:
                return 409, {"detail": "already rotated"}
            row.update(token_hash=body["token_hash"], refresh_hash=body["refresh_hash"],
                       prev_refresh_hash=body["old_refresh_hash"], token_expires_at=body["token_expires_at"])
            return 200, row
        return super().__call__(method, path, body)


@pytest.fixture
def oauth(rig, monkeypatch):  # noqa: F811
    c, store, _, routed, inbox, values = rig
    archive = FakeOAuthArchive()
    monkeypatch.setattr(store, "_archive", archive)
    values["mcp.oauth.access_token_minutes"] = 60
    monkeypatch.setattr(oauth_mod.settings, "get", lambda k: values[k])
    server = OAuthServer(store, c.app.state.catalog if hasattr(c.app.state, "catalog") else _catalog(c))
    c.app.include_router(server.router())
    return c, store, archive


def _catalog(client):
    from core.catalog import ToolCatalog
    return ToolCatalog("http://hub/api")


def _register(c, **extra):
    resp = c.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT],
                                           "token_endpoint_auth_method": "none", **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authorize(c, client_id, verifier, **extra):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
              "code_challenge": pkce_s256(verifier), "code_challenge_method": "S256", "scope": "read", **extra}
    return c.get("/oauth/authorize", params=params, headers={"X-Hestia-Public-Base": BASE}).json()


def _consent(c, request_id, **consent):
    resp = c.post(f"/api/mcp/oauth/requests/{request_id}/approve", json={"scope": "read", **consent})
    assert resp.status_code == 200, resp.text
    query = parse_qs(urlsplit(resp.json()["redirect"]).query)
    assert query["state"] == ["xyz"] and query["iss"] == [BASE]
    return query["code"][0]


def _code_for(c, verifier, **consent):
    client = _register(c)
    request_id = _authorize(c, client["client_id"], verifier)["request_id"]
    return client, _consent(c, request_id, **consent)


def _exchange(c, client_id, code, verifier, redirect=REDIRECT):
    return c.post("/oauth/token", data={"grant_type": "authorization_code", "client_id": client_id, "code": code,
                                        "code_verifier": verifier, "redirect_uri": redirect})


def _verifier():
    return secrets.token_urlsafe(48)


@pytest.mark.unit
class TestHelpers:
    def test_pkce_s256_matches_rfc7636_example(self):
        assert pkce_s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    @pytest.mark.parametrize("uri,ok", [(REDIRECT, True), ("http://localhost:3000/cb", True),
                                        ("http://127.0.0.1/cb", True), ("http://evil.example/cb", False),
                                        ("https://a.example/cb#frag", False), ("javascript:alert(1)", False)])
    def test_redirect_rules(self, uri, ok):
        assert valid_redirect(uri) is ok


@pytest.mark.api
class TestOAuthFlow:
    def test_metadata_uses_the_public_base(self, oauth):
        c, *_ = oauth
        meta = c.get("/.well-known/oauth-authorization-server", headers={"X-Hestia-Public-Base": BASE}).json()
        assert meta["issuer"] == BASE and meta["token_endpoint"] == f"{BASE}/oauth/token"
        assert meta["code_challenge_methods_supported"] == ["S256"]
        res = c.get("/.well-known/oauth-protected-resource/mcp", headers={"X-Hestia-Public-Base": BASE}).json()
        assert res["resource"] == f"{BASE}/mcp" and res["authorization_servers"] == [BASE]
        bad = c.get("/.well-known/oauth-authorization-server", headers={"X-Hestia-Public-Base": "evil\"x"}).json()
        assert bad["issuer"] == oauth_mod.DEFAULT_BASE

    def test_register_refuses_plain_http_redirects(self, oauth):
        c, *_ = oauth
        resp = c.post("/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]})
        assert resp.status_code == 400 and resp.json()["error"] == "invalid_redirect_uri"

    def test_full_flow_token_works_on_the_door_and_refresh_rotates(self, oauth):
        c, store, archive = oauth
        verifier = _verifier()
        client, code = _code_for(c, verifier)
        assert not any(row.get("kind") == "oauth" for row in archive.rows.values())   # no access before the exchange
        tokens = _exchange(c, client["client_id"], code, verifier).json()
        assert tokens["access_token"].startswith("hso_") and tokens["refresh_token"].startswith("hsr_")
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600 and tokens["scope"] == "read"
        row = next(iter(archive.rows.values()))
        assert row["kind"] == "oauth" and row["client_id"] == client["client_id"]
        assert tokens["access_token"] not in str(archive.rows) and tokens["refresh_token"] not in str(archive.rows)
        names = [t["name"] for t in _rpc(c, "tools/list", token=tokens["access_token"]).json()["result"]["tools"]]
        assert names == ["forge_tasks"]                                               # read scope, external only

        fresh = c.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                             "refresh_token": tokens["refresh_token"]}).json()
        assert fresh["refresh_token"] != tokens["refresh_token"]
        assert _rpc(c, "tools/list", token=tokens["access_token"]).status_code == 401    # old access token stops
        assert _rpc(c, "tools/list", token=fresh["access_token"]).status_code == 200

    def test_replayed_refresh_token_revokes_the_access(self, oauth):
        c, _, archive = oauth
        verifier = _verifier()
        client, code = _code_for(c, verifier)
        tokens = _exchange(c, client["client_id"], code, verifier).json()
        refresh = {"grant_type": "refresh_token", "client_id": client["client_id"],
                   "refresh_token": tokens["refresh_token"]}
        fresh = c.post("/oauth/token", data=refresh).json()
        replay = c.post("/oauth/token", data=refresh)
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        assert next(iter(archive.rows.values()))["revoked_at"]
        assert _rpc(c, "tools/list", token=fresh["access_token"]).status_code == 401

    def test_reused_code_fails_and_revokes(self, oauth):
        c, _, archive = oauth
        verifier = _verifier()
        client, code = _code_for(c, verifier)
        tokens = _exchange(c, client["client_id"], code, verifier).json()
        again = _exchange(c, client["client_id"], code, verifier)
        assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
        assert _rpc(c, "tools/list", token=tokens["access_token"]).status_code == 401

    def test_wrong_verifier_or_redirect_gets_no_token(self, oauth):
        c, *_ = oauth
        verifier = _verifier()
        client, code = _code_for(c, verifier)
        assert _exchange(c, client["client_id"], code, _verifier()).json()["error"] == "invalid_grant"
        client, code = _code_for(c, verifier)
        assert _exchange(c, client["client_id"], code, verifier,
                         redirect="https://claude.ai/other").json()["error"] == "invalid_grant"

    def test_authorize_errors(self, oauth):
        c, *_ = oauth
        assert _authorize(c, "hmc_unknown", _verifier())["error"] == "invalid_client"
        client = _register(c)
        out = _authorize(c, client["client_id"], _verifier(), redirect_uri="https://evil.example/cb")
        assert out["error"] == "invalid_request" and "redirect" not in out      # never redirect to an unknown URI
        out = _authorize(c, client["client_id"], _verifier(), code_challenge_method="plain")
        assert out["error"] == "invalid_request" and out["redirect"].startswith(REDIRECT)

    def test_deny_and_used_request(self, oauth):
        c, *_ = oauth
        client = _register(c)
        request_id = _authorize(c, client["client_id"], _verifier())["request_id"]
        assert c.get(f"/api/mcp/oauth/requests/{request_id}").json()["client_name"] == "Claude"
        out = c.post(f"/api/mcp/oauth/requests/{request_id}/deny").json()
        assert parse_qs(urlsplit(out["redirect"]).query)["error"] == ["access_denied"]
        assert c.post(f"/api/mcp/oauth/requests/{request_id}/approve", json={}).status_code == 404

    def test_confidential_client_needs_its_secret(self, oauth):
        c, *_ = oauth
        client = _register(c, token_endpoint_auth_method="client_secret_basic")
        verifier = _verifier()
        request_id = _authorize(c, client["client_id"], verifier)["request_id"]
        code = _consent(c, request_id)
        form = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": REDIRECT}
        wrong = base64.b64encode(f"{client['client_id']}:nope".encode()).decode()
        assert c.post("/oauth/token", data=form, headers={"Authorization": f"Basic {wrong}"}).status_code == 401
        good = base64.b64encode(f"{client['client_id']}:{client['client_secret']}".encode()).decode()
        resp = c.post("/oauth/token", data=form, headers={"Authorization": f"Basic {good}"})
        assert resp.status_code == 200 and resp.json()["access_token"].startswith("hso_")

    def test_revoke_endpoint_stops_the_grant(self, oauth):
        c, *_ = oauth
        verifier = _verifier()
        client, code = _code_for(c, verifier)
        tokens = _exchange(c, client["client_id"], code, verifier).json()
        assert c.post("/oauth/revoke", data={"token": tokens["refresh_token"]}).status_code == 200
        assert _rpc(c, "tools/list", token=tokens["access_token"]).status_code == 401
        assert c.post("/oauth/revoke", data={"token": "hsr_unknown"}).status_code == 200

    def test_expired_access_token_gets_401_with_invalid_token(self, oauth):
        c, store, archive = oauth
        verifier = _verifier()
        client, code = _code_for(c, verifier)
        tokens = _exchange(c, client["client_id"], code, verifier).json()
        next(iter(archive.rows.values()))["token_expires_at"] = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        store._forget()
        resp = _rpc(c, "tools/list", token=tokens["access_token"])
        assert resp.status_code == 401 and 'error="invalid_token"' in resp.headers["www-authenticate"]
