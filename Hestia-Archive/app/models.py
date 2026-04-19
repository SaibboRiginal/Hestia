from sqlalchemy import Column, String, Integer, DateTime, Boolean, Float, Index, UniqueConstraint
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


class CalendarItem(Base):
    """Provider-agnostic calendar event / task / reminder stored for assistant memory.

    Persisted by Chronos (after create/update) and by Ingest (calendar fetch runs).
    Consumed by the Chronos notification worker for proactive reminders via Hermes.
    Generic enough to accommodate any calendar source — Google, Outlook, and future
    providers such as a native Hestia calendar.
    """
    __tablename__ = "calendar_items"

    id = Column(Integer, primary_key=True, index=True)
    # Provider-issued event id.  None for natively-created Hestia items.
    external_id = Column(String, nullable=True, index=True)
    # Originating system: "google", "outlook", "hestia", …
    source = Column(String, nullable=False, index=True)
    # "event", "task", or "reminder"
    kind = Column(String, nullable=False, default="event", index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=True)
    all_day = Column(Boolean, default=False, nullable=False)
    location = Column(String, nullable=True)
    # List of {"name": "…", "email": "…"} dicts.
    attendees = Column(JSONB, nullable=True, default=list)
    # RRULE string for recurring events, e.g. "RRULE:FREQ=WEEKLY;BYDAY=MO"
    recurrence = Column(String, nullable=True)
    # "confirmed" / "tentative" / "cancelled" / "completed"
    status = Column(String, nullable=False, default="confirmed", index=True)
    html_link = Column(String, nullable=True)
    # Whether the notification worker should nag about this item
    nag_enabled = Column(Boolean, default=True, nullable=False)
    # Last notification bucket sent: "1d", "2h", "30m" — prevents duplicate nags
    last_notified_bucket = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        # Unique per (external_id, source) when external_id is provided.
        # PostgreSQL treats two NULLs as distinct so this correctly allows
        # multiple Hestia-native items (external_id=NULL) per source.
        UniqueConstraint("external_id", "source",
                         name="uq_calendar_external_source"),
        Index("ix_calendar_items_start_at", "start_at"),
    )


class DocumentRecord(Base):
    """A document uploaded by the user and stored for history and RAG retrieval.

    Files are analysed by Oracle, their text is extracted and chunked into
    ``DocumentChunk`` rows, each with its own embedding vector.  The
    ``DocumentRecord`` itself carries a document-level summary embedding for
    coarse-grained filtering.

    Lifecycle tracking
    ------------------
    ``last_accessed_at`` is updated every time a chunk from this document is
    returned by the semantic search endpoint.  ``access_count`` is the total
    number of times this has happened.  Together they allow pruning strategies
    such as "delete non-permanent documents not accessed in the last 30 days
    with fewer than 3 total retrievals".

    ``tags`` is a JSON-encoded list of short keywords assigned by the LLM at
    ingestion time (e.g. ``["contract", "lease", "2024"]``).

    ``file_hash`` is the SHA-256 hex digest of the original file bytes.  It
    lets future code detect duplicate uploads and could be used to re-associate
    a stored byte-blob once object storage is wired up.
    """
    __tablename__ = "document_records"

    id = Column(Integer, primary_key=True, index=True)
    # Stable, caller-assigned UUID (hex, no dashes)
    document_id = Column(String, unique=True, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    # Telegram chat_id as string — used to scope retrieval to the right user
    chat_id = Column(String, index=True, nullable=True)
    filename = Column(String, nullable=True)
    mime_type = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    # SHA-256 of original file bytes — for dedup and future object-storage recall
    file_hash = Column(String, nullable=True, index=True)
    # LLM-generated metadata
    title = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    # Truncated full extracted text (max ~40k chars)
    extracted_text = Column(String, nullable=True)
    # Document-level summary embedding for coarse-grained semantic search
    embedding = Column(Vector(768), nullable=True)
    chunk_count = Column(Integer, default=0, nullable=False)
    # If True the document is never auto-expired and is always included in RAG
    is_permanent = Column(Boolean, default=False, nullable=False, index=True)
    # Hestia domain this document belongs to (LLM-assigned at ingest time)
    domain = Column(String, default="documents", nullable=False, index=True)
    # JSON-encoded list of short keyword tags, e.g. '["lease","2024","contract"]'
    tags = Column(String, nullable=True)

    # ── Lifecycle / access tracking ───────────────────────────────────────────
    # Incremented every time a chunk from this document surfaces in RAG search
    access_count = Column(Integer, default=0, nullable=False)
    # Set to now() on every RAG hit — used for LRU-style pruning
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        Index("ix_document_records_session_chat", "session_id", "chat_id"),
    )


class DocumentChunk(Base):
    """Individual semantic chunk of a DocumentRecord.

    Each chunk stores its own embedding vector (contextualised by prepending
    the document title + summary) so that fine-grained semantic search can
    pinpoint the most relevant passage inside a document.
    """
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, index=True, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(String, nullable=False)
    # Contextualised chunk embedding (title+summary prepended before embedding)
    embedding = Column(Vector(768), nullable=True)

    __table_args__ = (
        Index("ix_document_chunks_document_id", "document_id"),
    )
