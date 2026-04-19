"""Document storage and RAG retrieval endpoints."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=schemas.DocumentRead)
def store_document(
    doc: schemas.DocumentIngest, db: Session = Depends(database.get_db)
):
    """Ingest a document with pre-computed chunks. Idempotent on document_id."""
    existing = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == doc.document_id
    ).first()
    if existing:
        return existing

    db_doc = models.DocumentRecord(
        document_id=doc.document_id,
        session_id=doc.session_id,
        chat_id=doc.chat_id,
        filename=doc.filename,
        mime_type=doc.mime_type,
        file_size_bytes=doc.file_size_bytes,
        file_hash=doc.file_hash,
        title=doc.title,
        summary=doc.summary,
        extracted_text=doc.extracted_text,
        embedding=doc.embedding if doc.embedding else None,
        is_permanent=doc.is_permanent,
        domain=doc.domain or "documents",
        tags=doc.tags,
        chunk_count=len(doc.chunks),
    )
    db.add(db_doc)
    for chunk in doc.chunks:
        db.add(models.DocumentChunk(
            document_id=doc.document_id,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            embedding=chunk.embedding if chunk.embedding else None,
        ))
    db.commit()
    db.refresh(db_doc)
    return db_doc


@router.get("", response_model=List[schemas.DocumentRead])
def list_documents(
    session_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    is_permanent: Optional[bool] = None,
    domain: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(database.get_db),
):
    """List documents with optional session / chat / permanence / domain filters."""
    q = db.query(models.DocumentRecord)
    if session_id:
        q = q.filter(models.DocumentRecord.session_id == session_id)
    if chat_id:
        q = q.filter(models.DocumentRecord.chat_id == chat_id)
    if is_permanent is not None:
        q = q.filter(models.DocumentRecord.is_permanent == is_permanent)
    if domain:
        q = q.filter(models.DocumentRecord.domain == domain.lower().strip())
    return q.order_by(models.DocumentRecord.created_at.desc()).limit(max(1, min(limit, 200))).all()


@router.get("/{document_id}", response_model=schemas.DocumentRead)
def get_document(document_id: str, db: Session = Depends(database.get_db)):
    """Return a single document by its UUID."""
    doc = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == document_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(database.get_db)):
    """Delete a document and all its associated chunks."""
    doc = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == document_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.query(models.DocumentChunk).filter(
        models.DocumentChunk.document_id == document_id
    ).delete()
    db.delete(doc)
    db.commit()
    return {"status": "deleted", "document_id": document_id}


@router.patch("/{document_id}/permanent")
def update_document_permanent(
    document_id: str,
    update: schemas.DocumentPermanentUpdate,
    db: Session = Depends(database.get_db),
):
    """Toggle permanent / temporary status of a document."""
    doc = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == document_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.is_permanent = update.is_permanent
    db.commit()
    return {"document_id": document_id, "is_permanent": doc.is_permanent}


@router.post("/search", response_model=List[schemas.DocumentSearchResult])
def search_document_chunks(
    req: schemas.DocumentSearchRequest,
    db: Session = Depends(database.get_db),
):
    """Semantic search over document chunks using L2 vector distance.

    Returns at most 2 chunks per document to avoid flooding context.
    Optionally tracks access stats when *track_access* is True.
    """
    if not req.query_vector:
        return []

    dist_col = models.DocumentChunk.embedding.l2_distance(
        req.query_vector).label("distance")
    q = (
        db.query(models.DocumentChunk, models.DocumentRecord, dist_col)
        .join(models.DocumentRecord, models.DocumentRecord.document_id == models.DocumentChunk.document_id)
        .filter(models.DocumentChunk.embedding.isnot(None))
    )
    if req.session_id:
        q = q.filter(models.DocumentRecord.session_id == req.session_id)
    if req.chat_id:
        q = q.filter(models.DocumentRecord.chat_id == req.chat_id)
    if req.is_permanent is not None:
        q = q.filter(models.DocumentRecord.is_permanent == req.is_permanent)
    if req.domain:
        q = q.filter(models.DocumentRecord.domain ==
                     req.domain.lower().strip())

    rows = q.order_by(text("distance")).limit(req.limit * 4).all()

    results: list[schemas.DocumentSearchResult] = []
    per_doc_count: dict[str, int] = {}
    accessed_ids: set[str] = set()

    for chunk, doc, distance in rows:
        dist_f = float(distance)
        if dist_f > req.threshold:
            break
        doc_id = chunk.document_id
        if per_doc_count.get(doc_id, 0) >= 2:
            continue
        results.append(schemas.DocumentSearchResult(
            document_id=doc_id,
            title=doc.title,
            summary=doc.summary,
            chunk_text=chunk.chunk_text,
            chunk_index=chunk.chunk_index,
            distance=dist_f,
            is_permanent=doc.is_permanent,
            domain=doc.domain or "documents",
            tags=doc.tags,
            created_at=doc.created_at,
            last_accessed_at=doc.last_accessed_at,
            access_count=doc.access_count or 0,
        ))
        per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1
        accessed_ids.add(doc_id)
        if len(results) >= req.limit:
            break

    if req.track_access and accessed_ids:
        now = datetime.now(timezone.utc)
        db.query(models.DocumentRecord).filter(
            models.DocumentRecord.document_id.in_(accessed_ids)
        ).update(
            {"last_accessed_at": now,
                "access_count": models.DocumentRecord.access_count + 1},
            synchronize_session=False,
        )
        db.commit()

    return results


@router.delete("/prune")
def prune_documents(
    req: schemas.DocumentPruneRequest,
    db: Session = Depends(database.get_db),
):
    """Bulk-delete non-permanent documents that are stale and rarely accessed.

    A document is pruned when is_permanent=False AND it is older than
    idle_days AND access_count ≤ max_access_count.  Pass dry_run=true to
    preview without committing.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=req.idle_days)
    q = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.is_permanent == False,  # noqa: E712
        models.DocumentRecord.access_count <= req.max_access_count,
        or_(
            models.DocumentRecord.last_accessed_at < cutoff,
            models.DocumentRecord.last_accessed_at.is_(None),
        ),
        models.DocumentRecord.created_at < cutoff,
    )
    candidates = q.all()
    candidate_ids = [doc.document_id for doc in candidates]

    if req.dry_run:
        return {"dry_run": True, "would_delete": len(candidate_ids), "document_ids": candidate_ids}

    if candidate_ids:
        db.query(models.DocumentChunk).filter(
            models.DocumentChunk.document_id.in_(candidate_ids)
        ).delete(synchronize_session=False)
        db.query(models.DocumentRecord).filter(
            models.DocumentRecord.document_id.in_(candidate_ids)
        ).delete(synchronize_session=False)
        db.commit()

    return {"dry_run": False, "deleted": len(candidate_ids), "document_ids": candidate_ids}
