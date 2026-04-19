"""Calendar item endpoints — provider-agnostic event / task / reminder store."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.post("/items", response_model=schemas.CalendarItemRead)
def upsert_calendar_item(
    item: schemas.CalendarItemCreate,
    db: Session = Depends(database.get_db),
):
    """Create or update a calendar item (keyed by external_id + source)."""
    if item.external_id:
        existing = db.query(models.CalendarItem).filter(
            models.CalendarItem.external_id == item.external_id,
            models.CalendarItem.source == item.source,
        ).first()
        if existing:
            for field, value in item.model_dump(exclude={"external_id", "source"}).items():
                setattr(existing, field, value)
            db.commit()
            db.refresh(existing)
            return existing
    db_item = models.CalendarItem(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/items", response_model=List[schemas.CalendarItemRead])
def list_calendar_items(
    source: Optional[str] = None,
    kind: Optional[str] = None,
    status_filter: Optional[str] = None,
    nag_enabled: Optional[bool] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(database.get_db),
):
    """List calendar items; supports time-window, source, kind, and nag filters."""
    q = db.query(models.CalendarItem)
    if source:
        q = q.filter(models.CalendarItem.source == source)
    if kind:
        q = q.filter(models.CalendarItem.kind == kind)
    if status_filter:
        q = q.filter(models.CalendarItem.status == status_filter)
    if nag_enabled is not None:
        q = q.filter(models.CalendarItem.nag_enabled == nag_enabled)
    if from_time:
        try:
            q = q.filter(models.CalendarItem.start_at >=
                         datetime.fromisoformat(from_time))
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid from_time: {from_time}")
    if to_time:
        try:
            q = q.filter(models.CalendarItem.start_at <=
                         datetime.fromisoformat(to_time))
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid to_time: {to_time}")
    return q.order_by(models.CalendarItem.start_at.asc()).limit(max(1, min(limit, 1000))).all()


@router.get("/items/{item_id}", response_model=schemas.CalendarItemRead)
def get_calendar_item(item_id: int, db: Session = Depends(database.get_db)):
    """Return a single calendar item by its primary key."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    return item


@router.patch("/items/{item_id}/nag", response_model=schemas.CalendarItemRead)
def update_calendar_item_nag(
    item_id: int,
    req: schemas.CalendarItemNagUpdate,
    db: Session = Depends(database.get_db),
):
    """Enable or disable proactive nag notifications for a calendar item."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    item.nag_enabled = req.nag_enabled
    db.commit()
    db.refresh(item)
    return item


@router.patch("/items/{item_id}/notified", response_model=schemas.CalendarItemRead)
def update_calendar_item_notified(
    item_id: int,
    req: schemas.CalendarItemNotifiedUpdate,
    db: Session = Depends(database.get_db),
):
    """Record the last notification bucket sent for a calendar item."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    item.last_notified_bucket = req.last_notified_bucket
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}")
def delete_calendar_item(item_id: int, db: Session = Depends(database.get_db)):
    """Delete a calendar item by its Archive primary key."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    db.delete(item)
    db.commit()
    return {"success": True}


@router.delete("/items/by-external/{source}/{external_id}")
def delete_calendar_item_by_external(
    source: str,
    external_id: str,
    db: Session = Depends(database.get_db),
):
    """Delete a calendar item by provider source + external_id."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.source == source,
        models.CalendarItem.external_id == external_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    db.delete(item)
    db.commit()
    return {"success": True}
