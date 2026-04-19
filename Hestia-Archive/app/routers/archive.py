"""Raw archive endpoints — ingest data lake for unevaluated records."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(prefix="/api/archive", tags=["archive"])


@router.post("", response_model=schemas.RecordResponse)
def save_record(record: schemas.RecordCreate, db: Session = Depends(database.get_db)):
    """Create a new raw archive record; return existing if reference_id matches."""
    if record.reference_id:
        existing = db.query(models.ArchiveRecord).filter(
            models.ArchiveRecord.reference_id == record.reference_id
        ).first()
        if existing:
            return existing
    db_record = models.ArchiveRecord(**record.model_dump())
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


@router.get("/{domain}/unevaluated")
def get_unevaluated(domain: str, db: Session = Depends(database.get_db)):
    """Return all unevaluated records for the given domain."""
    return db.query(models.ArchiveRecord).filter(
        models.ArchiveRecord.domain == domain,
        models.ArchiveRecord.is_evaluated == False,  # noqa: E712
    ).all()


@router.patch("/{record_id}", response_model=schemas.RecordResponse)
def update_record(
    record_id: int,
    update_data: schemas.RecordUpdate,
    db: Session = Depends(database.get_db),
):
    """Patch an archive record with an AI evaluation result."""
    db_record = db.query(models.ArchiveRecord).filter(
        models.ArchiveRecord.id == record_id
    ).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Record not found")
    current_payload = dict(db_record.payload)
    current_payload["ai_evaluation"] = update_data.evaluation
    db_record.payload = current_payload
    db_record.is_evaluated = True
    db.commit()
    db.refresh(db_record)
    return db_record
