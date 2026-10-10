"""Assistant presence storage — live signals, current snapshot, light change history.

Archive only stores: what a signal means, how states are evaluated and what they change live in
Chronos (the presence engine, SPEC docs/work/2026-10-10-assistant-presence), the only caller.
"""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(prefix="/api/presence-store", tags=["presence"])


def _signal_view(row: models.PresenceSignal) -> dict:
    return {"key": row.key, "value": row.value, "meta": row.meta or {},
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get("")
def load_all(db: Session = Depends(database.get_db)):
    """Everything Chronos needs at startup: unexpired signals + the last snapshot."""
    now = datetime.now(timezone.utc)
    db.query(models.PresenceSignal).filter(models.PresenceSignal.expires_at.isnot(None),
                                           models.PresenceSignal.expires_at < now).delete(
        synchronize_session=False)
    db.commit()
    snap = db.query(models.PresenceSnapshot).filter(models.PresenceSnapshot.id == 1).first()
    return {"signals": [_signal_view(r) for r in db.query(models.PresenceSignal).all()],
            "snapshot": snap.data if snap else None}


@router.put("/signals/{key}", response_model=schemas.PresenceSignalResponse)
def write_signal(key: str, req: schemas.PresenceSignalWrite, db: Session = Depends(database.get_db)):
    row = db.query(models.PresenceSignal).filter(models.PresenceSignal.key == key).first()
    if row:
        row.value, row.meta, row.expires_at = req.value, req.meta or {}, req.expires_at
    else:
        row = models.PresenceSignal(key=key, value=req.value, meta=req.meta or {}, expires_at=req.expires_at)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/signals/{key}")
def delete_signal(key: str, db: Session = Depends(database.get_db)):
    deleted = db.query(models.PresenceSignal).filter(models.PresenceSignal.key == key).delete(
        synchronize_session=False)
    db.commit()
    return {"status": "deleted" if deleted else "absent", "key": key}


@router.put("/snapshot")
def write_snapshot(req: schemas.PresenceSnapshotWrite, db: Session = Depends(database.get_db)):
    """Upsert the current state; ``change`` (when the state changed) goes to the history."""
    row = db.query(models.PresenceSnapshot).filter(models.PresenceSnapshot.id == 1).first()
    if row:
        row.data = req.data
    else:
        db.add(models.PresenceSnapshot(id=1, data=req.data))
    if req.change:
        db.add(models.PresenceChange(data=req.change))
        db.flush()
        keep = max(1, min(int(req.history_keep or 100), 1000))
        stale = (db.query(models.PresenceChange.id).order_by(models.PresenceChange.id.desc())
                 .offset(keep).all())
        if stale:
            db.query(models.PresenceChange).filter(
                models.PresenceChange.id.in_([r.id for r in stale])).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok"}


@router.get("/history")
def list_history(limit: int = 50, db: Session = Depends(database.get_db)) -> List[dict]:
    rows = (db.query(models.PresenceChange).order_by(models.PresenceChange.id.desc())
            .limit(max(1, min(limit, 500))).all())
    return [{**(r.data or {}), "at": r.created_at.isoformat() if r.created_at else None} for r in rows]
