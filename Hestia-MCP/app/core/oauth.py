"""OAuth 2.1 authorization server of Hestia's MCP (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B3, §B6).

For the clients that only speak OAuth (claude.ai web/mobile custom connectors, ChatGPT). Everything public goes
through the WebUI door (the only service behind the tunnel), which forwards here through Hub and passes the public
address it was reached at in ``X-Hestia-Public-Base`` (issuer, metadata URLs):

- ``GET /.well-known/oauth-protected-resource[/mcp]`` (RFC 9728) and ``GET /.well-known/oauth-authorization-server``
  (RFC 8414) — metadata.
- ``POST /oauth/register`` (RFC 7591) — dynamic client registration (redirect URIs https, or http on loopback).
- ``GET /oauth/authorize`` — checks client, exact redirect_uri, PKCE S256 and parks the request; the WebUI then shows
  its consent page (behind the normal WebUI login). **No code without that page**: only
  ``POST /api/mcp/oauth/requests/{id}/approve`` (WebUI, logged in) issues one, with the scope, tools and expiry Marko
  picked there.
- ``POST /oauth/token`` — ``authorization_code`` (PKCE verifier, same redirect_uri, code used once: a replay revokes
  the access it became) and ``refresh_token`` (rotated on every use; a replayed old one revokes the access).
- ``POST /oauth/revoke`` (RFC 7009).

A grant is an access of kind ``oauth`` in the same list as the tokens (Accessi page): revoke / renew / delete work the
same, and its access tokens (``hso_…``, short-lived: ``mcp.oauth.access_token_minutes``) go through the same check as
``hst_…`` tokens (scope, tools, expiry, rate limit, audit). Clients, codes and tokens are stored in Archive only as
sha256 hashes (the client id is public).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.access import (OAUTH_TOKEN_PREFIX, SCOPES, AccessError, AccessStore, RateLimiter, hash_token, usable)
from core.catalog import EXTERNAL
from core.mcp_settings import OAUTH_TOKEN_MINUTES, settings

logger = logging.getLogger("hestia_mcp.oauth")

CLIENT_PREFIX = "hmc_"
CODE_PREFIX = "hsc_"
REFRESH_PREFIX = "hsr_"
CODE_TTL_S = 300            # a code lives 5 minutes (protocol, not a tunable)
REQUEST_TTL_S = 900         # time to log in on the WebUI and press Consenti
MAX_PENDING = 50
REGISTER_PER_MIN = 10       # dynamic registration is open to the internet: a small global brake
DEFAULT_BASE = "http://localhost:19015"
_STORE = "api/mcp-access-store"
_BASE_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$")
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
SCOPE_STRING = {"read": "read", "write": "read write"}


class OAuthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(description or error)
        self.error, self.description, self.status = error, description, status

    def response(self) -> JSONResponse:
        body = {"error": self.error, **({"error_description": self.description} if self.description else {})}
        return JSONResponse(body, status_code=self.status, headers={"Cache-Control": "no-store"})


# ── small helpers (also used by the door, core/external.py) ──────────────────

def public_base(request: Request) -> str:
    """The public address the WebUI door was reached at (``X-Hestia-Public-Base``), else the local WebUI."""
    raw = (request.headers.get("x-hestia-public-base") or "").strip().rstrip("/")
    return raw if _BASE_RE.match(raw) else DEFAULT_BASE


def resource_metadata_url(base: str) -> str:
    return f"{base}/.well-known/oauth-protected-resource/mcp"


def www_authenticate(base: str, error: str | None = None) -> str:
    """``Bearer resource_metadata="…"``: tells an OAuth client (claude.ai, ChatGPT) where to start."""
    parts = ([f'error="{error}"'] if error else []) + [f'resource_metadata="{resource_metadata_url(base)}"']
    return "Bearer " + ", ".join(parts)


def pkce_s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def valid_redirect(uri: str) -> bool:
    """https anywhere, http only on loopback (desktop clients); never a fragment."""
    try:
        parts = urlsplit(str(uri))
    except ValueError:
        return False
    if parts.fragment or not parts.hostname or len(str(uri)) > 2000:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


def with_query(uri: str, params: dict[str, Any]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(k, str(v)) for k, v in params.items() if v is not None]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def requested_scope(scope: str | None) -> str:
    return "write" if "write" in str(scope or "").split() else "read"


def external_tool_list(catalog) -> list[dict]:
    """Tools a module opened to external AIs (what an access can be limited to)."""
    return [{"name": t["name"], "title": t.get("title"), "description": t.get("description"),
             "service": (t.get("_meta") or {}).get("hestia", {}).get("service"),
             "writes": not t["annotations"]["readOnlyHint"]} for t in catalog.tools(EXTERNAL)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Consent(BaseModel):
    scope: str = Field("read", description="read | write")
    tools: list[str] = Field(default_factory=list, description="[] = every tool open to external AIs")
    expires_days: int | None = Field(90, description="0 or null = no expiry")
    name: str | None = Field(None, description="Name in the Accessi list (default: the client's name)")


class OAuthServer:
    def __init__(self, store: AccessStore, catalog):
        self.store = store
        self.catalog = catalog
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._register_brake = RateLimiter()

    def _archive(self, method: str, path: str, body: Any = None) -> Any:
        return self.store._ok(*self.store._archive(method, f"{_STORE}/{path}", body))

    # ── metadata ───────────────────────────────────────────────────────────
    @staticmethod
    def resource_metadata(base: str) -> dict:
        return {"resource": f"{base}/mcp", "authorization_servers": [base], "scopes_supported": list(SCOPES),
                "bearer_methods_supported": ["header"], "resource_name": "Hestia"}

    @staticmethod
    def server_metadata(base: str) -> dict:
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": list(_AUTH_METHODS),
            "revocation_endpoint_auth_methods_supported": list(_AUTH_METHODS),
            "scopes_supported": list(SCOPES),
            "authorization_response_iss_parameter_supported": True,
            "service_documentation": "https://github.com/marcovidic/Hestia#collegare-unai-esterna",
        }

    # ── RFC 7591 registration ──────────────────────────────────────────────
    def register(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise OAuthError("invalid_client_metadata", "JSON object expected")
        if not self._register_brake.allow("register", REGISTER_PER_MIN):
            raise OAuthError("temporarily_unavailable", "Too many registrations, retry in a minute", 429)
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > 10:
            raise OAuthError("invalid_redirect_uri", "redirect_uris: 1 to 10 URIs")
        uris = [str(u) for u in uris]
        bad = [u for u in uris if not valid_redirect(u)]
        if bad:
            raise OAuthError("invalid_redirect_uri", f"Not allowed (https, or http on localhost): {bad[0][:200]}")
        method = str(body.get("token_endpoint_auth_method") or "client_secret_basic")
        if method not in _AUTH_METHODS:
            raise OAuthError("invalid_client_metadata", f"token_endpoint_auth_method {method} not supported")
        grants = body.get("grant_types") or ["authorization_code", "refresh_token"]
        if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
            raise OAuthError("invalid_client_metadata", "grant_types: authorization_code, refresh_token")
        responses = body.get("response_types") or ["code"]
        if responses != ["code"]:
            raise OAuthError("invalid_client_metadata", "response_types: code")
        name = " ".join(str(body.get("client_name") or "").split())[:80] or urlsplit(uris[0]).hostname or "AI esterna"
        client_id = CLIENT_PREFIX + secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(32) if method != "none" else None
        self._archive("POST", "oauth/clients", {
            "client_id": client_id, "client_name": name, "redirect_uris": uris, "auth_method": method,
            "secret_hash": hash_token(secret) if secret else None,
            "meta": {k: str(body[k])[:300] for k in ("client_uri", "software_id", "software_version") if body.get(k)}})
        logger.info("event=mcp_oauth_client_registered client=%s name=%s auth=%s redirect_host=%s", client_id, name,
                    method, urlsplit(uris[0]).hostname)
        out = {"client_id": client_id, "client_id_issued_at": int(time.time()), "client_name": name,
               "redirect_uris": uris, "grant_types": grants, "response_types": ["code"],
               "token_endpoint_auth_method": method}
        if secret:
            out.update(client_secret=secret, client_secret_expires_at=0)
        return out

    def _client(self, client_id: str) -> dict | None:
        if not str(client_id or "").startswith(CLIENT_PREFIX):
            return None
        status, payload = self.store._archive("GET", f"{_STORE}/oauth/clients/{client_id}")
        if status >= 500:
            raise OAuthError("temporarily_unavailable", "Archive unavailable", 503)
        return payload if status < 400 and isinstance(payload, dict) else None

    # ── authorize: check, then park the request for the consent page ───────
    def authorize(self, params: dict, base: str) -> dict:
        """``{status: consent, request_id}``, or ``{status: error, error, error_description, redirect?}``.
        No ``redirect`` when the client or its redirect_uri cannot be trusted (the WebUI shows the error)."""
        client = self._client(params.get("client_id"))
        if client is None:
            return {"status": "error", "error": "invalid_client", "error_description": "Client sconosciuto"}
        redirect_uri = params.get("redirect_uri") or (
            client["redirect_uris"][0] if len(client["redirect_uris"]) == 1 else "")
        if redirect_uri not in client["redirect_uris"]:
            return {"status": "error", "error": "invalid_request",
                    "error_description": "redirect_uri diverso da quello registrato"}
        state = params.get("state")

        def fail(error: str, description: str) -> dict:
            logger.info("event=mcp_oauth_authorize_refused client=%s error=%s", client["client_id"], error)
            return {"status": "error", "error": error, "error_description": description,
                    "redirect": with_query(redirect_uri, {"error": error, "error_description": description,
                                                          "state": state, "iss": base})}

        if params.get("response_type") != "code":
            return fail("unsupported_response_type", "Only response_type=code")
        challenge = str(params.get("code_challenge") or "")
        if not challenge:
            return fail("invalid_request", "PKCE required (code_challenge)")
        if params.get("code_challenge_method") != "S256":
            return fail("invalid_request", "code_challenge_method must be S256")
        if not _CHALLENGE_RE.match(challenge):
            return fail("invalid_request", "Malformed code_challenge")
        request_id = secrets.token_urlsafe(24)
        now = time.time()
        with self._lock:
            for key in [k for k, v in self._pending.items() if now - v["created"] > REQUEST_TTL_S]:
                self._pending.pop(key, None)
            while len(self._pending) >= MAX_PENDING:
                self._pending.pop(next(iter(self._pending)))
            self._pending[request_id] = {
                "client_id": client["client_id"], "client_name": client["client_name"], "redirect_uri": redirect_uri,
                "state": state, "code_challenge": challenge, "scope": requested_scope(params.get("scope")),
                "resource": params.get("resource"), "base": base, "created": now}
        logger.info("event=mcp_oauth_consent_asked client=%s name=%s", client["client_id"], client["client_name"])
        return {"status": "consent", "request_id": request_id}

    def _request(self, request_id: str, pop: bool = False) -> dict:
        with self._lock:
            req = self._pending.get(request_id)
            if req and time.time() - req["created"] > REQUEST_TTL_S:
                self._pending.pop(request_id, None)
                req = None
            if req and pop:
                self._pending.pop(request_id, None)
        if req is None:
            raise AccessError("Richiesta di collegamento scaduta o già usata: ricollega dall'app", 404)
        return req

    def pending(self, request_id: str) -> dict:
        req = self._request(request_id)
        return {"request_id": request_id, "client_id": req["client_id"], "client_name": req["client_name"],
                "redirect_uri": req["redirect_uri"], "redirect_host": urlsplit(req["redirect_uri"]).hostname,
                "scope": req["scope"], "resource": req["resource"],
                "expires_in": int(REQUEST_TTL_S - (time.time() - req["created"])),
                "tools": external_tool_list(self.catalog)}

    def approve(self, request_id: str, consent: Consent) -> dict:
        if consent.scope not in SCOPES:
            raise AccessError(f"Scope sconosciuto '{consent.scope}': usa read o write")
        req = self._request(request_id, pop=True)
        code = CODE_PREFIX + secrets.token_urlsafe(32)
        days = int(consent.expires_days) if consent.expires_days else None
        name = " ".join(str(consent.name or "").split())[:80] or req["client_name"]
        self._archive("POST", "oauth/codes", {
            "code_hash": hash_token(code), "client_id": req["client_id"], "redirect_uri": req["redirect_uri"],
            "code_challenge": req["code_challenge"], "scope": consent.scope,
            "tools": sorted({str(t).strip() for t in consent.tools if str(t).strip()}), "name": name,
            "expires_days": days if days and days > 0 else None, "resource": req["resource"],
            "expires_at": (_now() + timedelta(seconds=CODE_TTL_S)).isoformat()})
        logger.info("event=mcp_oauth_consent_given client=%s access=%s scope=%s tools=%d", req["client_id"], name,
                    consent.scope, len(consent.tools))
        return {"redirect": with_query(req["redirect_uri"], {"code": code, "state": req["state"], "iss": req["base"]})}

    def deny(self, request_id: str) -> dict:
        req = self._request(request_id, pop=True)
        logger.info("event=mcp_oauth_consent_denied client=%s", req["client_id"])
        return {"redirect": with_query(req["redirect_uri"], {
            "error": "access_denied", "error_description": "Rifiutato su Hestia", "state": req["state"],
            "iss": req["base"]})}

    # ── token endpoint ─────────────────────────────────────────────────────
    def _authenticate(self, form: dict, authorization: str) -> dict:
        client_id, secret = form.get("client_id"), form.get("client_secret")
        if authorization.lower().startswith("basic "):
            try:
                user, _, password = base64.b64decode(authorization[6:].strip()).decode("utf-8").partition(":")
            except (ValueError, UnicodeDecodeError):
                raise OAuthError("invalid_client", "Malformed Basic header", 401)
            from urllib.parse import unquote
            client_id, secret = unquote(user), unquote(password)
        client = self._client(client_id)
        if client is None:
            raise OAuthError("invalid_client", "Unknown client", 401)
        if client.get("auth_method") != "none" or client.get("has_secret"):
            if not secret:
                raise OAuthError("invalid_client", "client_secret required", 401)
            if not (self._archive("POST", f"oauth/clients/{client['client_id']}/check-secret",
                                  {"secret_hash": hash_token(str(secret))}) or {}).get("ok"):
                raise OAuthError("invalid_client", "Wrong client_secret", 401)
        return client

    def _tokens(self) -> tuple[str, str, str, int]:
        minutes = int(settings.get(OAUTH_TOKEN_MINUTES))
        expires = (_now() + timedelta(minutes=minutes)).isoformat()
        return (OAUTH_TOKEN_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32), expires,
                minutes * 60)

    def _revoke_quietly(self, access_id: str | None, why: str) -> None:
        if not access_id:
            return
        try:
            self.store.revoke(access_id)
            logger.warning("event=mcp_oauth_access_revoked_on_replay access_id=%s reason=%s", access_id, why)
        except AccessError as exc:
            logger.info("event=mcp_oauth_replay_revoke_skipped access_id=%s error=%s", access_id, exc)

    def token(self, form: dict, authorization: str = "") -> dict:
        grant = form.get("grant_type")
        if grant not in ("authorization_code", "refresh_token"):
            raise OAuthError("unsupported_grant_type", "authorization_code or refresh_token")
        client = self._authenticate(form, authorization)
        if grant == "authorization_code":
            return self._exchange_code(client, form)
        return self._refresh(client, form)

    def _exchange_code(self, client: dict, form: dict) -> dict:
        code = str(form.get("code") or "")
        if not code.startswith(CODE_PREFIX):
            raise OAuthError("invalid_grant", "Unknown code")
        access_id = uuid.uuid4().hex[:12]
        status, row = self.store._archive("POST", f"{_STORE}/oauth/codes/consume",
                                          {"code_hash": hash_token(code), "access_id": access_id})
        if status >= 500:
            raise OAuthError("temporarily_unavailable", "Archive unavailable", 503)
        if status >= 400 or not isinstance(row, dict):
            raise OAuthError("invalid_grant", "Unknown code")
        if row.get("reused"):
            self._revoke_quietly(row.get("access_id"), "code_reused")
            raise OAuthError("invalid_grant", "Code already used")
        expires = row.get("expires_at")
        if not expires or datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= _now():
            raise OAuthError("invalid_grant", "Code expired")
        if row.get("client_id") != client["client_id"]:
            raise OAuthError("invalid_grant", "Code issued to another client")
        if form.get("redirect_uri") != row.get("redirect_uri"):
            raise OAuthError("invalid_grant", "redirect_uri does not match the authorization request")
        verifier = str(form.get("code_verifier") or "")
        if not (43 <= len(verifier) <= 128) or not secrets.compare_digest(pkce_s256(verifier), row["code_challenge"]):
            raise OAuthError("invalid_grant", "PKCE verification failed")
        access_token, refresh_token, token_expires, expires_in = self._tokens()
        days = row.get("expires_days")
        self.store.create_oauth({
            "access_id": access_id, "name": row["name"], "scope": row["scope"], "tools": row.get("tools") or [],
            "token_hash": hash_token(access_token), "refresh_hash": hash_token(refresh_token),
            "token_expires_at": token_expires, "client_id": client["client_id"],
            "expires_at": (_now() + timedelta(days=int(days))).isoformat() if days else None,
            "meta": {"client_name": client["client_name"], "redirect_host": urlsplit(row["redirect_uri"]).hostname,
                     "resource": row.get("resource")}})
        return {"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in,
                "refresh_token": refresh_token, "scope": SCOPE_STRING.get(row["scope"], "read")}

    def _refresh(self, client: dict, form: dict) -> dict:
        refresh = str(form.get("refresh_token") or "")
        if not refresh.startswith(REFRESH_PREFIX):
            raise OAuthError("invalid_grant", "Unknown refresh token")
        old_hash = hash_token(refresh)
        try:
            access = self.store.by_refresh(old_hash)
        except AccessError:
            raise OAuthError("temporarily_unavailable", "Archive unavailable", 503)
        if access is None:
            raise OAuthError("invalid_grant", "Unknown refresh token")
        if access.get("reused"):
            self._revoke_quietly(access.get("access_id"), "refresh_reused")
            raise OAuthError("invalid_grant", "Refresh token already used")
        if access.get("client_id") != client["client_id"]:
            raise OAuthError("invalid_grant", "Refresh token of another client")
        ok, why = usable(access, token=False)
        if not ok:
            raise OAuthError("invalid_grant", f"Access {why}")
        access_token, refresh_token, token_expires, expires_in = self._tokens()
        if self.store.rotate(access["access_id"], old_hash, hash_token(access_token), hash_token(refresh_token),
                             token_expires) is None:
            raise OAuthError("invalid_grant", "Refresh token already used")
        logger.info("event=mcp_oauth_token_refreshed access=%s", access.get("name"))
        return {"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in,
                "refresh_token": refresh_token, "scope": SCOPE_STRING.get(access.get("scope"), "read")}

    def revoke_token(self, form: dict) -> None:
        """RFC 7009: revoking either token of a grant stops the whole access. Unknown tokens are not an error."""
        token = str(form.get("token") or "")
        access = None
        if token.startswith(REFRESH_PREFIX):
            access = self.store.by_refresh(hash_token(token))
        elif token.startswith(OAUTH_TOKEN_PREFIX):
            status, payload = self.store._archive("GET", f"{_STORE}/accesses/by-hash/{hash_token(token)}")
            access = payload if status < 400 and isinstance(payload, dict) else None
        if access and access.get("kind") == "oauth" and (
                not form.get("client_id") or form.get("client_id") == access.get("client_id")):
            self.store.revoke(access["access_id"])

    # ── HTTP ───────────────────────────────────────────────────────────────
    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/.well-known/oauth-protected-resource")
        @router.get("/.well-known/oauth-protected-resource/mcp")
        def protected_resource(request: Request):
            return self.resource_metadata(public_base(request))

        @router.get("/.well-known/oauth-authorization-server")
        def authorization_server(request: Request):
            return self.server_metadata(public_base(request))

        @router.post("/oauth/register")
        async def register(request: Request):
            try:
                body = await request.json()
                return JSONResponse(self.register(body), status_code=201, headers={"Cache-Control": "no-store"})
            except ValueError:
                return OAuthError("invalid_client_metadata", "JSON body expected").response()
            except OAuthError as exc:
                return exc.response()
            except AccessError as exc:
                return OAuthError("temporarily_unavailable", str(exc), 503).response()

        @router.get("/oauth/authorize")
        def authorize(request: Request):
            try:
                return self.authorize(dict(request.query_params), public_base(request))
            except OAuthError as exc:
                return {"status": "error", "error": exc.error, "error_description": exc.description}

        @router.post("/oauth/token")
        async def token(request: Request):
            try:
                form = await _form(request)
                return JSONResponse(self.token(form, request.headers.get("authorization") or ""),
                                    headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
            except OAuthError as exc:
                if exc.error != "invalid_grant":
                    logger.info("event=mcp_oauth_token_refused error=%s", exc.error)
                else:
                    logger.info("event=mcp_oauth_token_refused error=invalid_grant reason=%s", exc.description)
                return exc.response()
            except AccessError as exc:
                return OAuthError("temporarily_unavailable", str(exc), 503).response()

        @router.post("/oauth/revoke")
        async def revoke(request: Request):
            try:
                self.revoke_token(await _form(request))
            except AccessError as exc:
                return OAuthError("temporarily_unavailable", str(exc), 503).response()
            return JSONResponse({}, headers={"Cache-Control": "no-store"})

        # Consent page (WebUI, behind its login) — never reachable from the door.
        def _guard(fn):
            try:
                return fn()
            except AccessError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

        @router.get("/api/mcp/oauth/requests/{request_id}")
        def consent_request(request_id: str):
            return _guard(lambda: self.pending(request_id))

        @router.post("/api/mcp/oauth/requests/{request_id}/approve")
        def consent_approve(request_id: str, body: Consent):
            return _guard(lambda: self.approve(request_id, body))

        @router.post("/api/mcp/oauth/requests/{request_id}/deny")
        def consent_deny(request_id: str):
            return _guard(lambda: self.deny(request_id))

        @router.get("/api/mcp/oauth/clients")
        def clients():
            return _guard(lambda: self._archive("GET", "oauth/clients"))

        return router


async def _form(request: Request) -> dict:
    """Token/revoke body: form-encoded (OAuth clients calling directly) or JSON (the WebUI door through Hub)."""
    raw = await request.body()
    if not raw:
        return {}
    if "application/x-www-form-urlencoded" in (request.headers.get("content-type") or ""):
        return dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
    try:
        data = json.loads(raw)
    except ValueError:
        raise OAuthError("invalid_request", "Body must be form-encoded or JSON")
    if not isinstance(data, dict):
        raise OAuthError("invalid_request", "Body must be an object")
    return {k: (v if isinstance(v, str) or v is None else str(v)) for k, v in data.items()}
