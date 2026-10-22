"""Generic module store router — rows with last-write-wins and a global cursor.

Same contract as ``hercules-store`` / ``selfcare-store`` / ``wardrobe-store`` (PUT/GET ``records``, GET
``cursor``), built once for every newer module (Plutus ``finance-store``, Iris ``iris-store``, reflection ``signals-store``,
Echo ``echo-store``).
Archive only stores: the owner module gives each ``kind`` its meaning.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import database, maintenance, models

_MAX_LIMIT = 20000


class StoreRow(BaseModel):
    kind: str = Field(..., min_length=1, max_length=40)
    id: str = Field(..., min_length=1, max_length=120)
    parent_id: Optional[str] = None
    ref_id: Optional[str] = None
    at: Optional[datetime] = None
    data: dict = Field(default_factory=dict)
    updated_at: datetime
    deleted: bool = False


class StoreWrite(BaseModel):
    rows: List[StoreRow]


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build_router(prefix: str, model, tag: str) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    def view(row) -> dict:
        return {"kind": row.kind, "id": row.id, "parent_id": row.parent_id, "ref_id": row.ref_id,
                "at": row.at.isoformat() if row.at else None, "data": row.data or {},
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "deleted": bool(row.deleted), "seq": int(row.seq or 0)}

    def cursor(db: Session) -> int:
        return int(db.query(func.coalesce(func.max(model.seq), 0)).scalar() or 0)

    @router.put("/records")
    def write_records(req: StoreWrite, db: Session = Depends(database.get_db)):
        """Upsert rows; an older row (``updated_at``) is not written and comes back in ``stale``."""
        if len(req.rows) > 5000:
            raise HTTPException(status_code=413, detail="max 5000 rows per write")
        applied, stale = [], []
        for r in req.rows:
            incoming = _utc(r.updated_at)
            row = db.query(model).filter(model.kind == r.kind, model.id == r.id).first()
            if row is not None and row.updated_at and _utc(row.updated_at) > incoming:
                stale.append(view(row))
                continue
            if row is None:
                row = model(kind=r.kind, id=r.id)
                db.add(row)
            row.parent_id, row.ref_id, row.at = r.parent_id, r.ref_id, _utc(r.at)
            row.data, row.updated_at, row.deleted = r.data or {}, incoming, bool(r.deleted)
            row.seq = int(db.execute(text(f"SELECT nextval('{model.SEQ_NAME}')")).scalar())
            db.flush()
            applied.append({"kind": row.kind, "id": row.id, "seq": int(row.seq)})
        db.commit()
        return {"applied": applied, "stale": stale, "cursor": cursor(db)}

    @router.get("/cursor")
    def read_cursor(db: Session = Depends(database.get_db)):
        return {"cursor": cursor(db), "epoch": maintenance.epoch()}

    @router.get("/records")
    def list_records(kind: Optional[str] = None, parent_id: Optional[str] = None, ref_id: Optional[str] = None,
                     ids: Optional[str] = None, at_from: Optional[datetime] = None,
                     at_to: Optional[datetime] = None, since_seq: Optional[int] = None,
                     include_deleted: bool = False, order: str = "seq", limit: int = 5000,
                     db: Session = Depends(database.get_db)) -> dict:
        """Filtered rows; ``since_seq`` for sync pulls (tombstones included)."""
        q = db.query(model)
        for col, value in ((model.kind, kind), (model.parent_id, parent_id), (model.ref_id, ref_id),
                           (model.id, ids)):
            if value:
                q = q.filter(col.in_([v for v in value.split(",") if v]))
        if at_from:
            q = q.filter(model.at >= _utc(at_from))
        if at_to:
            q = q.filter(model.at < _utc(at_to))
        if since_seq is not None:
            q = q.filter(model.seq > since_seq)
        elif not include_deleted:
            q = q.filter(model.deleted.is_(False))
        col = {"at": model.at.asc().nulls_first(), "-at": model.at.desc().nulls_last()}.get(order, model.seq.asc())
        rows = q.order_by(col).limit(max(1, min(int(limit), _MAX_LIMIT))).all()
        return {"rows": [view(r) for r in rows], "cursor": cursor(db), "epoch": maintenance.epoch()}

    return router


finance_router = build_router("/api/finance-store", models.FinanceRecord, "finance")
iris_router = build_router("/api/iris-store", models.IrisRecord, "iris")
echo_router = build_router("/api/echo-store", models.EchoRecord, "echo")
signals_router = build_router("/api/signals-store", models.SignalRecord, "signals")
