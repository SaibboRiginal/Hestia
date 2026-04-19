"""Long-term memory endpoints — preferences, subscriptions, and dispatch logs."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
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
    domain: Optional[str] = None, db: Session = Depends(database.get_db)
):
    """Return active preferences, optionally scoped to a domain (includes 'general')."""
    q = db.query(models.UserPreference).filter(models.UserPreference.is_active == True)  # noqa: E712
    if domain:
        q = q.filter(models.UserPreference.domain.in_([domain, "general"]))
    return q.all()


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
    db_pref.is_active = update_data.is_active
    if update_data.weight is not None:
        db_pref.weight = update_data.weight
    db.commit()
    db.refresh(db_pref)
    return db_pref


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
