"""Who may use Hestia's MCP from outside: accesses (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B6).

An access = name, scope (read | write), the tools it may use ([] = every tool a module opened to external
clients), expiry. Stored in Archive (``/api/mcp-access-store``) through Hub; the token is shown once at
creation and only its sha256 is stored. Revoking or renewing here takes effect at once (local cache dropped).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger("hestia_mcp.access")

TOKEN_PREFIX = "hst_"          # access of kind token (made on the Accessi page)
OAUTH_TOKEN_PREFIX = "hso_"    # short-lived access token of an access of kind oauth (core/oauth.py)
SCOPES = ("read", "write")
_STORE = "api/mcp-access-store/accesses"


class AccessError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        value = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def usable(access: dict, now: datetime | None = None, *, token: bool = True) -> tuple[bool, str]:
    """``(ok, why)``: revoked or expired accesses stop at once. ``token`` also checks the short life of an OAuth
    access token (``token_expires_at``); ``token=False`` checks only the access itself (refresh grant)."""
    now = now or datetime.now(timezone.utc)
    if access.get("revoked_at"):
        return False, "revoked"
    expires = _parse(access.get("expires_at"))
    if expires and expires <= now:
        return False, "expired"
    token_expires = _parse(access.get("token_expires_at")) if token else None
    if token_expires and token_expires <= now:
        return False, "expired"
    return True, ""


def allows_tool(access: dict, tool_name: str) -> bool:
    tools = access.get("tools") or []
    return not tools or tool_name in tools


class AccessStore:
    def __init__(self, hub_api_url: str, *, cache_ttl: float = 30.0, timeout: float = 8.0):
        self.hub = hub_api_url.rstrip("/")
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._lock = threading.Lock()

    # ── Archive through Hub ────────────────────────────────────────────────
    def _archive(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        try:
            resp = requests.post(f"{self.hub}/route/archive/{path}",
                                 json={"method": method, "headers": {}, "query": {}, "body": body,
                                       "timeout_seconds": self.timeout}, timeout=self.timeout + 3)
        except Exception as exc:  # noqa: BLE001
            raise AccessError(f"Archive unreachable: {exc}", 503)
        if resp.status_code != 200:
            raise AccessError(f"Hub returned {resp.status_code}", 503)
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def _ok(self, status: int, payload: Any) -> Any:
        if status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise AccessError(str(detail or f"Archive returned {status}"), status if status < 500 else 503)
        return payload

    def _forget(self) -> None:
        with self._lock:
            self._cache.clear()

    # ── management (Accessi page) ──────────────────────────────────────────
    def list(self) -> list[dict]:
        return (self._ok(*self._archive("GET", _STORE)) or {}).get("accesses") or []

    def create(self, name: str, scope: str = "read", tools: list[str] | None = None,
               expires_days: int | None = None) -> tuple[dict, str]:
        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise AccessError("Dai un nome all'accesso (es. Claude Code PC)")
        if scope not in SCOPES:
            raise AccessError(f"Scope sconosciuto '{scope}': usa read o write")
        token = new_token()
        expires = (datetime.now(timezone.utc) + timedelta(days=int(expires_days))).isoformat() \
            if expires_days else None
        body = {"access_id": uuid.uuid4().hex[:12], "name": name, "kind": "token", "scope": scope,
                "tools": sorted({str(t).strip() for t in tools or [] if str(t).strip()}),
                "token_hash": hash_token(token), "expires_at": expires}
        access = self._ok(*self._archive("POST", _STORE, body))
        logger.info("event=mcp_access_created access=%s scope=%s tools=%d expires=%s", name, scope,
                    len(body["tools"]), expires or "-")
        return access, token

    def update(self, access_id: str, **changes: Any) -> dict:
        body: dict[str, Any] = {}
        if changes.get("name"):
            body["name"] = " ".join(str(changes["name"]).split())[:80]
        if changes.get("scope") is not None:
            if changes["scope"] not in SCOPES:
                raise AccessError(f"Scope sconosciuto '{changes['scope']}': usa read o write")
            body["scope"] = changes["scope"]
        if changes.get("tools") is not None:
            body["tools"] = sorted({str(t).strip() for t in changes["tools"] if str(t).strip()})
        if changes.get("expires_days") is not None:
            days = int(changes["expires_days"])
            if days > 0:
                body["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            else:
                body["clear_expiry"] = True
        access = self._ok(*self._archive("PATCH", f"{_STORE}/{access_id}", body))
        self._forget()
        return access

    def create_oauth(self, body: dict) -> dict:
        """An access of kind oauth (token exchange in core/oauth.py): hashes, scope and tools chosen on consent."""
        access = self._ok(*self._archive("POST", _STORE, {**body, "kind": "oauth"}))
        logger.info("event=mcp_access_created kind=oauth access=%s scope=%s tools=%d client=%s", body.get("name"),
                    body.get("scope"), len(body.get("tools") or []), body.get("client_id"))
        return access

    def by_refresh(self, refresh_hash: str) -> dict | None:
        status, payload = self._archive("GET", f"{_STORE}/by-refresh/{refresh_hash}")
        if status >= 500:
            raise AccessError("Archive unavailable", 503)
        return payload if status < 400 and isinstance(payload, dict) else None

    def rotate(self, access_id: str, old_refresh_hash: str, token_hash: str, refresh_hash: str,
               token_expires_at: str) -> dict | None:
        """New access + refresh token hashes; None when the refresh token was already rotated (race / replay)."""
        status, payload = self._archive("POST", f"{_STORE}/{access_id}/rotate", {
            "old_refresh_hash": old_refresh_hash, "token_hash": token_hash, "refresh_hash": refresh_hash,
            "token_expires_at": token_expires_at})
        self._forget()
        if status == 409:
            return None
        return self._ok(status, payload)

    def get(self, access_id: str) -> dict | None:
        return next((a for a in self.list() if a.get("access_id") == access_id), None)

    def revoke(self, access_id: str) -> dict:
        access = self._ok(*self._archive("PATCH", f"{_STORE}/{access_id}", {"revoked": True}))
        self._forget()
        logger.info("event=mcp_access_revoked access=%s", access.get("name"))
        return access

    def renew(self, access_id: str, oauth_days: int = 90) -> tuple[dict, str]:
        """New token for the same access (the old one stops at once); a revoked access comes back.
        An OAuth access has no token to show: it comes back (if revoked) and lasts ``oauth_days`` more; the AI keeps
        its refresh token and goes on. Returns ``(access, "")`` then."""
        current = self.get(access_id)
        if current and current.get("kind") == "oauth":
            expires = (datetime.now(timezone.utc) + timedelta(days=oauth_days)).isoformat()
            access = self._ok(*self._archive("PATCH", f"{_STORE}/{access_id}",
                                             {"revoked": False, "expires_at": expires}))
            self._forget()
            logger.info("event=mcp_access_renewed kind=oauth access=%s expires=%s", access.get("name"), expires)
            return access, ""
        token = new_token()
        access = self._ok(*self._archive("PATCH", f"{_STORE}/{access_id}",
                                         {"token_hash": hash_token(token), "revoked": False}))
        self._forget()
        logger.info("event=mcp_access_renewed access=%s", access.get("name"))
        return access, token

    def delete(self, access_id: str) -> dict:
        out = self._ok(*self._archive("DELETE", f"{_STORE}/{access_id}"))
        self._forget()
        return out

    # ── the door ───────────────────────────────────────────────────────────
    def verify(self, token: str) -> tuple[dict | None, str]:
        """``(access, "")`` for a usable token, ``(None, why)`` otherwise (unknown | revoked | expired)."""
        token = str(token or "").strip()
        if not token.startswith((TOKEN_PREFIX, OAUTH_TOKEN_PREFIX)) or len(token) < 20:
            return None, "unknown"
        digest = hash_token(token)
        now = time.time()
        with self._lock:
            cached = self._cache.get(digest)
        if cached and now - cached[0] < self.cache_ttl:
            access = cached[1]
        else:
            status, payload = self._archive("GET", f"{_STORE}/by-hash/{digest}")
            if status >= 500:
                raise AccessError("Archive unavailable", 503)
            access = payload if status < 400 and isinstance(payload, dict) else None
            with self._lock:
                self._cache[digest] = (now, access)
        if access is None:
            return None, "unknown"
        ok, why = usable(access)
        return (access, "") if ok else (None, why)

    def touch(self, access: dict) -> None:
        """Last use + counters, in the background (a call never waits for it)."""
        def _run():
            try:
                self._archive("POST", f"{_STORE}/{access['access_id']}/used")
            except Exception as exc:  # noqa: BLE001
                logger.debug("event=mcp_access_touch_failed access=%s error=%s", access.get("name"), exc)
        threading.Thread(target=_run, daemon=True, name="mcp-access-touch").start()


class RateLimiter:
    """Calls per minute per access (sliding window, in memory)."""

    def __init__(self):
        self._calls: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, per_minute: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            window = self._calls.setdefault(key, deque())
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= max(1, int(per_minute)):
                return False
            window.append(now)
            return True
