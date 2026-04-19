"""Entity CRUD, domain discovery, and hybrid search engine."""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, desc, or_
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(tags=["entities"])


# ── JSON nested-key helpers ───────────────────────────────────────────────────

def _find_nested_key(data: dict, target_key: str) -> Any:
    """Search recursively for *target_key* in a nested dict."""
    if target_key in data:
        return data[target_key]
    for value in data.values():
        if isinstance(value, dict):
            result = _find_nested_key(value, target_key)
            if result is not None:
                return result
    return None


def _find_nested_path(data: dict, target_path: str) -> Any:
    """Traverse a dot-separated path in a nested dict."""
    current = data
    for segment in target_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


# ── Domain / schema discovery ─────────────────────────────────────────────────

@router.get("/api/domains")
def get_available_domains(db: Session = Depends(database.get_db)):
    """Return the distinct domain names present in the entity table."""
    rows = db.query(models.EntityRecord.domain).distinct().all()
    return [r[0] for r in rows if r[0]]


@router.get("/api/schemas")
def get_domain_schemas(db: Session = Depends(database.get_db)):
    """Return the payload field names for one representative entity per domain."""
    rows = db.query(models.EntityRecord.domain).distinct().all()
    result = {}
    for (domain,) in rows:
        entity = (
            db.query(models.EntityRecord)
            .filter(models.EntityRecord.domain == domain)
            .order_by(models.EntityRecord.id.desc())
            .first()
        )
        if entity and entity.payload:
            result[domain] = list(entity.payload.keys())
    return result


# ── Entity CRUD ───────────────────────────────────────────────────────────────

@router.post("/api/entities", response_model=schemas.EntityResponse)
def upsert_entity(entity: schemas.EntityUpsert, db: Session = Depends(database.get_db)):
    """Upsert an entity with intelligent payload merging."""
    db_entity = db.query(models.EntityRecord).filter(
        models.EntityRecord.entity_id == entity.entity_id
    ).first()

    if db_entity:
        db_entity.status = entity.status
        if db_entity.payload and entity.payload:
            merged = dict(db_entity.payload)
            for key, new_val in entity.payload.items():
                old_val = merged.get(key)
                if new_val is None or new_val == "":
                    if old_val is not None:
                        merged[key] = old_val
                elif key == "summary" and isinstance(new_val, str) and isinstance(old_val, str):
                    merged[key] = new_val if len(
                        new_val) > len(old_val) else old_val
                elif key == "specs" and isinstance(old_val, dict) and isinstance(new_val, dict):
                    specs = dict(old_val)
                    specs.update(
                        {k: v for k, v in new_val.items() if v is not None})
                    merged[key] = specs
                elif key == "location" and isinstance(new_val, dict) and new_val.get("lat") is not None:
                    if not isinstance(old_val, dict) or old_val.get("lat") is None:
                        merged[key] = new_val
                else:
                    merged[key] = new_val
            db_entity.payload = merged
        else:
            db_entity.payload = entity.payload
        if entity.embedding:
            db_entity.embedding = entity.embedding
    else:
        db_entity = models.EntityRecord(**entity.model_dump())
        db.add(db_entity)

    db.commit()
    db.refresh(db_entity)
    return db_entity


@router.get("/api/entities")
def get_active_entities(
    domain: Optional[str] = None, db: Session = Depends(database.get_db)
):
    """Return all active entities, optionally filtered by domain."""
    q = db.query(models.EntityRecord).filter(
        models.EntityRecord.status == "active")
    if domain:
        q = q.filter(models.EntityRecord.domain == domain)
    return [{"url": e.entity_id, **dict(e.payload)} for e in q.all()]


@router.get("/api/entities/records", response_model=List[schemas.EntityResponse])
def get_entity_records(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
    db: Session = Depends(database.get_db),
):
    """Return paginated raw entity rows with optional domain/status filters."""
    q = db.query(models.EntityRecord)
    if domain:
        q = q.filter(models.EntityRecord.domain == domain)
    if status:
        q = q.filter(models.EntityRecord.status == status)
    return q.order_by(models.EntityRecord.updated_at.desc()).limit(max(1, min(limit, 5000))).all()


# ── Hybrid search (vector + SQL filters) ─────────────────────────────────────

@router.post("/api/entities/search")
def search_entities(req: schemas.AdvancedSearchRequest, db: Session = Depends(database.get_db)):
    """Hybrid search: SQL hard filters → vector reranking → Python numeric filters."""
    try:
        q = db.query(models.EntityRecord).filter(
            models.EntityRecord.status == "active")

        if req.domain and req.domain != "general":
            q = q.filter(models.EntityRecord.domain == req.domain)

        # SQL text filters (ilike on the JSON blob)
        if req.filters:
            for key, value in req.filters.items():
                if isinstance(value, list):
                    conditions = [
                        cast(models.EntityRecord.payload,
                             String).ilike(f"%{str(v)}%")
                        for v in value
                    ]
                    q = q.filter(or_(*conditions))
                else:
                    q = q.filter(
                        cast(models.EntityRecord.payload,
                             String).ilike(f"%{str(value)}%")
                    )

        # Vector ordering (semantic reranking)
        if req.query_vector:
            q = q.order_by(
                models.EntityRecord.embedding.l2_distance(req.query_vector))
        else:
            q = q.order_by(desc(models.EntityRecord.id))

        db_results = q.limit(100).all()
        output = []
        for e in db_results:
            item = {"url": e.entity_id, **dict(e.payload)}
            if req.filters_gt and any(
                _find_nested_key(item, k) is None or float(
                    _find_nested_key(item, k) or 0) <= float(v)
                for k, v in req.filters_gt.items()
            ):
                continue
            if req.filters_lt and any(
                _find_nested_key(item, k) is None or float(
                    _find_nested_key(item, k) or 0) >= float(v)
                for k, v in req.filters_lt.items()
            ):
                continue
            output.append(item)

        if req.sort_by and output:
            sample = _find_nested_key(output[0], req.sort_by)
            if sample is not None:
                try:
                    output.sort(
                        key=lambda x: float(
                            _find_nested_key(x, req.sort_by) or 0),
                        reverse=(req.sort_order == "desc"),
                    )
                except (ValueError, TypeError):
                    pass

        return output[: req.limit]

    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Maintenance ───────────────────────────────────────────────────────────────

@router.post("/api/entities/cleanup", response_model=schemas.EntityCleanupResponse)
def cleanup_entities(req: schemas.EntityCleanupRequest, db: Session = Depends(database.get_db)):
    """Delete entity records that are missing required fields."""
    q = db.query(models.EntityRecord)
    if req.domain:
        q = q.filter(models.EntityRecord.domain == req.domain)

    records = q.order_by(models.EntityRecord.updated_at.desc()).limit(
        max(1, min(req.delete_limit, 5000))
    ).all()

    to_delete = []
    for record in records:
        payload = dict(record.payload or {})
        invalid = (
            (req.require_created_at and record.created_at is None)
            or not (record.entity_id or "").strip()
        )
        if not invalid:
            for field in req.required_fields:
                val = _find_nested_path(payload, field)
                if val is None or (isinstance(val, str) and not val.strip()):
                    invalid = True
                    break
        if invalid:
            to_delete.append(record)

    sampled_ids = [r.entity_id for r in to_delete[:50] if r.entity_id]
    if not req.dry_run:
        for r in to_delete:
            db.delete(r)
        db.commit()

    return schemas.EntityCleanupResponse(
        scanned=len(records),
        deleted=0 if req.dry_run else len(to_delete),
        sampled_deleted_ids=sampled_ids,
        dry_run=req.dry_run,
    )
