"""Long-term memory endpoints — preferences, subscriptions, and dispatch logs."""
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas, database

router = APIRouter(tags=["memory"])


# ── User preferences ──────────────────────────────────────────────────────────

@router.post("/api/memory", response_model=schemas.PreferenceResponse)
def add_preference(
    pref: schemas.PreferenceCreate, db: Session = Depends(database.get_db)
):
    """Create a new user preference record."""
    db_pref = models.UserPreference(**pref.model_dump())
    db.add(db_pref)
    db.commit()
    db.refresh(db_pref)
    return db_pref


@router.get("/api/memory/active", response_model=List[schemas.PreferenceResponse])
def get_active_preferences(
    domain: Optional[str] = None,
    memory_class: Optional[str] = None,
    limit: int = 1000,
    db: Session = Depends(database.get_db),
):
    """Return active memories, optionally scoped to a domain (includes 'general')
    and to a memory_class (e.g. skill, durable_user_preference).

    memory_class used to be ignored although every caller sent it: Athena's
    skill lifecycle received user preferences as "skills" and could deactivate them.
    """
    q = db.query(models.UserPreference).filter(models.UserPreference.is_active == True)  # noqa: E712
    if domain:
        q = q.filter(models.UserPreference.domain.in_([domain, "general"]))
    if memory_class:
        q = q.filter(models.UserPreference.memory_class == memory_class)
    return q.order_by(models.UserPreference.id.desc()).limit(max(1, min(limit, 5000))).all()


@router.patch("/api/memory/{pref_id}", response_model=schemas.PreferenceResponse)
def deprecate_preference(
    pref_id: int,
    update_data: schemas.PreferenceUpdate,
    db: Session = Depends(database.get_db),
):
    """Activate or deprecate a preference; optionally update its weight."""
    db_pref = db.query(models.UserPreference).filter(
        models.UserPreference.id == pref_id
    ).first()
    if not db_pref:
        raise HTTPException(status_code=404, detail="Preference not found")
    if update_data.is_active is not None:
        db_pref.is_active = update_data.is_active
    if update_data.weight is not None:
        db_pref.weight = update_data.weight
    if update_data.extra_data is not None:
        db_pref.extra_data = {**(db_pref.extra_data or {}), **update_data.extra_data}
    db.commit()
    db.refresh(db_pref)
    return db_pref


# ── Similarity search ────────────────────────────────────────────────────────

