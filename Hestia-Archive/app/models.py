from sqlalchemy import Column, String, Integer, DateTime, Boolean, Float, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from .database import Base
from typing import List, Optional


class ArchiveRecord(Base):
    """Data Lake per i record grezzi in arrivo dagli Ingest."""
    __tablename__ = "archive_records"

    id = Column(Integer, primary_key=True, index=True)
    reference_id = Column(String, unique=True, index=True, nullable=True)
    domain = Column(String, index=True)
    source = Column(String, index=True)
    payload = Column(JSONB, nullable=False)
    is_evaluated = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_archive_payload_gin', payload, postgresql_using='gin'),
    )


class EntityRecord(Base):
    """Rappresenta oggetti del mondo reale (es. Case) processati."""
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(String, unique=True, index=True, nullable=False)
    domain = Column(String, index=True)
    status = Column(String, default="active", index=True)
    payload = Column(JSONB, nullable=False)
    # RAG: Vettori a 768 dimensioni per Nomic-Embed-Text
    embedding = Column(Vector(768), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        Index('ix_entities_payload_gin', payload, postgresql_using='gin'),
    )


class ChatHistory(Base):
    """Memoria a breve termine delle sessioni chat."""
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class UserPreference(Base):
    """Memoria a lungo termine: fatti e regole sull'utente."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    fact = Column(String, nullable=False)
    domain = Column(String, index=True)
    weight = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AlertSubscription(Base):
    __tablename__ = "alert_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(String, unique=True, index=True, nullable=False)
    owner = Column(String, index=True, nullable=False)
    domain = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    filters = Column(JSONB, nullable=False, default=dict)
    channels = Column(JSONB, nullable=False, default=list)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        onupdate=func.now(), server_default=func.now())


class DispatchLog(Base):
    __tablename__ = "dispatch_logs"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    domain = Column(String, index=True, nullable=False)
    entity_id = Column(String, index=True, nullable=False)
    channel = Column(String, index=True, nullable=False)
    target = Column(String, nullable=False)
    success = Column(Boolean, default=False, index=True)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
