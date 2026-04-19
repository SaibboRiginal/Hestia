import os
import requests
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, cast, Float, String, desc, asc, or_
from . import models, schemas, database
from .database import engine
from typing import List, Optional, Any

# --- Turn on the AI vector math BEFORE creating tables ---
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

# Generate the universal table
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Hestia-Archive Vault",
              version="3.0.0 (Entity & Vector Ready)")


@app.on_event("startup")
def register_on_hub_startup():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "ARCHIVE_SERVICE_BASE_URL", "http://hestia_archive:19002")
    payload = {
        "name": "archive",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("ARCHIVE_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "storage"],
        "capabilities": {
            "api_prefix": "/api",
            "commands": [
                {
                    "command": "preferenze_attive",
                    "title": "🧠 Preferenze attive",
                    "description": "Mostra le preferenze utente attive",
                    "method": "GET",
                    "path": "/api/memory/active",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": "Mostra le preferenze attive in elenco sintetico, raggruppando per dominio e usando linguaggio naturale.",
                },
                {
                    "command": "notifiche_attive",
                    "title": "🔔 Notifiche attive",
                    "description": "Mostra le notifiche automatiche attive",
                    "method": "GET",
                    "path": "/api/subscriptions/active",
                    "query_template": {
                        "owner": "$session_id",
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": "Mostra le notifiche attive con filtri principali, stato e cosa verrà notificato, in modo leggibile e breve.",
                },
                {
                    "command": "avvisi_recenti",
                    "title": "📬 Avvisi recenti",
                    "description": "Mostra gli ultimi avvisi inviati",
                    "method": "GET",
                    "path": "/api/dispatch/logs/enriched",
                    "query_template": {
                        "limit": 15,
                        "hours": 72,
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": "Mostra una timeline degli avvisi recenti con TITOLO COMPLETO della proprietà, indirizzo, prezzo e data/ora. Usa link leggibili con il titolo dell'immobile, NON 'Apri annuncio'. Per ogni avviso indica se è stato consegnato con successo. Sii conciso ma informativo.",
                },
                {
                    "command": "notifica_disattiva",
                    "title": "🔕 Disattiva notifica",
                    "description": "Disattiva una notifica tramite subscription_id",
                    "method": "PATCH",
                    "path": "/api/subscriptions/$arg.subscription_id/active",
                    "body_template": {
                        "is_active": False,
                    },
                    "arguments_help": "subscription_id=<id>",
                    "arg_picker": {
                        "arg": "subscription_id",
                        "source": {
                            "service": "archive",
                            "method": "GET",
                            "path": "/api/subscriptions/active",
                            "query_template": {
                                "owner": "$session_id"
                            }
                        },
                        "value_field": "subscription_id",
                        "label_fields": ["domain", "event_type", "filters"]
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": "Conferma chiaramente l'avvenuta disattivazione della notifica.",
                },
                {
                    "command": "notifica_attiva",
                    "title": "🔔 Riattiva notifica",
                    "description": "Riattiva una notifica tramite subscription_id",
                    "method": "PATCH",
                    "path": "/api/subscriptions/$arg.subscription_id/active",
                    "body_template": {
                        "is_active": True,
                    },
                    "arguments_help": "subscription_id=<id>",
                    "arg_picker": {
                        "arg": "subscription_id",
                        "source": {
                            "service": "archive",
                            "method": "GET",
                            "path": "/api/subscriptions/active",
                            "query_template": {
                                "owner": "$session_id"
                            }
                        },
                        "value_field": "subscription_id",
                        "label_fields": ["domain", "event_type", "filters"]
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": "Conferma chiaramente l'avvenuta riattivazione della notifica.",
                },
            ],
        },
    }
    try:
        requests.post(f"{hub_api_url}/registry/register",
                      json=payload, timeout=4)
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_archive"}

# ==========================================
# RAW ARCHIVE (Ingest Data Lake)
# ==========================================


@app.post("/api/archive", response_model=schemas.RecordResponse)
def save_record(record: schemas.RecordCreate, db: Session = Depends(database.get_db)):
    if record.reference_id:
        existing = db.query(models.ArchiveRecord).filter(
            models.ArchiveRecord.reference_id == record.reference_id).first()
        if existing:
            return existing
    db_record = models.ArchiveRecord(**record.model_dump())
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


@app.get("/api/archive/{domain}/unevaluated")
def get_unevaluated(domain: str, db: Session = Depends(database.get_db)):
    return db.query(models.ArchiveRecord).filter(models.ArchiveRecord.domain == domain, models.ArchiveRecord.is_evaluated == False).all()


@app.patch("/api/archive/{record_id}", response_model=schemas.RecordResponse)
def update_record(record_id: int, update_data: schemas.RecordUpdate, db: Session = Depends(database.get_db)):
    db_record = db.query(models.ArchiveRecord).filter(
        models.ArchiveRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Record not found")
    current_payload = dict(db_record.payload)
    current_payload["ai_evaluation"] = update_data.evaluation
    db_record.payload = current_payload
    db_record.is_evaluated = True
    db.commit()
    db.refresh(db_record)
    return db_record

# ==========================================
# ENTITIES (Processed Real-World Objects)
# ==========================================


@app.post("/api/entities", response_model=schemas.EntityResponse)
def upsert_entity(entity: schemas.EntityUpsert, db: Session = Depends(database.get_db)):
    """
    Upsert entity: create if new, update if exists.
    When updating, merge payloads intelligently to preserve existing data.
    """
    db_entity = db.query(models.EntityRecord).filter(
        models.EntityRecord.entity_id == entity.entity_id).first()

    if db_entity:
        # Entity exists - update with intelligent merge
        db_entity.status = entity.status

        # Merge payloads: keep existing fields if new payload doesn't have them
        # or if new values are empty/None
        if db_entity.payload and entity.payload:
            merged_payload = dict(db_entity.payload)

            for key, new_value in entity.payload.items():
                old_value = merged_payload.get(key)

                # Update if new value is more substantial
                if new_value is not None and new_value != "":
                    if key == "summary":
                        # For summary, prefer longer descriptions
                        if isinstance(new_value, str) and isinstance(old_value, str):
                            merged_payload[key] = new_value if len(
                                new_value) > len(old_value) else old_value
                        else:
                            merged_payload[key] = new_value
                    elif key == "specs":
                        # For specs, merge dict fields
                        if isinstance(old_value, dict) and isinstance(new_value, dict):
                            merged_specs = dict(old_value)
                            merged_specs.update(
                                {k: v for k, v in new_value.items() if v is not None})
                            merged_payload[key] = merged_specs
                        else:
                            merged_payload[key] = new_value
                    elif key == "location":
                        # For location, update only if new has coordinates and old doesn't
                        if isinstance(new_value, dict) and new_value.get("lat") is not None:
                            if not isinstance(old_value, dict) or old_value.get("lat") is None:
                                merged_payload[key] = new_value
                    else:
                        # For other fields, prefer non-empty new values
                        merged_payload[key] = new_value
                else:
                    # Keep old value if new is empty/None
                    if old_value is not None:
                        merged_payload[key] = old_value

            db_entity.payload = merged_payload
        else:
            db_entity.payload = entity.payload

        if entity.embedding:
            db_entity.embedding = entity.embedding
    else:
        # New entity - create
        db_entity = models.EntityRecord(**entity.model_dump())
        db.add(db_entity)

    db.commit()
    db.refresh(db_entity)
    return db_entity


@app.get("/api/domains")
def get_available_domains(db: Session = Depends(database.get_db)):
    domains = db.query(models.EntityRecord.domain).distinct().all()
    return [d[0] for d in domains if d[0]]


@app.get("/api/schemas")
def get_domain_schemas(db: Session = Depends(database.get_db)):
    domains = db.query(models.EntityRecord.domain).distinct().all()
    schemas = {}
    for (d,) in domains:
        entity = db.query(models.EntityRecord).filter(
            models.EntityRecord.domain == d).order_by(models.EntityRecord.id.desc()).first()
        if entity and entity.payload:
            schemas[d] = list(entity.payload.keys())
    return schemas


@app.get("/api/entities")
def get_active_entities(domain: Optional[str] = None, db: Session = Depends(database.get_db)):
    query = db.query(models.EntityRecord).filter(
        models.EntityRecord.status == 'active')
    if domain:
        query = query.filter(models.EntityRecord.domain == domain)
    output = []
    for e in query.all():
        item = dict(e.payload)
        item["url"] = e.entity_id
        output.append(item)
    return output

# ==========================================
# 🎯 HYBRID SEARCH ENGINE (RAG + SQL + PYTHON SAFE FILTER)
# ==========================================

# 🆕 FUNZIONE SALVAVITA: Cerca una chiave ovunque nel JSON, anche se nascosta (es. dentro "specs")


def _find_nested_key(data: dict, target_key: str) -> Any:
    if target_key in data:
        return data[target_key]
    for key, value in data.items():
        if isinstance(value, dict):
            res = _find_nested_key(value, target_key)
            if res is not None:
                return res
    return None


def _find_nested_path(data: dict, target_path: str) -> Any:
    current = data
    for segment in target_path.split('.'):
        if not isinstance(current, dict):
            return None
        if segment not in current:
            return None
        current = current.get(segment)
    return current


@app.post("/api/entities/search")
def search_entities(req: schemas.AdvancedSearchRequest, db: Session = Depends(database.get_db)):
    try:
        print(f"\n🚀 [ARCHIVE DEBUG] --- INIZIO RICERCA ---")
        print(
            f"🚀 [ARCHIVE DEBUG] Dominio: {req.domain} | Filtri: {req.filters}")

        query = db.query(models.EntityRecord).filter(
            models.EntityRecord.status == 'active')

        if req.domain and req.domain != "general":
            query = query.filter(models.EntityRecord.domain == req.domain)

        # 1. HARD FILTERS (Ricerca testo bruta ovunque nel JSON)
        if req.filters:
            for key, value in req.filters.items():
                if isinstance(value, list):
                    conditions = [cast(models.EntityRecord.payload, String).ilike(
                        f"%{str(v)}%") for v in value]
                    query = query.filter(or_(*conditions))
                else:
                    query = query.filter(
                        cast(models.EntityRecord.payload, String).ilike(f"%{str(value)}%"))

        # 2. RICERCA SEMANTICA VETTORIALE (Ordinamento puro basato sulla distanza)
        if req.query_vector and len(req.query_vector) > 0:
            print(
                "🚀 [ARCHIVE DEBUG] Vettore rilevato! Applicazione ordinamento semantico l2_distance.")
            query = query.order_by(
                models.EntityRecord.embedding.l2_distance(req.query_vector))
        else:
            query = query.order_by(desc(models.EntityRecord.id))

        # Estrarre i dati dal DB (Max 100 per sicurezza per non intasare la RAM)
        db_results = query.limit(100).all()
        print(
            f"🚀 [ARCHIVE DEBUG] Il database SQL ha restituito {len(db_results)} record base.")

        # 3. FILTRAGGIO MATEMATICO IN PYTHON (ANTI-CRASH)
        output = []
        for e in db_results:
            item = dict(e.payload)
            item["url"] = e.entity_id
            include = True

            if req.filters_gt:
                for k, v in req.filters_gt.items():
                    val = _find_nested_key(item, k)
                    if val is None or float(val) <= float(v):
                        include = False

            if req.filters_lt:
                for k, v in req.filters_lt.items():
                    val = _find_nested_key(item, k)
                    if val is None or float(val) >= float(v):
                        include = False

            if include:
                output.append(item)

        # 4. ORDINAMENTO IN PYTHON PROTETTO
        if req.sort_by:
            # Verifica che almeno un record abbia la chiave richiesta per evitare errori di tipo
            sample_val = _find_nested_key(
                output[0], req.sort_by) if output else None

            if sample_val is not None:
                print(
                    f"🚀 [ARCHIVE DEBUG] Ordinamento Python attivo su: {req.sort_by}")
                try:
                    output.sort(
                        key=lambda x: float(
                            _find_nested_key(x, req.sort_by) or 0),
                        reverse=(req.sort_order == "desc")
                    )
                except (ValueError, TypeError):
                    print(
                        f"⚠️ [SORT ERROR] Impossibile ordinare per {req.sort_by}: tipi non compatibili.")

        final_output = output[:req.limit]
        print(
            f"✅ [ARCHIVE DEBUG] --- FINE RICERCA: Restituiti {len(final_output)} record validati ---")
        return final_output

    except Exception as e:
        import traceback
        print(f"💥 [CRITICAL ARCHIVE ERROR] {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/entities/records", response_model=List[schemas.EntityResponse])
def get_entity_records(domain: Optional[str] = None, status: Optional[str] = None, limit: int = 500, db: Session = Depends(database.get_db)):
    query = db.query(models.EntityRecord)
    if domain:
        query = query.filter(models.EntityRecord.domain == domain)
    if status:
        query = query.filter(models.EntityRecord.status == status)
    return query.order_by(models.EntityRecord.updated_at.desc()).limit(max(1, min(limit, 5000))).all()


@app.post("/api/entities/cleanup", response_model=schemas.EntityCleanupResponse)
def cleanup_entities(req: schemas.EntityCleanupRequest, db: Session = Depends(database.get_db)):
    query = db.query(models.EntityRecord)
    if req.domain:
        query = query.filter(models.EntityRecord.domain == req.domain)

    records = query.order_by(models.EntityRecord.updated_at.desc()).limit(
        max(1, min(req.delete_limit, 5000))).all()

    to_delete = []
    for record in records:
        payload = dict(record.payload or {})
        invalid = False

        if req.require_created_at and record.created_at is None:
            invalid = True

        if record.entity_id is None or str(record.entity_id).strip() == "":
            invalid = True

        for field in req.required_fields:
            value = _find_nested_path(payload, field)
            if value is None:
                invalid = True
                break
            if isinstance(value, str) and value.strip() == "":
                invalid = True
                break

        if invalid:
            to_delete.append(record)

    deleted_ids = [
        record.entity_id for record in to_delete[:50] if record.entity_id]

    if not req.dry_run:
        for record in to_delete:
            db.delete(record)
        db.commit()

    return schemas.EntityCleanupResponse(
        scanned=len(records),
        deleted=0 if req.dry_run else len(to_delete),
        sampled_deleted_ids=deleted_ids,
        dry_run=req.dry_run,
    )


# ==========================================
# SHORT-TERM MEMORY (Chat Sessions)
# ==========================================


@app.get("/api/chat/history/all")
def get_all_chat_history(db: Session = Depends(database.get_db)):
    return db.query(models.ChatHistory).order_by(models.ChatHistory.timestamp.desc()).all()


@app.delete("/api/chat/history/all")
def nuke_all_chat_history(db: Session = Depends(database.get_db)):
    deleted_count = db.query(models.ChatHistory).delete()
    db.commit()
    return {"status": "success", "deleted_messages": deleted_count}


@app.post("/api/chat/history", response_model=schemas.ChatMessageResponse)
def save_chat_message(message: schemas.ChatMessageCreate, db: Session = Depends(database.get_db)):
    db_msg = models.ChatHistory(**message.model_dump())
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)
    return db_msg


@app.get("/api/chat/history/{session_id}", response_model=List[schemas.ChatMessageResponse])
def get_chat_session(session_id: str, limit: int = 20, db: Session = Depends(database.get_db)):
    messages = db.query(models.ChatHistory).filter(models.ChatHistory.session_id == session_id).order_by(
        models.ChatHistory.timestamp.desc()).limit(limit).all()
    return list(reversed(messages))


@app.delete("/api/chat/history/{session_id}")
def delete_chat_history(session_id: str, db: Session = Depends(database.get_db)):
    deleted_count = db.query(models.ChatHistory).filter(
        models.ChatHistory.session_id == session_id).delete()
    db.commit()
    return {"status": "success", "deleted_messages": deleted_count}

# ==========================================
# LONG-TERM MEMORY (Cognitive Architecture)
# ==========================================


@app.post("/api/memory", response_model=schemas.PreferenceResponse)
def add_preference(pref: schemas.PreferenceCreate, db: Session = Depends(database.get_db)):
    db_pref = models.UserPreference(**pref.model_dump())
    db.add(db_pref)
    db.commit()
    db.refresh(db_pref)
    return db_pref


@app.get("/api/memory/active", response_model=List[schemas.PreferenceResponse])
def get_active_preferences(domain: Optional[str] = None, db: Session = Depends(database.get_db)):
    query = db.query(models.UserPreference).filter(
        models.UserPreference.is_active == True)
    if domain:
        query = query.filter(
            models.UserPreference.domain.in_([domain, "general"]))
    return query.all()


@app.patch("/api/memory/{pref_id}", response_model=schemas.PreferenceResponse)
def deprecate_preference(pref_id: int, update_data: schemas.PreferenceUpdate, db: Session = Depends(database.get_db)):
    db_pref = db.query(models.UserPreference).filter(
        models.UserPreference.id == pref_id).first()
    if not db_pref:
        raise HTTPException(status_code=404, detail="Preference not found")
    db_pref.is_active = update_data.is_active
    if update_data.weight is not None:
        db_pref.weight = update_data.weight
    db.commit()
    db.refresh(db_pref)
    return db_pref


@app.post("/api/subscriptions", response_model=schemas.SubscriptionResponse)
def upsert_subscription(req: schemas.SubscriptionUpsert, db: Session = Depends(database.get_db)):
    subscription = db.query(models.AlertSubscription).filter(
        models.AlertSubscription.subscription_id == req.subscription_id
    ).first()

    if subscription:
        subscription.owner = req.owner
        subscription.domain = req.domain
        subscription.event_type = req.event_type
        subscription.filters = req.filters
        subscription.channels = req.channels
        subscription.is_active = req.is_active
    else:
        subscription = models.AlertSubscription(**req.model_dump())
        db.add(subscription)

    db.commit()
    db.refresh(subscription)
    return subscription


@app.get("/api/subscriptions/active", response_model=List[schemas.SubscriptionResponse])
def get_active_subscriptions(domain: Optional[str] = None, event_type: Optional[str] = None, owner: Optional[str] = None, db: Session = Depends(database.get_db)):
    query = db.query(models.AlertSubscription).filter(
        models.AlertSubscription.is_active == True
    )
    if domain:
        query = query.filter(models.AlertSubscription.domain == domain)
    if event_type:
        query = query.filter(models.AlertSubscription.event_type == event_type)
    if owner:
        query = query.filter(models.AlertSubscription.owner == owner)

    return query.order_by(models.AlertSubscription.updated_at.desc()).limit(2000).all()


@app.patch("/api/subscriptions/{subscription_id}/active", response_model=schemas.SubscriptionResponse)
def update_subscription_active(subscription_id: str, req: schemas.SubscriptionActiveUpdate, db: Session = Depends(database.get_db)):
    subscription = db.query(models.AlertSubscription).filter(
        models.AlertSubscription.subscription_id == subscription_id
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.is_active = req.is_active
    db.commit()
    db.refresh(subscription)
    return subscription


@app.post("/api/dispatch/logs", response_model=schemas.DispatchLogResponse)
def create_dispatch_log(req: schemas.DispatchLogCreate, db: Session = Depends(database.get_db)):
    log = models.DispatchLog(**req.model_dump())
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@app.get("/api/dispatch/logs", response_model=List[schemas.DispatchLogResponse])
def get_dispatch_logs(subscription_id: Optional[str] = None, entity_id: Optional[str] = None, limit: int = 200, db: Session = Depends(database.get_db)):
    query = db.query(models.DispatchLog)
    if subscription_id:
        query = query.filter(
            models.DispatchLog.subscription_id == subscription_id)
    if entity_id:
        query = query.filter(models.DispatchLog.entity_id == entity_id)
    return query.order_by(models.DispatchLog.created_at.desc()).limit(max(1, min(limit, 2000))).all()


@app.get("/api/dispatch/logs/enriched")
def get_dispatch_logs_enriched(
    subscription_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 20,
    hours: Optional[int] = None,
    db: Session = Depends(database.get_db)
):
    """Get dispatch logs enriched with entity data for better formatting"""
    from datetime import datetime, timedelta, timezone

    query = db.query(models.DispatchLog)

    if subscription_id:
        query = query.filter(
            models.DispatchLog.subscription_id == subscription_id)
    if entity_id:
        query = query.filter(models.DispatchLog.entity_id == entity_id)

    # Filter by time if hours parameter provided
    if hours is not None and hours > 0:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = query.filter(models.DispatchLog.created_at >= cutoff_time)

    logs = query.order_by(models.DispatchLog.created_at.desc()).limit(
        max(1, min(limit, 500))).all()

    # Enrich logs with entity data
    enriched = []
    for log in logs:
        log_dict = {
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

        # Try to fetch entity data
        try:
            entity = db.query(models.EntityRecord).filter(
                models.EntityRecord.domain == log.domain,
                models.EntityRecord.entity_id == log.entity_id
            ).first()

            if entity and entity.payload:
                # Include key entity fields for formatting
                log_dict["entity_title"] = entity.payload.get("title")
                log_dict["entity_address"] = entity.payload.get("address")
                log_dict["entity_price"] = entity.payload.get("price")
                log_dict["entity_url"] = entity.payload.get(
                    "url") or log.entity_id
                log_dict["entity_summary"] = entity.payload.get("summary")
        except Exception:
            pass  # If entity fetch fails, continue with just log data

        enriched.append(log_dict)

    return enriched


# ==========================================
# CALENDAR ITEMS (Provider-agnostic memory)
# ==========================================


@app.post("/api/calendar/items", response_model=schemas.CalendarItemRead)
def upsert_calendar_item(
    item: schemas.CalendarItemCreate,
    db: Session = Depends(database.get_db),
):
    """Upsert a calendar event / task / reminder.

    When ``external_id`` + ``source`` match an existing row the row is updated.
    Otherwise a new row is created.  This ensures Ingest and Chronos can sync
    the same provider event without creating duplicates.
    """
    if item.external_id:
        existing = (
            db.query(models.CalendarItem)
            .filter(
                models.CalendarItem.external_id == item.external_id,
                models.CalendarItem.source == item.source,
            )
            .first()
        )
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


@app.get("/api/calendar/items", response_model=List[schemas.CalendarItemRead])
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
    """List calendar items with optional time-window and field filters.

    ``from_time`` / ``to_time`` accept ISO-8601 datetime strings.
    Set ``status_filter=confirmed`` to exclude cancelled events.
    """
    from datetime import datetime, timezone as _tz

    query = db.query(models.CalendarItem)

    if source:
        query = query.filter(models.CalendarItem.source == source)
    if kind:
        query = query.filter(models.CalendarItem.kind == kind)
    if status_filter:
        query = query.filter(models.CalendarItem.status == status_filter)
    if nag_enabled is not None:
        query = query.filter(models.CalendarItem.nag_enabled == nag_enabled)
    if from_time:
        try:
            dt = datetime.fromisoformat(from_time)
            query = query.filter(models.CalendarItem.start_at >= dt)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid from_time: {from_time}")
    if to_time:
        try:
            dt = datetime.fromisoformat(to_time)
            query = query.filter(models.CalendarItem.start_at <= dt)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid to_time: {to_time}")

    return (
        query.order_by(models.CalendarItem.start_at.asc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )


@app.get("/api/calendar/items/{item_id}", response_model=schemas.CalendarItemRead)
def get_calendar_item(item_id: int, db: Session = Depends(database.get_db)):
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    return item


@app.patch("/api/calendar/items/{item_id}/nag", response_model=schemas.CalendarItemRead)
def update_calendar_item_nag(
    item_id: int,
    req: schemas.CalendarItemNagUpdate,
    db: Session = Depends(database.get_db),
):
    """Enable or disable proactive notifications for a specific calendar item."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    item.nag_enabled = req.nag_enabled
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/calendar/items/{item_id}/notified", response_model=schemas.CalendarItemRead)
def update_calendar_item_notified(
    item_id: int,
    req: schemas.CalendarItemNotifiedUpdate,
    db: Session = Depends(database.get_db),
):
    """Record which notification bucket was last sent (used by the Chronos worker)."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    item.last_notified_bucket = req.last_notified_bucket
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/calendar/items/{item_id}")
def delete_calendar_item(item_id: int, db: Session = Depends(database.get_db)):
    """Delete a calendar item by its Archive id."""
    item = db.query(models.CalendarItem).filter(
        models.CalendarItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    db.delete(item)
    db.commit()
    return {"success": True}


@app.delete("/api/calendar/items/by-external/{source}/{external_id}")
def delete_calendar_item_by_external(
    source: str,
    external_id: str,
    db: Session = Depends(database.get_db),
):
    """Delete a calendar item by provider source + external_id (used by Chronos after provider delete)."""
    item = (
        db.query(models.CalendarItem)
        .filter(
            models.CalendarItem.source == source,
            models.CalendarItem.external_id == external_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    db.delete(item)
    db.commit()
    return {"success": True}


# ==========================================
# DOCUMENT STORAGE & RAG
# ==========================================


@app.post("/api/documents", response_model=schemas.DocumentRead)
def store_document(doc: schemas.DocumentIngest, db: Session = Depends(database.get_db)):
    """Ingest a document record with all pre-computed chunks.

    Idempotent: if ``document_id`` already exists the existing row is returned
    unchanged (Oracle fires this in a background thread and may retry).
    """
    existing = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == doc.document_id).first()
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
        db_chunk = models.DocumentChunk(
            document_id=doc.document_id,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            embedding=chunk.embedding if chunk.embedding else None,
        )
        db.add(db_chunk)

    db.commit()
    db.refresh(db_doc)
    return db_doc


@app.get("/api/documents", response_model=List[schemas.DocumentRead])
def list_documents(
    session_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    is_permanent: Optional[bool] = None,
    domain: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(database.get_db),
):
    """List stored documents, optionally filtered by session / chat / permanence / domain."""
    query = db.query(models.DocumentRecord)
    if session_id:
        query = query.filter(models.DocumentRecord.session_id == session_id)
    if chat_id:
        query = query.filter(models.DocumentRecord.chat_id == chat_id)
    if is_permanent is not None:
        query = query.filter(
            models.DocumentRecord.is_permanent == is_permanent)
    if domain:
        query = query.filter(models.DocumentRecord.domain ==
                             domain.lower().strip())
    return query.order_by(models.DocumentRecord.created_at.desc()).limit(max(1, min(limit, 200))).all()


@app.get("/api/documents/{document_id}", response_model=schemas.DocumentRead)
def get_document(document_id: str, db: Session = Depends(database.get_db)):
    doc = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(database.get_db)):
    """Delete a document and all its chunks."""
    doc = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.query(models.DocumentChunk).filter(
        models.DocumentChunk.document_id == document_id).delete()
    db.delete(doc)
    db.commit()
    return {"status": "deleted", "document_id": document_id}


@app.patch("/api/documents/{document_id}/permanent")
def update_document_permanent(
    document_id: str,
    update: schemas.DocumentPermanentUpdate,
    db: Session = Depends(database.get_db),
):
    """Toggle permanent / temporary status of a stored document."""
    doc = db.query(models.DocumentRecord).filter(
        models.DocumentRecord.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.is_permanent = update.is_permanent
    db.commit()
    return {"document_id": document_id, "is_permanent": doc.is_permanent}


@app.post("/api/documents/search", response_model=List[schemas.DocumentSearchResult])
def search_document_chunks(
    req: schemas.DocumentSearchRequest,
    db: Session = Depends(database.get_db),
):
    """Semantic search over document chunks using L2 vector distance.

    Joins chunks with their parent document to apply session/chat/permanence
    filters at the DB level.  Returns at most 2 chunks per document to avoid
    flooding context with repetitive text.
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
    accessed_doc_ids: set[str] = set()

    for chunk, doc, distance in rows:
        dist_f = float(distance)
        if dist_f > req.threshold:
            break  # Ordered by distance — safe to stop early
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
        accessed_doc_ids.add(doc_id)
        if len(results) >= req.limit:
            break

    # Update access tracking for every document that surfaced in results
    if req.track_access and accessed_doc_ids:
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc)
        db.query(models.DocumentRecord).filter(
            models.DocumentRecord.document_id.in_(accessed_doc_ids)
        ).update(
            {"last_accessed_at": now,
                "access_count": models.DocumentRecord.access_count + 1},
            synchronize_session=False,
        )
        db.commit()

    return results


@app.delete("/api/documents/prune")
def prune_documents(
    req: schemas.DocumentPruneRequest,
    db: Session = Depends(database.get_db),
):
    """Bulk-delete non-permanent documents that are stale and rarely accessed.

    A document is pruned when ALL of the following are true:
    - ``is_permanent`` is False
    - Last access (or creation, if never retrieved) is older than ``idle_days`` days
    - ``access_count`` ≤ ``max_access_count``

    Pass ``dry_run=true`` to see what would be deleted without committing.
    """
    from datetime import datetime, timezone as _tz, timedelta
    cutoff = datetime.now(_tz.utc) - timedelta(days=req.idle_days)

    # A document counts as "idle" if it was never accessed (last_accessed_at IS NULL
    # and created_at < cutoff) OR if last_accessed_at < cutoff.
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
        return {
            "dry_run": True,
            "would_delete": len(candidate_ids),
            "document_ids": candidate_ids,
        }

    if candidate_ids:
        db.query(models.DocumentChunk).filter(
            models.DocumentChunk.document_id.in_(candidate_ids)
        ).delete(synchronize_session=False)
        db.query(models.DocumentRecord).filter(
            models.DocumentRecord.document_id.in_(candidate_ids)
        ).delete(synchronize_session=False)
        db.commit()

    return {
        "dry_run": False,
        "deleted": len(candidate_ids),
        "document_ids": candidate_ids,
    }