@router.post("/api/memory/search/similar")
def search_similar_memories(
    body: dict, db: Session = Depends(database.get_db)
):
    """Return active memories ranked by cosine similarity to *embedding*.

    Body: {"embedding": [...], "memory_class": "skill", "domain": "calendar", "limit": 5}
    """
    query_embedding = body.get("embedding")
    if not isinstance(query_embedding, list) or not query_embedding:
        raise HTTPException(status_code=400, detail="embedding vector required")

    memory_class = body.get("memory_class")
    domain = body.get("domain")
    limit = min(int(body.get("limit", 5)), 20)

    q = db.query(models.UserPreference).filter(
        models.UserPreference.is_active == True,  # noqa: E712
        models.UserPreference.embedding.isnot(None),
    )
    if memory_class:
        q = q.filter(models.UserPreference.memory_class == memory_class)
    if domain:
        q = q.filter(
            models.UserPreference.domain.in_([domain, "general"]))

    candidates = q.all()
    if not candidates:
        return []

    # Cosine similarity ranking
    from math import sqrt

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    def norm(v):
        return sqrt(sum(x * x for x in v))

    qn = norm(query_embedding)
    scored = []
    for row in candidates:
        # pgvector yields numpy arrays (not list): the old isinstance(list)
        # check skipped every row, so similarity search always returned [].
        emb = [float(x) for x in row.embedding] if row.embedding is not None else []
        if not emb:
            continue
        rn = norm(emb)
        if qn == 0.0 or rn == 0.0:
            continue
        sim = dot(query_embedding, emb) / (qn * rn)
        scored.append((sim, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    # Serialize top matches
    results = []
    for sim, row in top:
        d = {
            "id": row.id,
            "fact": row.fact,
            "domain": row.domain,
            "weight": row.weight,
            "is_active": row.is_active,
            "memory_class": row.memory_class,
            "domains": row.domains,
            "extra_data": row.extra_data,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "_similarity": round(sim, 4),
        }
        results.append(d)
    return results


# ── Alert subscriptions ───────────────────────────────────────────────────────

@router.post("/api/subscriptions", response_model=schemas.SubscriptionResponse)
def upsert_subscription(
    req: schemas.SubscriptionUpsert, db: Session = Depends(database.get_db)
):
    """Create or update an alert subscription keyed by subscription_id."""
    sub = db.query(models.AlertSubscription).filter(
        models.AlertSubscription.subscription_id == req.subscription_id
    ).first()
    if sub:
        sub.owner = req.owner
        sub.domain = req.domain
        sub.event_type = req.event_type
        sub.filters = req.filters
        sub.channels = req.channels
        sub.is_active = req.is_active
    else:
        sub = models.AlertSubscription(**req.model_dump())
        db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("/api/subscriptions/active", response_model=List[schemas.SubscriptionResponse])
def get_active_subscriptions(
    domain: Optional[str] = None,
    event_type: Optional[str] = None,
    owner: Optional[str] = None,
    db: Session = Depends(database.get_db),
):
    """Return active subscriptions with optional domain / event_type / owner filters."""
    q = db.query(models.AlertSubscription).filter(
        models.AlertSubscription.is_active == True  # noqa: E712
    )
    if domain:
        q = q.filter(models.AlertSubscription.domain == domain)
    if event_type:
        q = q.filter(models.AlertSubscription.event_type == event_type)
    if owner:
        q = q.filter(models.AlertSubscription.owner == owner)
    return q.order_by(models.AlertSubscription.updated_at.desc()).limit(2000).all()


@router.patch(
    "/api/subscriptions/{subscription_id}/active",
    response_model=schemas.SubscriptionResponse,
)
def update_subscription_active(
    subscription_id: str,
    req: schemas.SubscriptionActiveUpdate,
    db: Session = Depends(database.get_db),
):
    """Toggle is_active on a subscription by its subscription_id."""
    sub = db.query(models.AlertSubscription).filter(
        models.AlertSubscription.subscription_id == subscription_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.is_active = req.is_active
    db.commit()
    db.refresh(sub)
    return sub


# ── Dispatch logs ─────────────────────────────────────────────────────────────

@router.post("/api/dispatch/logs", response_model=schemas.DispatchLogResponse)
def create_dispatch_log(
    req: schemas.DispatchLogCreate, db: Session = Depends(database.get_db)
):
    """Record a dispatch event log."""
    log = models.DispatchLog(**req.model_dump())
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get("/api/dispatch/logs", response_model=List[schemas.DispatchLogResponse])
def get_dispatch_logs(
    subscription_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(database.get_db),
):
    """Return dispatch logs with optional subscription / entity filters."""
    q = db.query(models.DispatchLog)
    if subscription_id:
        q = q.filter(models.DispatchLog.subscription_id == subscription_id)
    if entity_id:
        q = q.filter(models.DispatchLog.entity_id == entity_id)
    return q.order_by(models.DispatchLog.created_at.desc()).limit(max(1, min(limit, 2000))).all()


@router.get("/api/dispatch/logs/enriched")
def get_dispatch_logs_enriched(
    subscription_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 20,
    hours: Optional[int] = None,
    db: Session = Depends(database.get_db),
):
    """Return dispatch logs enriched with entity payload data."""
    q = db.query(models.DispatchLog)
    if subscription_id:
        q = q.filter(models.DispatchLog.subscription_id == subscription_id)
    if entity_id:
        q = q.filter(models.DispatchLog.entity_id == entity_id)
    if hours is not None and hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        q = q.filter(models.DispatchLog.created_at >= cutoff)

    logs = q.order_by(models.DispatchLog.created_at.desc()).limit(
        max(1, min(limit, 500))
    ).all()

    enriched = []
    for log in logs:
        entry = {
            "id": log.id,
            "subscription_id": log.subscription_id,
            "event_type": log.event_type,
            "domain": log.domain,
            "entity_id": log.entity_id,
            "channel": log.channel,
            "target": log.target,
            "success": log.success,
            "detail": log.detail,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        try:
            entity = db.query(models.EntityRecord).filter(
                models.EntityRecord.domain == log.domain,
                models.EntityRecord.entity_id == log.entity_id,
            ).first()
            if entity and entity.payload:
                entry["entity_title"] = entity.payload.get("title")
                entry["entity_address"] = entity.payload.get("address")
                entry["entity_price"] = entity.payload.get("price")
                entry["entity_url"] = entity.payload.get(
                    "url") or log.entity_id
                entry["entity_summary"] = entity.payload.get("summary")
        except Exception:
            pass
        enriched.append(entry)

    return enriched


# ── Interaction ledger ───────────────────────────────────────────────────────

@router.post("/api/interaction-ledger", response_model=schemas.InteractionLedgerResponse)
def create_interaction_ledger_record(
    req: schemas.InteractionLedgerCreate,
    db: Session = Depends(database.get_db),
):
    """Append a compact typed interaction record."""
    row = models.InteractionLedgerRecord(**req.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/api/interaction-ledger", response_model=List[schemas.InteractionLedgerResponse])
def get_interaction_ledger(
    session_id: Optional[str] = None,
    event_type: Optional[str] = None,
    domain: Optional[str] = None,
    source_service: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(database.get_db),
):
    """Return interaction ledger records with optional filters."""
    q = db.query(models.InteractionLedgerRecord)
    if session_id:
        q = q.filter(models.InteractionLedgerRecord.session_id == session_id)
    if event_type:
        q = q.filter(models.InteractionLedgerRecord.event_type == event_type)
    if domain:
        q = q.filter(models.InteractionLedgerRecord.domain == domain)
    if source_service:
        q = q.filter(
            models.InteractionLedgerRecord.source_service == source_service)
    return q.order_by(models.InteractionLedgerRecord.created_at.desc()).limit(max(1, min(limit, 2000))).all()


# ── Outbound event lifecycle (P2-4) ─────────────────────────────────────────

@router.post("/api/outbound-events/upsert", response_model=schemas.OutboundEventResponse)
def upsert_outbound_event(
    req: schemas.OutboundEventUpsert,
    db: Session = Depends(database.get_db),
):
    """Create or update an outbound event lifecycle record."""
    row = db.query(models.OutboundEventRecord).filter(
        models.OutboundEventRecord.outbound_event_id == req.outbound_event_id
    ).first()
    data = req.model_dump()
    if row:
        for key, value in data.items():
            setattr(row, key, value)
    else:
        row = models.OutboundEventRecord(**data)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/api/outbound-events", response_model=List[schemas.OutboundEventResponse])
def list_outbound_events(
    outbound_event_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    lifecycle_state: Optional[str] = None,
    lifecycle_states: Optional[str] = None,
    subscription_id: Optional[str] = None,
    question_id: Optional[str] = None,
    brief_id: Optional[str] = None,
    channel: Optional[str] = None,
    target: Optional[str] = None,
    domain: Optional[str] = None,
    payload_source: Optional[str] = None,
    created_before: Optional[datetime] = None,
    created_after: Optional[datetime] = None,
    updated_before: Optional[datetime] = None,
    order_by: str = "updated",
    limit: int = 200,
    db: Session = Depends(database.get_db),
):
    """Return outbound lifecycle records with optional filters.

    ``lifecycle_states`` = comma list; ``payload_source`` matches
    ``payload.notification.source`` (Hermes notifications); ``order_by``
    ``created`` (newest first, for inbox paging with ``created_before``) or ``updated``.
    """
    M = models.OutboundEventRecord
    q = db.query(M)
    if outbound_event_id:
        q = q.filter(M.outbound_event_id == outbound_event_id)
    if dedupe_key:
        q = q.filter(M.dedupe_key == dedupe_key)
    if lifecycle_state:
        q = q.filter(M.lifecycle_state == lifecycle_state)
    if lifecycle_states:
        states = [x.strip() for x in lifecycle_states.split(",") if x.strip()]
        if states:
            q = q.filter(M.lifecycle_state.in_(states))
    if subscription_id:
        q = q.filter(M.subscription_id == subscription_id)
    if question_id:
        q = q.filter(M.question_id == question_id)
    if brief_id:
        q = q.filter(M.brief_id == brief_id)
    if channel:
        q = q.filter(M.channel == channel)
    if target:
        q = q.filter(M.target == target)
    if domain:
        q = q.filter(M.domain == domain)
    if payload_source:
        q = q.filter(M.payload["notification"]["source"].astext == payload_source)
    if created_before:
        q = q.filter(M.created_at < created_before)
    if created_after:
        q = q.filter(M.created_at > created_after)
    if updated_before:
        q = q.filter(M.updated_at < updated_before)
    order = M.created_at.desc() if order_by == "created" else M.updated_at.desc()
    return q.order_by(order).limit(max(1, min(limit, 2000))).all()


@router.patch("/api/outbound-events/{outbound_event_id}/state", response_model=schemas.OutboundEventResponse)
def update_outbound_event_state(
    outbound_event_id: str,
    req: schemas.OutboundEventStateUpdate,
    db: Session = Depends(database.get_db),
):
    """Update lifecycle state of an existing outbound event record.

    ``only_if_states`` makes it a compare-and-set (row locked): 409 with the
    current state when it does not match. ``payload_merge`` is merged into
    the payload in the same transaction.
    """
    row = db.query(models.OutboundEventRecord).filter(
        models.OutboundEventRecord.outbound_event_id == outbound_event_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(status_code=404, detail="Outbound event not found")

    if req.only_if_states is not None and row.lifecycle_state not in req.only_if_states:
        current = row.lifecycle_state
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "status": "state_conflict", "lifecycle_state": current})

    row.lifecycle_state = req.lifecycle_state
    if req.detail is not None or req.only_if_states is None:
        row.detail = req.detail
    if req.superseded_by is not None or req.only_if_states is None:
        row.superseded_by = req.superseded_by
    if req.payload_merge:
        merged = dict(row.payload or {})
        merged.update(req.payload_merge)
        row.payload = merged
    db.commit()
    db.refresh(row)
    return row


# ── Feedback records (P3-2) ──────────────────────────────────────────────────

@router.post("/api/feedback", response_model=schemas.FeedbackResponse)
def create_feedback_record(
    req: schemas.FeedbackCreate,
    db: Session = Depends(database.get_db),
):
    """Append a quality feedback record."""
    data = req.model_dump()
    feedback_id = data.pop(
        "feedback_id", None) or f"fbk-{uuid.uuid4().hex[:16]}"
    row = models.FeedbackRecord(feedback_id=feedback_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/api/feedback", response_model=List[schemas.FeedbackResponse])
def list_feedback_records(
    session_id: Optional[str] = None,
    quality_label: Optional[schemas.FeedbackQualityLabel] = None,
    source_client: Optional[str] = None,
    source_service: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(database.get_db),
):
    """List feedback records with optional filters."""
    q = db.query(models.FeedbackRecord)
    if session_id:
        q = q.filter(models.FeedbackRecord.session_id == session_id)
    if quality_label:
        q = q.filter(models.FeedbackRecord.quality_label == quality_label)
    if source_client:
        q = q.filter(models.FeedbackRecord.source_client == source_client)
    if source_service:
        q = q.filter(models.FeedbackRecord.source_service == source_service)
    return q.order_by(models.FeedbackRecord.created_at.desc()).limit(max(1, min(limit, 5000))).all()


def _feedback_jsonl_lines(rows: list[models.FeedbackRecord]) -> Iterator[str]:
    for row in rows:
        payload = row.payload or {}
        record = {
            "feedback_id": row.feedback_id,
            "session_id": row.session_id,
            "interaction_id": row.interaction_id,
            "source_service": row.source_service,
            "source_client": row.source_client,
            "quality_label": row.quality_label,
            "quality_score": row.quality_score,
            "outcome_label": row.outcome_label,
            "feedback_text": row.feedback_text,
            "tags": row.tags or [],
            "instruction": payload.get("instruction"),
            "input": payload.get("input"),
            "output": payload.get("output"),
            "payload": payload,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        yield json.dumps(record, ensure_ascii=False) + "\n"


@router.get("/api/feedback/export/jsonl")
def export_feedback_jsonl(
    session_id: Optional[str] = None,
    quality_label: Optional[schemas.FeedbackQualityLabel] = None,
    source_client: Optional[str] = None,
    source_service: Optional[str] = None,
    limit: int = 1000,
    db: Session = Depends(database.get_db),
):
    """Export filtered feedback rows as JSONL for offline analysis/training."""
    q = db.query(models.FeedbackRecord)
    if session_id:
        q = q.filter(models.FeedbackRecord.session_id == session_id)
    if quality_label:
        q = q.filter(models.FeedbackRecord.quality_label == quality_label)
    if source_client:
        q = q.filter(models.FeedbackRecord.source_client == source_client)
    if source_service:
        q = q.filter(models.FeedbackRecord.source_service == source_service)
    rows = q.order_by(models.FeedbackRecord.created_at.desc()
                      ).limit(max(1, min(limit, 10000))).all()
    filename = f"feedback-export-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    return StreamingResponse(
        _feedback_jsonl_lines(rows),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
