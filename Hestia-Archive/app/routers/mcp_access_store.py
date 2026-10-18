"""MCP access storage — who may use Hestia's MCP from outside (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B6).

Archive only stores: scopes, tool lists, expiry and the token check live in Hestia-MCP, the only caller.
Tokens arrive already hashed; no endpoint returns a hash.
"""
from datetime import datetime, timezone
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
            "calls_total": int(row.calls_total or 0), "meta": row.meta or {}, "created_at": _iso(row.created_at)}


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
                           calls_day=0, calls_total=0)
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
