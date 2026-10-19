"""MCP access storage — who may use Hestia's MCP from outside (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B6).

Archive only stores: scopes, tool lists, expiry and the token check live in Hestia-MCP, the only caller.
Tokens arrive already hashed; no endpoint returns a hash. OAuth (kind ``oauth``): self-registered clients, one-time
authorization codes and rotating refresh tokens, all as hashes; the protocol itself lives in Hestia-MCP.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, database

router = APIRouter(prefix="/api/mcp-access-store", tags=["mcp-access"])


class AccessCreate(BaseModel):
    access_id: str = Field(..., min_length=4, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    kind: str = Field("token", max_length=20)
    scope: str = Field("read", max_length=20)
    tools: List[str] = Field(default_factory=list)
    token_hash: Optional[str] = Field(None, max_length=128)
    expires_at: Optional[datetime] = None
    meta: dict = Field(default_factory=dict)
    client_id: Optional[str] = Field(None, max_length=64)
    refresh_hash: Optional[str] = Field(None, max_length=128)
    token_expires_at: Optional[datetime] = None


class AccessPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    scope: Optional[str] = Field(None, max_length=20)
    tools: Optional[List[str]] = None
    token_hash: Optional[str] = Field(None, max_length=128)
    expires_at: Optional[datetime] = None
    clear_expiry: bool = False
    revoked: Optional[bool] = None
    meta: Optional[dict] = None


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def view(row: models.MCPAccess) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    return {"access_id": row.access_id, "name": row.name, "kind": row.kind, "scope": row.scope,
            "tools": list(row.tools or []), "expires_at": _iso(row.expires_at), "revoked_at": _iso(row.revoked_at),
            "last_used_at": _iso(row.last_used_at), "calls_today": int(row.calls_day or 0) if row.calls_date == today else 0,
            "calls_total": int(row.calls_total or 0), "meta": row.meta or {}, "created_at": _iso(row.created_at),
            "client_id": row.client_id, "token_expires_at": _iso(row.token_expires_at)}


def _get(db: Session, access_id: str) -> models.MCPAccess:
    row = db.query(models.MCPAccess).filter(models.MCPAccess.access_id == access_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="access not found")
    return row


@router.get("/accesses")
def list_accesses(db: Session = Depends(database.get_db)) -> dict:
    rows = db.query(models.MCPAccess).order_by(models.MCPAccess.created_at.desc()).all()
    return {"accesses": [view(r) for r in rows]}


@router.post("/accesses")
def create_access(req: AccessCreate, db: Session = Depends(database.get_db)) -> dict:
    if db.query(models.MCPAccess).filter(models.MCPAccess.access_id == req.access_id).first():
        raise HTTPException(status_code=409, detail="access id already used")
    row = models.MCPAccess(access_id=req.access_id, name=req.name, kind=req.kind, scope=req.scope,
                           tools=req.tools, token_hash=req.token_hash, expires_at=req.expires_at, meta=req.meta,
                           client_id=req.client_id, refresh_hash=req.refresh_hash,
                           token_expires_at=req.token_expires_at, calls_day=0, calls_total=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return view(row)


@router.get("/accesses/by-hash/{token_hash}")
def access_by_hash(token_hash: str, db: Session = Depends(database.get_db)) -> dict:
    row = db.query(models.MCPAccess).filter(models.MCPAccess.token_hash == token_hash).first()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown token")
    return view(row)


@router.patch("/accesses/{access_id}")
def patch_access(access_id: str, req: AccessPatch, db: Session = Depends(database.get_db)) -> dict:
    row = _get(db, access_id)
    for field in ("name", "scope", "tools", "token_hash", "meta"):
        value = getattr(req, field)
        if value is not None:
            setattr(row, field, value)
    if req.expires_at is not None:
        row.expires_at = req.expires_at
    elif req.clear_expiry:
        row.expires_at = None
    if req.revoked is not None:
        row.revoked_at = datetime.now(timezone.utc) if req.revoked else None
    db.commit()
    db.refresh(row)
    return view(row)


@router.post("/accesses/{access_id}/used")
def mark_used(access_id: str, db: Session = Depends(database.get_db)) -> dict:
    """One call made with this access: last use + counters (today, total)."""
    row = _get(db, access_id)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    row.calls_day = (int(row.calls_day or 0) if row.calls_date == today else 0) + 1
    row.calls_date = today
    row.calls_total = int(row.calls_total or 0) + 1
    row.last_used_at = now
    db.commit()
    return {"status": "ok", "calls_today": row.calls_day}


@router.delete("/accesses/{access_id}")
def delete_access(access_id: str, db: Session = Depends(database.get_db)) -> dict:
    deleted = db.query(models.MCPAccess).filter(models.MCPAccess.access_id == access_id).delete(
        synchronize_session=False)
    db.commit()
    return {"status": "deleted" if deleted else "absent", "access_id": access_id}


# ── OAuth (kind oauth) ───────────────────────────────────────────────────────

class RotateBody(BaseModel):
    old_refresh_hash: str = Field(..., max_length=128)
    token_hash: str = Field(..., max_length=128)
    refresh_hash: str = Field(..., max_length=128)
    token_expires_at: datetime


class ClientCreate(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    client_name: str = Field(..., min_length=1, max_length=80)
    redirect_uris: List[str] = Field(..., min_length=1, max_length=10)
    auth_method: str = Field("none", max_length=32)
    secret_hash: Optional[str] = Field(None, max_length=128)
    meta: dict = Field(default_factory=dict)


class SecretCheck(BaseModel):
    secret_hash: str = Field(..., max_length=128)


class CodeCreate(BaseModel):
    code_hash: str = Field(..., max_length=128)
    client_id: str = Field(..., max_length=64)
    redirect_uri: str = Field(..., max_length=2000)
    code_challenge: str = Field(..., max_length=128)
    scope: str = Field("read", max_length=20)
    tools: List[str] = Field(default_factory=list)
    name: str = Field(..., min_length=1, max_length=80)
    expires_days: Optional[int] = None
    resource: Optional[str] = Field(None, max_length=2000)
    expires_at: datetime


class CodeConsume(BaseModel):
    code_hash: str = Field(..., max_length=128)
    access_id: str = Field(..., max_length=64)


@router.get("/accesses/by-refresh/{refresh_hash}")
def access_by_refresh(refresh_hash: str, db: Session = Depends(database.get_db)) -> dict:
    """The access of a refresh token. ``reused: true`` = it is the *previous* refresh token (already rotated): a
    replay, the caller revokes the access."""
    row = db.query(models.MCPAccess).filter(models.MCPAccess.refresh_hash == refresh_hash).first()
    if row is not None:
        return {**view(row), "reused": False}
    row = db.query(models.MCPAccess).filter(models.MCPAccess.prev_refresh_hash == refresh_hash).first()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown refresh token")
    return {**view(row), "reused": True}


@router.post("/accesses/{access_id}/rotate")
def rotate_tokens(access_id: str, req: RotateBody, db: Session = Depends(database.get_db)) -> dict:
    """New access + refresh token in one step, only if ``old_refresh_hash`` is still the current one (two refreshes
    racing: the second gets 409)."""
    updated = db.query(models.MCPAccess).filter(
        models.MCPAccess.access_id == access_id, models.MCPAccess.refresh_hash == req.old_refresh_hash,
    ).update({"token_hash": req.token_hash, "refresh_hash": req.refresh_hash,
              "prev_refresh_hash": req.old_refresh_hash, "token_expires_at": req.token_expires_at},
             synchronize_session=False)
    db.commit()
    if not updated:
        raise HTTPException(status_code=409, detail="refresh token already rotated")
    return view(_get(db, access_id))


def client_view(row: models.MCPOAuthClient) -> dict:
    return {"client_id": row.client_id, "client_name": row.client_name, "redirect_uris": list(row.redirect_uris or []),
            "auth_method": row.auth_method, "has_secret": bool(row.secret_hash), "meta": row.meta or {},
            "last_used_at": _iso(row.last_used_at), "created_at": _iso(row.created_at)}


def _client(db: Session, client_id: str) -> models.MCPOAuthClient:
    row = db.query(models.MCPOAuthClient).filter(models.MCPOAuthClient.client_id == client_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="client not found")
    return row


@router.get("/oauth/clients")
def list_clients(db: Session = Depends(database.get_db)) -> dict:
    rows = db.query(models.MCPOAuthClient).order_by(models.MCPOAuthClient.created_at.desc()).all()
    return {"clients": [client_view(r) for r in rows]}


@router.post("/oauth/clients")
def create_client(req: ClientCreate, db: Session = Depends(database.get_db)) -> dict:
    if db.query(models.MCPOAuthClient).filter(models.MCPOAuthClient.client_id == req.client_id).first():
        raise HTTPException(status_code=409, detail="client id already used")
    row = models.MCPOAuthClient(client_id=req.client_id, client_name=req.client_name, redirect_uris=req.redirect_uris,
                                auth_method=req.auth_method, secret_hash=req.secret_hash, meta=req.meta)
    db.add(row)
    db.commit()
    db.refresh(row)
    return client_view(row)


@router.get("/oauth/clients/{client_id}")
def get_client(client_id: str, db: Session = Depends(database.get_db)) -> dict:
    return client_view(_client(db, client_id))


@router.post("/oauth/clients/{client_id}/check-secret")
def check_client_secret(client_id: str, req: SecretCheck, db: Session = Depends(database.get_db)) -> dict:
    """Does this hash match the client's secret? (the hash itself never leaves Archive)."""
    import hmac
    row = _client(db, client_id)
    ok = bool(row.secret_hash) and hmac.compare_digest(str(row.secret_hash), req.secret_hash)
    if ok:
        row.last_used_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": ok}


