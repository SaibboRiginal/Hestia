"""Chat history endpoints — short-term conversational memory."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
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


@router.get("/sessions")
def list_chat_sessions(since: Optional[str] = None, db: Session = Depends(database.get_db)):
    """Distinct session ids with messages since *since* (ISO datetime)."""
    q = db.query(models.ChatHistory.session_id).distinct()
    if since:
        try:
            q = q.filter(models.ChatHistory.timestamp >= datetime.fromisoformat(since.replace("Z", "+00:00")))
        except ValueError:
            pass
    return {"sessions": [row[0] for row in q.all() if row[0]]}


TAG_COLORS = ("gray", "red", "orange", "yellow", "green", "teal", "blue", "purple", "pink")
MAX_TAGS = 6


def _when(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean_tags(raw) -> list[dict]:
    out, seen = [], set()
    for t in raw if isinstance(raw, list) else []:
        name = str((t.get("name") if isinstance(t, dict) else t) or "").strip().lower()[:24]
        color = str(t.get("color") or "") if isinstance(t, dict) else ""
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "color": color if color in TAG_COLORS else TAG_COLORS[len(seen) % len(TAG_COLORS)]})
    return out[:MAX_TAGS]


def _meta_out(m: Optional[models.ChatSessionMeta]) -> dict:
    return {"title": (m.title if m else None) or None, "tags": (m.tags if m else None) or [],
            "pinned": bool(m.pinned) if m else False}


@router.get("/sessions/list")
def list_chat_sessions_rich(q: str = "", tag: str = "", since: Optional[str] = None, until: Optional[str] = None,
                            pinned: Optional[bool] = None, limit: int = 30, offset: int = 0,
                            db: Session = Depends(database.get_db)):
    """Conversations, newest first (Cindy 26 + WebUI history): title (own or first message), first/last time,
    message count, tags, pinned. ``q`` searches titles and messages, ``tag`` keeps one tag, ``since``/``until``
    bound the last message."""
    H = models.ChatHistory
    rows = db.query(H.session_id, func.min(H.timestamp), func.max(H.timestamp), func.count(H.id)).group_by(H.session_id)
    if q.strip():
        like = f"%{q.strip()}%"
        ids = {r[0] for r in db.query(H.session_id).filter(H.content.ilike(like)).distinct().all()}
        ids |= {r[0] for r in db.query(models.ChatSessionMeta.session_id).filter(models.ChatSessionMeta.title.ilike(like)).all()}
        rows = rows.filter(H.session_id.in_(list(ids) or [""]))
    lo, hi = _when(since), _when(until)
    if lo:
        rows = rows.having(func.max(H.timestamp) >= lo)
    if hi:
        rows = rows.having(func.max(H.timestamp) <= hi)
    sessions = [r for r in rows.all() if r[0]]
    metas = {m.session_id: m for m in db.query(models.ChatSessionMeta).filter(
        models.ChatSessionMeta.session_id.in_([r[0] for r in sessions])).all()} if sessions else {}
    want = tag.strip().lower()
    items = []
    for sid, first, last, count in sessions:
        meta = _meta_out(metas.get(sid))
        if want and not any(t.get("name") == want for t in meta["tags"]):
            continue
        if pinned is not None and meta["pinned"] != pinned:
            continue
        items.append({"session_id": sid, "first_at": first.isoformat() if first else None,
                      "last_at": last.isoformat() if last else None, "messages": count, **meta})
    items.sort(key=lambda i: (i["pinned"], i["last_at"] or ""), reverse=True)
    page = items[max(0, offset):max(0, offset) + max(1, min(limit, 100))]
    untitled = [i["session_id"] for i in page if not i["title"]]
    if untitled:
        firsts = {}
        for sid, content in (db.query(H.session_id, H.content).filter(H.session_id.in_(untitled), H.role == "user")
                             .order_by(H.timestamp.asc()).all()):
            firsts.setdefault(sid, content)
        for i in page:
            if not i["title"]:
                i["title"] = " ".join(str(firsts.get(i["session_id"]) or "Conversazione").split())[:70]
    return {"items": page, "total": len(items)}


@router.get("/sessions/tags")
def list_chat_tags(db: Session = Depends(database.get_db)):
    """Every tag in use, with its colour and how many conversations carry it."""
    counts: dict[str, dict] = {}
    for m in db.query(models.ChatSessionMeta).all():
        for t in m.tags or []:
            c = counts.setdefault(t.get("name"), {"name": t.get("name"), "color": t.get("color"), "count": 0})
            c["count"] += 1
    return {"items": sorted(counts.values(), key=lambda t: (-t["count"], t["name"] or "")), "colors": list(TAG_COLORS)}


@router.put("/sessions/{session_id}/meta")
def set_chat_session_meta(session_id: str, body: dict = Body(...), db: Session = Depends(database.get_db)):
    """Title, tags (replace, or ``add_tags`` / ``remove_tags``), pinned. Returns the meta and the previous one
    (so a client can undo)."""
    if not session_id.strip():
        raise HTTPException(status_code=422, detail="session_id required")
    m = db.get(models.ChatSessionMeta, session_id)
    before = _meta_out(m)
    if m is None:
        m = models.ChatSessionMeta(session_id=session_id, tags=[], pinned=False)
        db.add(m)
    if "title" in body:
        m.title = (str(body.get("title") or "").strip()[:120]) or None
    tags = list(m.tags or [])
    if "tags" in body:
        tags = _clean_tags(body.get("tags"))
    if body.get("add_tags"):
        tags = _clean_tags(tags + [t for t in body["add_tags"]])
    if body.get("remove_tags"):
        drop = {str(t.get("name") if isinstance(t, dict) else t).strip().lower() for t in body["remove_tags"]}
        tags = [t for t in tags if t.get("name") not in drop]
    m.tags = tags
    if "pinned" in body:
        m.pinned = bool(body.get("pinned"))
    if body.get("client"):
        m.client = str(body["client"])[:20]
    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"session_id": session_id, **_meta_out(m), "before": before}


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
