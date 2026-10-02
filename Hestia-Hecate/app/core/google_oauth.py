"""Google OAuth 2.0 authorization-code flow (loopback redirect + PKCE).

Why this module exists
----------------------
The previous implementation used the "out-of-band" redirect
(``urn:ietf:wg:oauth:2.0:oob``).  Google blocked OOB for every client type in
January 2023, so the consent page always failed with
``Error 400: invalid_request``.  This module replaces it with the flow Google
still supports for "Desktop app" OAuth clients:

1. ``start()`` builds an authorization URL whose ``redirect_uri`` is a loopback
   address (default ``http://localhost:19003/api/gateway/auth/callback/google``).
2. The user opens the URL, grants access, and Google redirects the browser to
   the loopback address with ``?code=...&state=...``.
   * Browser on the Docker host → the request reaches Hecate directly and the
     callback endpoint finishes the flow automatically.
   * Browser on another device (phone) → the page does not load, which is
     expected.  The user copies the URL from the address bar and sends it to
     ``POST /api/gateway/auth/complete/google`` (or pastes it in Telegram).
3. ``complete()`` exchanges the code (with the PKCE verifier) for tokens.

Pending sessions are persisted to disk so a container restart between the two
steps does not lose the flow.  No third-party OAuth library is needed: the
exchange is a single HTTPS POST.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

logger = logging.getLogger("hestia_hecate.google_oauth")

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
]
DEFAULT_REDIRECT_URI = "http://localhost:19003/api/gateway/auth/callback/google"
PENDING_TTL_SECONDS = 15 * 60

_LOCK = threading.Lock()


class GoogleOAuthError(Exception):
    """User-facing OAuth error with an HTTP status hint."""

    def __init__(self, message: str, status_code: int = 400, hint: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.hint = hint

    def to_detail(self) -> dict:
        detail = {"error": str(self)}
        if self.hint:
            detail["hint"] = self.hint
        return detail


# ── Configuration ─────────────────────────────────────────────────────────


def scopes() -> list[str]:
    raw = os.getenv("GOOGLE_OAUTH_SCOPES", "").strip()
    if not raw:
        return list(DEFAULT_SCOPES)
    return [s for s in raw.replace(",", " ").split() if s]


def redirect_uri() -> str:
    """Redirect URI resolution:

    1. ``GOOGLE_OAUTH_REDIRECT_URI`` when public (a localhost value yields to the tunnel);
    2. public Cloudflare tunnel URL for Hecate, read from ``GOOGLE_TUNNEL_URL_FILE``
       (default ``/code/data/tunnel-url.txt``, written by ``cloudflare-tunnel.bat``):
       the callback then works from ANY device (phone included), no copy-paste;
    3. localhost loopback (auto-completes only from the Docker host; elsewhere the
       user pastes the final URL in chat).
    """
    explicit = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if explicit and is_public_redirect(explicit):
        return explicit
    # An explicit *localhost* value (old .env default) must not hide the tunnel.
    tunnel_file = Path(os.getenv("GOOGLE_TUNNEL_URL_FILE", "/code/data/tunnel-url.txt"))
    try:
        if tunnel_file.exists():
            # utf-8-sig: Windows PowerShell 5 ``Out-File -Encoding utf8`` writes a BOM.
            tunnel = tunnel_file.read_text(encoding="utf-8-sig").strip().lstrip("\ufeff")
            if tunnel.startswith("https://") and _tunnel_alive(tunnel):
                return f"{tunnel.rstrip('/')}/api/gateway/auth/callback/google"
    except Exception as exc:
        logger.debug("event=google_tunnel_url_read_skipped reason=%s", exc)
    return explicit or DEFAULT_REDIRECT_URI


_TUNNEL_CHECK: dict[str, tuple[float, bool]] = {}


def _tunnel_alive(url: str) -> bool:
    """A stale tunnel-url.txt (tunnel stopped) must not become the redirect: Google
    would send the user to a dead page.  Checks ``<tunnel>/health`` (cached 60 s)."""
    now = time.time()
    cached = _TUNNEL_CHECK.get(url)
    if cached and now - cached[0] < 60:
        return cached[1]
    try:
        alive = requests.get(f"{url.rstrip('/')}/health", timeout=4).status_code < 500
    except requests.RequestException:
        alive = False
    if not alive:
        logger.warning("[🔄] event=google_tunnel_unreachable url=%s fallback=localhost", url)
    _TUNNEL_CHECK[url] = (now, alive)
    return alive


def is_public_redirect(uri: str) -> bool:
    """True when the redirect reaches Hecate from any device (not loopback)."""
    host = (urlparse(uri).hostname or "").lower()
    return bool(host) and host not in {"localhost", "127.0.0.1", "::1"}


def client_credentials() -> tuple[str, str]:
    return (
        os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
    )


def _pending_file() -> Path:
    token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", "/code/data/google_token.json"))
    return token_file.parent / "google_oauth_pending.json"


# ── Pending session store (disk-backed, single pending flow) ──────────────


def _load_pending() -> dict | None:
    path = _pending_file()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception as exc:
        logger.warning("event=google_oauth_pending_read_failed path=%s error=%s", path, exc)
        return None
    if not isinstance(data, dict) or not data.get("state"):
        return None
    if time.time() > float(data.get("expires_at", 0)):
        logger.info("event=google_oauth_pending_expired")
        _clear_pending()
        return None
    return data


def _save_pending(data: dict) -> None:
    path = _pending_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        # In-memory fallback is not possible across restarts; log loudly.
        logger.warning("event=google_oauth_pending_write_failed path=%s error=%s", path, exc)
        raise GoogleOAuthError(
            f"Cannot persist OAuth session to {path}: {exc}", status_code=500,
            hint="Check that the Hecate data/ volume is writable.")


def _clear_pending() -> None:
    try:
        _pending_file().unlink(missing_ok=True)
    except Exception:
        pass


def pending() -> dict | None:
    """Public view of the pending flow (no secrets)."""
    with _LOCK:
        data = _load_pending()
    if not data:
        return None
    return {
        "auth_url": data.get("auth_url"),
        "redirect_uri": data.get("redirect_uri"),
        "expires_at": data.get("expires_at"),
    }


def cancel() -> None:
    with _LOCK:
        _clear_pending()


# ── Flow steps ────────────────────────────────────────────────────────────


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def start() -> dict:
    """Create a new pending flow and return the authorization URL."""
    client_id, client_secret = client_credentials()
    if not client_id or not client_secret:
        raise GoogleOAuthError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set to start OAuth flow",
            hint="Create an OAuth client of type 'Desktop app' in Google Cloud Console "
                 "and put its id/secret in Hestia-Hecate/app/.env.")

    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    redirect = redirect_uri()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(scopes()),
        "access_type": "offline",       # ask for a refresh token
        "prompt": "consent",            # force refresh token even on re-consent
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_ENDPOINT}?{urlencode(params)}"
    with _LOCK:
        _save_pending({
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "auth_url": auth_url,
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_TTL_SECONDS,
        })
    logger.info("event=google_oauth_initiated redirect_uri=%s scopes=%s", redirect, params["scope"])
    return {"auth_url": auth_url, "redirect_uri": redirect, "expires_in": PENDING_TTL_SECONDS}


def parse_code_input(raw: str) -> tuple[str, str | None, str | None]:
    """Extract ``(code, state, error)`` from a raw code, a full redirect URL,
    or a bare query string.  Users paste whatever their browser shows."""
    text = str(raw or "").strip().strip('"').strip("'")
    if not text:
        return "", None, None
    query = ""
    if "://" in text:
        query = urlparse(text).query
    elif text.startswith("?") or "code=" in text or "error=" in text:
        query = text.lstrip("?")
    if query:
        qs = parse_qs(query)
        code = (qs.get("code") or [""])[0].strip()
        state = (qs.get("state") or [None])[0]
        error = (qs.get("error") or [None])[0]
        return code, state, error
    return text, None, None


def complete(raw_code: str, state: str | None = None) -> dict:
    """Exchange the authorization code for tokens.

    Returns the token dict in ``google.oauth2.credentials`` JSON shape
    (``token``, ``refresh_token``, ``expiry``, ``client_id``, ...).
    """
    code, parsed_state, error = parse_code_input(raw_code)
    state = state or parsed_state
    if error:
        with _LOCK:
            _clear_pending()
        raise GoogleOAuthError(
            f"Google returned error: {error}",
            hint="access_denied = consent refused, or your account is not in the "
                 "test-users list of the OAuth consent screen.")
    if not code:
        raise GoogleOAuthError("Missing authorization code",
                               hint="Send the code, or the full URL shown after granting access.")

    with _LOCK:
        session = _load_pending()
    if not session:
        raise GoogleOAuthError("No pending Google OAuth flow (expired or never started). "
                               "Call initiate first.", status_code=404)
    if state and state != session.get("state"):
        raise GoogleOAuthError(
            "OAuth state mismatch: this URL belongs to an older authorization attempt.",
            hint="Use the link from the most recent initiate call.")

    client_id, client_secret = client_credentials()
    try:
        resp = requests.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": session.get("redirect_uri") or redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": session.get("code_verifier", ""),
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError(f"Token endpoint unreachable: {exc}", status_code=502)

    payload: dict[str, Any] = {}
    try:
        payload = resp.json()
    except ValueError:
        pass
    if resp.status_code != 200:
        err = str(payload.get("error") or resp.status_code)
        desc = str(payload.get("error_description") or resp.text[:200])
        logger.warning("event=google_oauth_exchange_failed error=%s desc=%s", err, desc)
        raise GoogleOAuthError(f"Token exchange failed: {err} — {desc}", hint=_hint_for(err))

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise GoogleOAuthError(
            "Google did not return a refresh_token.",
            hint="Remove Hestia from https://myaccount.google.com/permissions and run initiate again.")

    expires_in = int(payload.get("expires_in") or 3600)
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=expires_in - 60)
    granted = str(payload.get("scope") or " ".join(scopes())).split()
    with _LOCK:
        _clear_pending()
    logger.info("event=google_oauth_exchange_ok scopes=%s", ",".join(granted))
    return {
        "token": payload.get("access_token"),
        "refresh_token": refresh_token,
        "token_uri": TOKEN_ENDPOINT,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": granted,
        "expiry": expiry.isoformat() + "Z",
    }


def _hint_for(error: str) -> str:
    hints = {
        "invalid_grant": "Code already used or expired (codes live ~10 min). Run initiate again.",
        "redirect_uri_mismatch": (
            f"Add '{redirect_uri()}' to the authorized redirect URIs of your OAuth client "
            "('Web application'), or use a 'Desktop app' client for the localhost redirect. "
            "The Cloudflare quick-tunnel URL changes at every restart: re-add it, or set a "
            "fixed GOOGLE_OAUTH_REDIRECT_URI."),
        "invalid_client": "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are wrong or the client was deleted.",
        "unauthorized_client": "This OAuth client type cannot use this flow — create a 'Desktop app' client.",
    }
    return hints.get(error, "")
