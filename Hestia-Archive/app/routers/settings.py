"""Settings storage — generic values, light history, pending proposals.

Archive only stores: what a setting means, its validation and who may change it
live in Themis (the settings module), which is the only caller of these routes.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(prefix="/api/settings-store", tags=["settings"])


def _value_query(db: Session, key: str, scope: str, scope_id: str):
    return db.query(models.SettingValue).filter(
        models.SettingValue.key == key, models.SettingValue.scope == scope,
        models.SettingValue.scope_id == (scope_id or ""))


def _log_history(db: Session, key: str, scope: str, scope_id: str, old, new, actor, reason, keep: int) -> None:
    db.add(models.SettingHistory(key=key, scope=scope, scope_id=scope_id or "", old_value=old,
                                 new_value=new, actor=actor, reason=reason))
    db.flush()
    keep = max(1, min(int(keep or 10), 100))
    stale = (db.query(models.SettingHistory.id)
             .filter(models.SettingHistory.key == key, models.SettingHistory.scope == scope,
                     models.SettingHistory.scope_id == (scope_id or ""))
             .order_by(models.SettingHistory.id.desc()).offset(keep).all())
    if stale:
        db.query(models.SettingHistory).filter(
            models.SettingHistory.id.in_([row.id for row in stale])).delete(synchronize_session=False)


@router.get("/values", response_model=List[schemas.SettingValueResponse])
def list_values(key: Optional[str] = None, prefix: Optional[str] = None, scope: Optional[str] = None,
                scope_id: Optional[str] = None, db: Session = Depends(database.get_db)):
    q = db.query(models.SettingValue)
    if key:
        q = q.filter(models.SettingValue.key == key)
    if prefix:
        q = q.filter(models.SettingValue.key.like(f"{prefix}%"))
    if scope:
        q = q.filter(models.SettingValue.scope == scope)
    if scope_id is not None:
        q = q.filter(models.SettingValue.scope_id == scope_id)
    return q.order_by(models.SettingValue.key).limit(5000).all()


@router.put("/values", response_model=schemas.SettingValueResponse)
def write_value(req: schemas.SettingValueWrite, db: Session = Depends(database.get_db)):
    """Upsert one value and log the change (old → new) in the same transaction."""
    row = _value_query(db, req.key, req.scope, req.scope_id).first()
    old = row.value if row else None
    if row:
        row.value = req.value
        row.updated_by = req.actor
    else:
        row = models.SettingValue(key=req.key, scope=req.scope, scope_id=req.scope_id or "",
                                  value=req.value, updated_by=req.actor)
        db.add(row)
    _log_history(db, req.key, req.scope, req.scope_id, old, req.value, req.actor, req.reason, req.history_keep)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/values")
def delete_value(key: str, scope: str = "system", scope_id: str = "", actor: Optional[str] = None,
                 reason: Optional[str] = None, history_keep: int = 10, db: Session = Depends(database.get_db)):
    """Remove a stored value (back to the default); logged as old → null."""
    row = _value_query(db, key, scope, scope_id).first()
    if not row:
        return {"status": "absent", "key": key}
    _log_history(db, key, scope, scope_id, row.value, None, actor, reason or "reset", history_keep)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "key": key}


@router.get("/history", response_model=List[schemas.SettingHistoryResponse])
def list_history(key: Optional[str] = None, scope: Optional[str] = None, scope_id: Optional[str] = None,
                 actor: Optional[str] = None, limit: int = 50, db: Session = Depends(database.get_db)):
    q = db.query(models.SettingHistory)
    if key:
        q = q.filter(models.SettingHistory.key == key)
    if scope:
        q = q.filter(models.SettingHistory.scope == scope)
    if scope_id is not None:
        q = q.filter(models.SettingHistory.scope_id == scope_id)
    if actor:
        q = q.filter(models.SettingHistory.actor == actor)
    return q.order_by(models.SettingHistory.id.desc()).limit(max(1, min(limit, 500))).all()


@router.post("/proposals", response_model=schemas.SettingProposalResponse)
def create_proposal(req: schemas.SettingProposalCreate, db: Session = Depends(database.get_db)):
    if db.query(models.SettingProposal).filter(models.SettingProposal.proposal_id == req.proposal_id).first():
        raise HTTPException(status_code=409, detail="proposal_id already exists")
    row = models.SettingProposal(**req.model_dump(), status="pending")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/proposals", response_model=List[schemas.SettingProposalResponse])
def list_proposals(status: Optional[str] = None, key: Optional[str] = None, proposal_id: Optional[str] = None,
                   limit: int = 100, db: Session = Depends(database.get_db)):
    q = db.query(models.SettingProposal)
    if status:
        q = q.filter(models.SettingProposal.status == status)
    if key:
        q = q.filter(models.SettingProposal.key == key)
    if proposal_id:
        q = q.filter(models.SettingProposal.proposal_id == proposal_id)
    return q.order_by(models.SettingProposal.id.desc()).limit(max(1, min(limit, 500))).all()


@router.patch("/proposals/{proposal_id}", response_model=schemas.SettingProposalResponse)
def update_proposal(proposal_id: str, req: schemas.SettingProposalUpdate, db: Session = Depends(database.get_db)):
    """Close a proposal. ``only_if_status`` makes the first answer win (409 for later ones)."""
    row = (db.query(models.SettingProposal)
           .filter(models.SettingProposal.proposal_id == proposal_id).with_for_update().first())
    if not row:
        raise HTTPException(status_code=404, detail="proposal not found")
    if req.only_if_status and row.status != req.only_if_status:
        raise HTTPException(status_code=409, detail=f"proposal already {row.status}")
    row.status = req.status
    row.decided_by = req.decided_by
    row.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row
