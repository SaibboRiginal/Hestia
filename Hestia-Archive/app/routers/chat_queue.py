"""Chat queue storage — messages written while the brain (Oracle) was offline.

Archive only stores (SPEC docs/work/2026-10-19-cervello-offline §3): each chat client queues its own messages
when Oracle does not answer and replays them when Chronos tells it the brain is back. ``claim`` is a
compare-and-set ``queued → answering`` so two drains never answer the same message twice; an item left in
``answering`` by a crashed drain is claimable again after ``stale_seconds``.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, database

router = APIRouter(prefix="/api/chat-queue", tags=["chat-queue"])

STATES = ("queued", "answering", "answered", "failed")


class QueueCreate(BaseModel):
    client: str = Field(..., min_length=1, max_length=40)
    session_id: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=20000)
    target: Optional[str] = Field(None, max_length=200)
    client_ref: Optional[str] = Field(None, max_length=200)
    meta: dict = Field(default_factory=dict)


class QueueDone(BaseModel):
    ok: bool = True
    detail: Optional[str] = Field(None, max_length=500)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def view(row: models.ChatQueueItem) -> dict:
    return {"id": row.id, "client": row.client, "session_id": row.session_id, "target": row.target,
            "client_ref": row.client_ref, "text": row.text, "meta": row.meta or {}, "state": row.state,
            "attempts": int(row.attempts or 0), "detail": row.detail, "created_at": _iso(row.created_at),
            "answered_at": _iso(row.answered_at)}


def _get(db: Session, item_id: int) -> models.ChatQueueItem:
    row = db.query(models.ChatQueueItem).filter(models.ChatQueueItem.id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.post("")
def enqueue(req: QueueCreate, db: Session = Depends(database.get_db)):
    row = models.ChatQueueItem(client=req.client, session_id=req.session_id, text=req.text, target=req.target,
                               client_ref=req.client_ref, meta=req.meta or {}, state="queued", attempts=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    waiting = db.query(models.ChatQueueItem).filter(models.ChatQueueItem.client == req.client,
                                                    models.ChatQueueItem.state.in_(("queued", "answering"))).count()
    return {**view(row), "position": waiting}


@router.get("")
def list_items(client: Optional[str] = None, state: Optional[str] = "queued", limit: int = 100,
               db: Session = Depends(database.get_db)):
    """Oldest first (answer order)."""
    q = db.query(models.ChatQueueItem)
    if client:
        q = q.filter(models.ChatQueueItem.client == client)
    if state:
        q = q.filter(models.ChatQueueItem.state == state)
    rows = q.order_by(models.ChatQueueItem.id.asc()).limit(max(1, min(limit, 500))).all()
    return {"items": [view(r) for r in rows]}


@router.get("/counts")
def counts(db: Session = Depends(database.get_db)):
    """Waiting messages per client (queued + answering)."""
    rows = db.query(models.ChatQueueItem.client).filter(
        models.ChatQueueItem.state.in_(("queued", "answering"))).all()
    out: dict[str, int] = {}
    for (client,) in rows:
        out[client] = out.get(client, 0) + 1
    return {"waiting": out, "total": sum(out.values())}


@router.post("/{item_id}/claim")
def claim(item_id: int, stale_seconds: int = 600, db: Session = Depends(database.get_db)):
    """Compare-and-set queued → answering; 409 when someone else holds it."""
    row = _get(db, item_id)
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=max(30, stale_seconds))
    q = db.query(models.ChatQueueItem).filter(models.ChatQueueItem.id == item_id)
    if row.state == "answering":
        claimed_at = row.answered_at
        if claimed_at is not None and claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        if claimed_at is None or claimed_at > stale_before:
            raise HTTPException(status_code=409, detail="already_claimed")
        q = q.filter(models.ChatQueueItem.state == "answering")
    else:
        q = q.filter(models.ChatQueueItem.state == "queued")
    # answered_at doubles as "claimed at" while answering.
    changed = q.update({"state": "answering", "attempts": int(row.attempts or 0) + 1, "answered_at": now},
                       synchronize_session=False)
    db.commit()
    if not changed:
        raise HTTPException(status_code=409, detail="already_claimed")
    db.refresh(row)
    return view(row)


@router.post("/{item_id}/done")
def done(item_id: int, req: QueueDone, db: Session = Depends(database.get_db)):
    """ok → answered; not ok → back to queued (answered again at the next drain), failed after 5 attempts."""
    row = _get(db, item_id)
    if req.ok:
        row.state = "answered"
        row.answered_at = datetime.now(timezone.utc)
    else:
        row.state = "failed" if int(row.attempts or 0) >= 5 else "queued"
        row.answered_at = None
    row.detail = req.detail
    db.commit()
    db.refresh(row)
    return view(row)