@router.delete("/oauth/clients/{client_id}")
def delete_client(client_id: str, db: Session = Depends(database.get_db)) -> dict:
    deleted = db.query(models.MCPOAuthClient).filter(models.MCPOAuthClient.client_id == client_id).delete(
        synchronize_session=False)
    db.commit()
    return {"status": "deleted" if deleted else "absent", "client_id": client_id}


@router.post("/oauth/codes")
def create_code(req: CodeCreate, db: Session = Depends(database.get_db)) -> dict:
    # Codes live minutes: drop the ones older than a day while we are here (used or not).
    db.query(models.MCPOAuthCode).filter(
        models.MCPOAuthCode.expires_at < datetime.now(timezone.utc) - timedelta(days=1)).delete(synchronize_session=False)
    row = models.MCPOAuthCode(**req.model_dump())
    db.add(row)
    db.commit()
    return {"status": "ok", "client_id": req.client_id, "expires_at": _iso(req.expires_at)}


@router.post("/oauth/codes/consume")
def consume_code(req: CodeConsume, db: Session = Depends(database.get_db)) -> dict:
    """Use a code once. First use: marks it used for ``access_id`` → the code's data, ``reused: false``. A second use
    → ``reused: true`` and the ``access_id`` it became (the caller revokes it: a stolen code was replayed)."""
    now = datetime.now(timezone.utc)
    updated = db.query(models.MCPOAuthCode).filter(
        models.MCPOAuthCode.code_hash == req.code_hash, models.MCPOAuthCode.used_at.is_(None),
    ).update({"used_at": now, "access_id": req.access_id}, synchronize_session=False)
    db.commit()
    row = db.query(models.MCPOAuthCode).filter(models.MCPOAuthCode.code_hash == req.code_hash).first()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown code")
    return {"reused": not updated, "access_id": row.access_id, "client_id": row.client_id,
            "redirect_uri": row.redirect_uri, "code_challenge": row.code_challenge, "scope": row.scope,
            "tools": list(row.tools or []), "name": row.name, "expires_days": row.expires_days,
            "resource": row.resource, "expires_at": _iso(row.expires_at)}
