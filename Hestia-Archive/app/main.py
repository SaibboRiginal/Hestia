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
        "HUB_API_URL", "http://hestia_hub:8005/api").rstrip("/")
    service_base_url = os.getenv(
        "ARCHIVE_SERVICE_BASE_URL", "http://hestia_archive:8000")
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
