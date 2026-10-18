"""Hercules (gym coach) storage — synced rows with last-write-wins and a global cursor.

Archive only stores: what a kind means, validation, records/statistics and the sync protocol live in
Hestia-Hercules (SPEC docs/work/2026-10-17-coach-module), the only caller.
"""
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import models, database

router = APIRouter(prefix="/api/hercules-store", tags=["hercules"])

_MAX_LIMIT = 20000


class HerculesRow(BaseModel):
    kind: str = Field(..., min_length=1, max_length=40)
    id: str = Field(..., min_length=1, max_length=80)
    parent_id: Optional[str] = None
    ref_id: Optional[str] = None
    at: Optional[datetime] = None
    data: dict = Field(default_factory=dict)
    updated_at: datetime
    deleted: bool = False


class HerculesWrite(BaseModel):
    rows: List[HerculesRow]


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def view(row: models.HerculesRecord) -> dict:
    return {"kind": row.kind, "id": row.id, "parent_id": row.parent_id, "ref_id": row.ref_id,
            "at": row.at.isoformat() if row.at else None, "data": row.data or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "deleted": bool(row.deleted), "seq": int(row.seq or 0)}


def _next_seq(db: Session) -> int:
    return int(db.execute(text("SELECT nextval('hercules_records_seq')")).scalar())


@router.put("/records")
def write_records(req: HerculesWrite, db: Session = Depends(database.get_db)):
    """Upsert rows. A row older than the stored one (``updated_at``) is not written and comes back in
    ``stale`` with the stored version, so writing the same row twice is harmless (idempotent sync)."""
    if len(req.rows) > 5000:
        raise HTTPException(status_code=413, detail="max 5000 rows per write")
    applied, stale = [], []
    for r in req.rows:
        incoming = _utc(r.updated_at)
        row = db.query(models.HerculesRecord).filter(models.HerculesRecord.kind == r.kind,
                                                     models.HerculesRecord.id == r.id).first()
        if row is not None and row.updated_at and _utc(row.updated_at) > incoming:
            stale.append(view(row))
            continue
        if row is None:
            row = models.HerculesRecord(kind=r.kind, id=r.id)
            db.add(row)
        row.parent_id, row.ref_id, row.at = r.parent_id, r.ref_id, _utc(r.at)
        row.data, row.updated_at, row.deleted = r.data or {}, incoming, bool(r.deleted)
        row.seq = _next_seq(db)
        db.flush()
        applied.append({"kind": row.kind, "id": row.id, "seq": int(row.seq)})
    db.commit()
    return {"applied": applied, "stale": stale, "cursor": _cursor(db)}


def _cursor(db: Session) -> int:
    return int(db.query(func.coalesce(func.max(models.HerculesRecord.seq), 0)).scalar() or 0)


@router.get("/cursor")
def read_cursor(db: Session = Depends(database.get_db)):
    return {"cursor": _cursor(db)}


@router.get("/records")
def list_records(kind: Optional[str] = None, parent_id: Optional[str] = None, ref_id: Optional[str] = None,
                 ids: Optional[str] = None, at_from: Optional[datetime] = None, at_to: Optional[datetime] = None,
                 since_seq: Optional[int] = None, include_deleted: bool = False, order: str = "seq",
                 limit: int = 5000, db: Session = Depends(database.get_db)) -> dict:
    """Filtered rows. ``ids`` comma separated; ``order`` seq | at | -at; ``since_seq`` for sync pulls
    (tombstones included then, so clients learn about deletes)."""
    q = db.query(models.HerculesRecord)
    if kind:
        kinds = [k for k in kind.split(",") if k]
        q = q.filter(models.HerculesRecord.kind.in_(kinds))
    if parent_id:
        q = q.filter(models.HerculesRecord.parent_id.in_([p for p in parent_id.split(",") if p]))
    if ref_id:
        q = q.filter(models.HerculesRecord.ref_id.in_([p for p in ref_id.split(",") if p]))
    if ids:
        q = q.filter(models.HerculesRecord.id.in_([p for p in ids.split(",") if p]))
    if at_from:
        q = q.filter(models.HerculesRecord.at >= _utc(at_from))
    if at_to:
        q = q.filter(models.HerculesRecord.at < _utc(at_to))
    if since_seq is not None:
        q = q.filter(models.HerculesRecord.seq > since_seq)
    elif not include_deleted:
        q = q.filter(models.HerculesRecord.deleted.is_(False))
    col = {"at": models.HerculesRecord.at.asc().nulls_first(), "-at": models.HerculesRecord.at.desc().nulls_last()
           }.get(order, models.HerculesRecord.seq.asc())
    rows = q.order_by(col).limit(max(1, min(int(limit), _MAX_LIMIT))).all()
    return {"rows": [view(r) for r in rows], "cursor": _cursor(db)}
