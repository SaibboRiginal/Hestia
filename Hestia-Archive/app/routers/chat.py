"""Chat history endpoints — short-term conversational memory."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/history/all")
def get_all_chat_history(db: Session = Depends(database.get_db)):
    """Return every stored chat message ordered by recency."""
    return (
        db.query(models.ChatHistory)
        .order_by(models.ChatHistory.timestamp.desc())
        .all()
    )


@router.delete("/history/all")
def nuke_all_chat_history(db: Session = Depends(database.get_db)):
    """Delete all chat history records."""
    deleted = db.query(models.ChatHistory).delete()
    db.commit()
    return {"status": "success", "deleted_messages": deleted}


@router.post("/history", response_model=schemas.ChatMessageResponse)
def save_chat_message(
    message: schemas.ChatMessageCreate, db: Session = Depends(database.get_db)
):
    """Persist a single chat message."""
    db_msg = models.ChatHistory(**message.model_dump())
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)
    return db_msg


@router.get("/history/{session_id}", response_model=List[schemas.ChatMessageResponse])
def get_chat_session(
    session_id: str, limit: int = 20, db: Session = Depends(database.get_db)
):
    """Return the last *limit* messages for a session in chronological order."""
    messages = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.session_id == session_id)
        .order_by(models.ChatHistory.timestamp.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(messages))


@router.delete("/history/{session_id}")
def delete_chat_history(session_id: str, db: Session = Depends(database.get_db)):
    """Delete all messages belonging to *session_id*."""
    deleted = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.session_id == session_id)
        .delete()
    )
    db.commit()
    return {"status": "success", "deleted_messages": deleted}
