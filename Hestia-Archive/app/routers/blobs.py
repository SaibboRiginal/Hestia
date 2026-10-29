"""Blob store — binary files (photos and their thumbnails) for any module.

Archive only stores bytes + content type + the owner's free ``meta``; resizing, which blobs form one photo and
when to delete them is the owner module's job (first user: Hestia-Wardrobe, SPEC
docs/work/2026-10-17-modulo-guardaroba §4.6). Bodies are JSON with base64, since Hub envelopes carry JSON only.
"""
import base64
import binascii
import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, database

router = APIRouter(prefix="/api/blobs", tags=["blobs"])

_MAX_MB = 15.0                    # hard safety cap per blob; modules enforce their own (Themis) limit below it


class BlobWrite(BaseModel):
    owner_module: str = Field(..., min_length=1, max_length=40)
    content_type: str = Field(..., min_length=3, max_length=120)
    data_base64: str = Field(..., min_length=1)
    meta: Optional[dict] = None


def _meta(row: models.BlobRecord) -> dict:
    return {"blob_id": row.blob_id, "owner_module": row.owner_module, "content_type": row.content_type,
            "size": row.size, "sha256": row.sha256, "meta": row.meta or {},
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _get(db: Session, blob_id: str) -> models.BlobRecord:
    row = db.query(models.BlobRecord).filter(models.BlobRecord.blob_id == blob_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="blob not found")
    return row


@router.post("")
def store_blob(req: BlobWrite, db: Session = Depends(database.get_db)):
    """Store a file; the same bytes for the same module return the existing blob (``deduped: true``)."""
    try:
        raw = base64.b64decode(req.data_base64.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="data_base64 is not valid base64")
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > _MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"file larger than {_MAX_MB:g} MB")
    digest = hashlib.sha256(raw).hexdigest()
    owner = req.owner_module.strip().lower()
    existing = db.query(models.BlobRecord).filter(models.BlobRecord.owner_module == owner,
                                                  models.BlobRecord.sha256 == digest).first()
    if existing:
        return {**_meta(existing), "deduped": True}
    row = models.BlobRecord(blob_id=uuid.uuid4().hex, owner_module=owner, content_type=req.content_type.strip().lower(),
                            size=len(raw), sha256=digest, data=raw, meta=req.meta or {})
    db.add(row)
    db.commit()
    db.refresh(row)
    return {**_meta(row), "deduped": False}


@router.get("")
def list_blobs(owner_module: str, limit: int = 500, db: Session = Depends(database.get_db)):
    rows = (db.query(models.BlobRecord).filter(models.BlobRecord.owner_module == owner_module.strip().lower())
            .order_by(models.BlobRecord.created_at.desc()).limit(max(1, min(int(limit), 5000))).all())
    return {"items": [_meta(r) for r in rows], "total_bytes": sum(r.size for r in rows)}


@router.get("/usage")
def storage_usage(db: Session = Depends(database.get_db)):
    """Size of the database and of the blobs per module — read by the stack monitor for growth alerts
    (Cindy 25, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W3). Read only, no row data."""
    from sqlalchemy import func as sa_func, text
    rows = (db.query(models.BlobRecord.owner_module, sa_func.count(models.BlobRecord.blob_id),
                     sa_func.coalesce(sa_func.sum(models.BlobRecord.size), 0))
            .group_by(models.BlobRecord.owner_module).all())
    by_module = {str(m): {"count": int(c), "bytes": int(b)} for m, c, b in rows}
    try:
        db_bytes = int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
    except Exception:  # noqa: BLE001 — not Postgres (tests): size unknown
        db.rollback()
        db_bytes = None
    return {"database_bytes": db_bytes, "blob_bytes": sum(v["bytes"] for v in by_module.values()),
            "blob_count": sum(v["count"] for v in by_module.values()), "blobs_by_module": by_module}


@router.get("/{blob_id}/meta")
def blob_meta(blob_id: str, db: Session = Depends(database.get_db)):
    return _meta(_get(db, blob_id))


@router.get("/{blob_id}/base64")
def blob_base64(blob_id: str, db: Session = Depends(database.get_db)):
    """Bytes as base64 JSON — what a module reads through Hub (envelopes are JSON)."""
    row = _get(db, blob_id)
    return {"blob_id": row.blob_id, "mime": row.content_type, "data_b64": base64.b64encode(row.data).decode()}


@router.get("/{blob_id}")
def blob_bytes(blob_id: str, db: Session = Depends(database.get_db)):
    row = _get(db, blob_id)
    return Response(content=row.data, media_type=row.content_type,
                    headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.delete("/{blob_id}")
def delete_blob(blob_id: str, db: Session = Depends(database.get_db)):
    deleted = db.query(models.BlobRecord).filter(models.BlobRecord.blob_id == blob_id).delete(synchronize_session=False)
    db.commit()
    return {"status": "deleted" if deleted else "absent", "blob_id": blob_id}
