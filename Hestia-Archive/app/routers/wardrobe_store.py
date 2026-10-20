"""Wardrobe storage — rows with last-write-wins and a change cursor (same protocol as the Hercules store).

Archive only stores: what a kind means, validation, statistics and suggestions live in
Hestia-Wardrobe (SPEC docs/work/2026-10-17-modulo-guardaroba), the only caller.
"""
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import database, maintenance, models

router = APIRouter(prefix="/api/wardrobe-store", tags=["wardrobe"])

_MAX_LIMIT = 20000


class WardrobeRow(BaseModel):
    kind: str = Field(..., min_length=1, max_length=40)
    id: str = Field(..., min_length=1, max_length=80)
    parent_id: Optional[str] = None
    ref_id: Optional[str] = None
    at: Optional[datetime] = None
    data: dict = Field(default_factory=dict)
    updated_at: datetime
    deleted: bool = False


class WardrobeWrite(BaseModel):
    rows: List[WardrobeRow]


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def view(row: models.WardrobeRecord) -> dict:
    return {"kind": row.kind, "id": row.id, "parent_id": row.parent_id, "ref_id": row.ref_id,
            "at": row.at.isoformat() if row.at else None, "data": row.data or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "deleted": bool(row.deleted), "seq": int(row.seq or 0)}


def _next_seq(db: Session) -> int:
    return int(db.execute(text("SELECT nextval('wardrobe_records_seq')")).scalar())


@router.put("/records")
def write_records(req: WardrobeWrite, db: Session = Depends(database.get_db)):
    """Upsert rows. A row older than the stored one (``updated_at``) is not written and comes back in
    ``stale`` with the stored version, so writing the same row twice is harmless (idempotent sync)."""
    if len(req.rows) > 5000:
        raise HTTPException(status_code=413, detail="max 5000 rows per write")
    applied, stale = [], []
    for r in req.rows:
        incoming = _utc(r.updated_at)
        row = db.query(models.WardrobeRecord).filter(models.WardrobeRecord.kind == r.kind,
                                                     models.WardrobeRecord.id == r.id).first()
        if row is not None and row.updated_at and _utc(row.updated_at) > incoming:
            stale.append(view(row))
            continue
        if row is None:
            row = models.WardrobeRecord(kind=r.kind, id=r.id)
            db.add(row)
        row.parent_id, row.ref_id, row.at = r.parent_id, r.ref_id, _utc(r.at)
        row.data, row.updated_at, row.deleted = r.data or {}, incoming, bool(r.deleted)
        row.seq = _next_seq(db)
        db.flush()
        applied.append({"kind": row.kind, "id": row.id, "seq": int(row.seq)})
    db.commit()
    return {"applied": applied, "stale": stale, "cursor": _cursor(db)}


def _cursor(db: Session) -> int:
    return int(db.query(func.coalesce(func.max(models.WardrobeRecord.seq), 0)).scalar() or 0)


@router.get("/cursor")
def read_cursor(db: Session = Depends(database.get_db)):
    return {"cursor": _cursor(db), "epoch": maintenance.epoch()}


@router.get("/records")
def list_records(kind: Optional[str] = None, parent_id: Optional[str] = None, ref_id: Optional[str] = None,
                 ids: Optional[str] = None, at_from: Optional[datetime] = None, at_to: Optional[datetime] = None,
                 since_seq: Optional[int] = None, include_deleted: bool = False, order: str = "seq",
                 limit: int = 5000, db: Session = Depends(database.get_db)) -> dict:
    """Filtered rows. ``ids`` comma separated; ``order`` seq | at | -at; ``since_seq`` for sync pulls
    (tombstones included then, so clients learn about deletes)."""
    q = db.query(models.WardrobeRecord)
    if kind:
        kinds = [k for k in kind.split(",") if k]
        q = q.filter(models.WardrobeRecord.kind.in_(kinds))
    if parent_id:
        q = q.filter(models.WardrobeRecord.parent_id.in_([p for p in parent_id.split(",") if p]))
    if ref_id:
        q = q.filter(models.WardrobeRecord.ref_id.in_([p for p in ref_id.split(",") if p]))
    if ids:
        q = q.filter(models.WardrobeRecord.id.in_([p for p in ids.split(",") if p]))
    if at_from:
        q = q.filter(models.WardrobeRecord.at >= _utc(at_from))
    if at_to:
        q = q.filter(models.WardrobeRecord.at < _utc(at_to))
    if since_seq is not None:
        q = q.filter(models.WardrobeRecord.seq > since_seq)
    elif not include_deleted:
        q = q.filter(models.WardrobeRecord.deleted.is_(False))
    col = {"at": models.WardrobeRecord.at.asc().nulls_first(), "-at": models.WardrobeRecord.at.desc().nulls_last()
           }.get(order, models.WardrobeRecord.seq.asc())
    rows = q.order_by(col).limit(max(1, min(int(limit), _MAX_LIMIT))).all()
    return {"rows": [view(r) for r in rows], "cursor": _cursor(db), "epoch": maintenance.epoch()}
