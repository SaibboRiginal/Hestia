from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Boolean, Float, Index, UniqueConstraint, Sequence, LargeBinary
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
    """Memoria a lungo termine: fatti, preferenze, e skill procedurali."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    fact = Column(String, nullable=False)
    domain = Column(String, index=True)
    weight = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    memory_class = Column(String, index=True, nullable=True)
    embedding = Column(Vector(768), nullable=True)
    domains = Column(JSONB, nullable=True)
    extra_data = Column(JSONB, nullable=True)
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


class InteractionLedgerRecord(Base):
    """Compact typed interaction events for behavior/state tracking."""
    __tablename__ = "interaction_ledger"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=True)
    actor = Column(String, index=True, nullable=False, default="assistant")
    event_type = Column(String, index=True, nullable=False)
    domain = Column(String, index=True, nullable=False, default="general")
    source_service = Column(
        String, index=True, nullable=False, default="oracle")
    reference_id = Column(String, index=True, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_interaction_ledger_payload_gin",
              payload, postgresql_using="gin"),
    )


class OutboundEventRecord(Base):
    """Delivery lifecycle state for a logical outbound event."""
    __tablename__ = "outbound_events"

    id = Column(Integer, primary_key=True, index=True)
    outbound_event_id = Column(String, unique=True, index=True, nullable=False)
    dedupe_key = Column(String, index=True, nullable=False)
    lifecycle_state = Column(
        String, index=True, nullable=False, default="created")

    event_type = Column(String, index=True, nullable=False)
    domain = Column(String, index=True, nullable=False, default="general")
    entity_id = Column(String, index=True, nullable=True)
    subscription_id = Column(String, index=True, nullable=True)
    channel = Column(String, index=True, nullable=True)
    target = Column(String, nullable=True)

    question_id = Column(String, index=True, nullable=True)
    brief_id = Column(String, index=True, nullable=True)
    source_service = Column(
        String, index=True, nullable=False, default="hermes")
    superseded_by = Column(String, index=True, nullable=True)
    detail = Column(String, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(
    ), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_outbound_events_payload_gin",
              payload, postgresql_using="gin"),
    )


class FeedbackRecord(Base):
    """User and client quality feedback used for tuning/evaluation exports."""
    __tablename__ = "feedback_records"

    id = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(String, unique=True, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=True)
    interaction_id = Column(String, index=True, nullable=True)
    source_service = Column(
        String, index=True, nullable=False, default="oracle")
    source_client = Column(String, index=True, nullable=True)
    quality_label = Column(String, index=True, nullable=False)
    quality_score = Column(Integer, index=True, nullable=True)
    outcome_label = Column(String, index=True, nullable=True)
    feedback_text = Column(String, nullable=True)
    tags = Column(JSONB, nullable=False, default=list)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_feedback_records_payload_gin",
              payload, postgresql_using="gin"),
        Index("ix_feedback_records_tags_gin", tags, postgresql_using="gin"),
    )


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
    # Free-form metadata (assistant agenda: type, owner, action, skips, rules…)
    meta = Column(JSONB, nullable=True, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        # Unique per (external_id, source) when external_id is provided.
        # PostgreSQL treats two NULLs as distinct so this correctly allows
        # multiple Hestia-native items (external_id=NULL) per source.
        UniqueConstraint("external_id", "source",
                         name="uq_calendar_external_source"),
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


# ── Settings storage (logic lives in Themis; Archive only stores) ─────────────

class SettingValue(Base):
    """One stored setting value. ``scope``: system | profile | client | session."""
    __tablename__ = "setting_values"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, index=True, nullable=False)
    scope = Column(String, nullable=False, default="system")
    scope_id = Column(String, nullable=False, default="")
    value = Column(JSONB, nullable=True)
    updated_by = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    __table_args__ = (UniqueConstraint("key", "scope", "scope_id", name="uq_setting_values_key_scope"),)


class SettingHistory(Base):
    """Light change log (last N per key/scope, trimmed on write) used for undo."""
    __tablename__ = "setting_history"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, index=True, nullable=False)
    scope = Column(String, nullable=False, default="system")
    scope_id = Column(String, nullable=False, default="")
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    actor = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SettingProposal(Base):
    """A change proposed by the assistant, applied only after the user's answer."""
    __tablename__ = "setting_proposals"

    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(String, unique=True, index=True, nullable=False)
    key = Column(String, index=True, nullable=False)
    scope = Column(String, nullable=False, default="system")
    scope_id = Column(String, nullable=False, default="")
    value = Column(JSONB, nullable=True)
    reason = Column(String, nullable=True)
    proposer = Column(String, nullable=True)
    status = Column(String, index=True, nullable=False, default="pending")
    decided_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    decided_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


# ── Assistant presence (owner of the semantics: Chronos) ─────────────────────

class PresenceSignal(Base):
    """One live fact reported to the presence engine (last interaction, a running activity,
    a manual switch, a resource level). ``expires_at`` lets a crashed reporter heal itself."""
    __tablename__ = "presence_signals"

    key = Column(String, primary_key=True)
    value = Column(JSONB, nullable=True)
    meta = Column(JSONB, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class PresenceSnapshot(Base):
    """The current composite state (single row, id=1) so every client reads it after a restart."""
    __tablename__ = "presence_snapshot"

    id = Column(Integer, primary_key=True)
    data = Column(JSONB, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class PresenceChange(Base):
    """Light history of state changes (trimmed on write)."""
    __tablename__ = "presence_changes"

    id = Column(Integer, primary_key=True, index=True)
    data = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Chat queue (brain offline) — owner of the semantics: each chat client ─────

class ChatQueueItem(Base):
    """A chat message written while Oracle was offline; its client answers it when the brain returns
    (SPEC docs/work/2026-10-19-cervello-offline). ``state``: queued → answering → answered | failed."""
    __tablename__ = "chat_queue"

    id = Column(Integer, primary_key=True, index=True)
    client = Column(String, index=True, nullable=False)
    session_id = Column(String, nullable=False)
    target = Column(String, nullable=True)
    client_ref = Column(String, nullable=True)
    text = Column(String, nullable=False)
    meta = Column(JSONB, nullable=True)
    state = Column(String, index=True, nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    answered_at = Column(DateTime(timezone=True), nullable=True)


# ── Hercules (gym coach) storage — owner of the semantics: Hestia-Hercules ───

HERCULES_SEQ = Sequence("hercules_records_seq", metadata=Base.metadata)


class HerculesRecord(Base):
    """One synced row of the gym coach (exercise, template, program, session, set, measurement, feedback,
    adaptation, goal). Ids are client UUIDs (offline first); ``updated_at`` is the writer's clock for
    last-write-wins; ``seq`` grows on every write and is the sync cursor; deletes are tombstones."""
    __tablename__ = "hercules_records"

    kind = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    parent_id = Column(String, nullable=True, index=True)   # set → session, feedback → session…
    ref_id = Column(String, nullable=True, index=True)      # set → exercise, measurement → its kind…
    at = Column(DateTime(timezone=True), nullable=True)     # the row's time (session start, measurement…)
    data = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, HERCULES_SEQ, nullable=False, index=True)

    __table_args__ = (Index("ix_hercules_kind_at", "kind", "at"),
                      Index("ix_hercules_kind_ref", "kind", "ref_id"))


# ── Hygieia (self care) storage — owner of the semantics: Hestia-Hygieia ─────

SELFCARE_SEQ = Sequence("selfcare_records_seq", metadata=Base.metadata)


class SelfcareRecord(Base):
    """One row of the self care module (product, product event, routine, routine version, log, journal entry,
    custom option, reminder state). ``updated_at`` is the writer's clock for last-write-wins; ``seq`` grows on
    every write (mirror cursor); deletes are tombstones."""
    __tablename__ = "selfcare_records"

    kind = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    parent_id = Column(String, nullable=True, index=True)   # log → routine, version → routine, event → product
    ref_id = Column(String, nullable=True, index=True)      # product → product_key, log → date…
    at = Column(DateTime(timezone=True), nullable=True)     # the row's time (log done_at, event at…)
    data = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, SELFCARE_SEQ, nullable=False, index=True)

    __table_args__ = (Index("ix_selfcare_kind_at", "kind", "at"),
                      Index("ix_selfcare_kind_ref", "kind", "ref_id"))


# ── Wardrobe storage — owner of the semantics: Hestia-Wardrobe ───────────────

WARDROBE_SEQ = Sequence("wardrobe_records_seq", metadata=Base.metadata)


class WardrobeRecord(Base):
    """One row of the wardrobe (piece, outfit, wear, taxonomy, collection…), same shape as the Hercules store:
    ``updated_at`` = writer's clock for last-write-wins, ``seq`` = change cursor, deletes are tombstones."""
    __tablename__ = "wardrobe_records"

    kind = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    parent_id = Column(String, nullable=True, index=True)   # wear → outfit
    ref_id = Column(String, nullable=True, index=True)
    at = Column(DateTime(timezone=True), nullable=True)     # wear date, purchase date…
    data = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, WARDROBE_SEQ, nullable=False, index=True)

    __table_args__ = (Index("ix_wardrobe_kind_at", "kind", "at"),)


# ── Blob store — generic binary files (photos) for any module ───────────────

class BlobRecord(Base):
    """A binary file (photo, thumbnail) owned by a module. Pure storage: the meaning of ``meta`` and which
    blobs belong together is the owner's business. Deduped per module by sha256."""
    __tablename__ = "blobs"

    blob_id = Column(String, primary_key=True)
    owner_module = Column(String, nullable=False, index=True)
    content_type = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False, index=True)
    data = Column(LargeBinary, nullable=False)
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("owner_module", "sha256", name="uq_blobs_owner_sha"),)


# ── MCP accesses — owner of the semantics: Hestia-MCP ───────────────────────

class MCPAccess(Base):
    """Who may use Hestia's MCP from outside (an external AI). Pure storage: Hestia-MCP decides what a scope
    allows. Tokens only as a sha256 hash (shown once at creation, never stored in clear)."""
    __tablename__ = "mcp_accesses"

    access_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="token")        # token | oauth
    scope = Column(String, nullable=False, default="read")        # read | write
    tools = Column(JSONB, nullable=False, default=list)           # [] = every tool open to external clients
    token_hash = Column(String, nullable=True, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    calls_date = Column(String, nullable=True)                    # YYYY-MM-DD of calls_day
    calls_day = Column(Integer, nullable=False, default=0)
    calls_total = Column(BigInteger, nullable=False, default=0)
    # OAuth accesses (kind oauth, docs/work/2026-10-18-moduli-core-e-mcp-esterno §B6): token_hash = the current
    # short-lived access token, refresh_hash = the current refresh token (rotated on use; the previous one is kept
    # to spot a replay), token_expires_at = when the access token stops. Hashes only.
    client_id = Column(String, nullable=True, index=True)
    refresh_hash = Column(String, nullable=True, unique=True, index=True)
    prev_refresh_hash = Column(String, nullable=True, index=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MCPOAuthClient(Base):
    """An OAuth client registered by itself (RFC 7591 dynamic registration: claude.ai, ChatGPT…). The client id is
    public; a client secret, when there is one, only as a sha256 hash. Semantics: Hestia-MCP."""
    __tablename__ = "mcp_oauth_clients"

    client_id = Column(String, primary_key=True)
    client_name = Column(String, nullable=False)
    redirect_uris = Column(JSONB, nullable=False, default=list)
    auth_method = Column(String, nullable=False, default="none")     # none | client_secret_post | client_secret_basic
    secret_hash = Column(String, nullable=True)
    meta = Column(JSONB, nullable=False, default=dict)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MCPOAuthCode(Base):
    """A one-time authorization code issued on the WebUI consent page (only its sha256). It carries what Marko chose
    there (scope, tools, expiry); used once, then ``access_id`` names the access it became."""
    __tablename__ = "mcp_oauth_codes"

    code_hash = Column(String, primary_key=True)
    client_id = Column(String, nullable=False, index=True)
    redirect_uri = Column(String, nullable=False)
    code_challenge = Column(String, nullable=False)
    scope = Column(String, nullable=False, default="read")
    tools = Column(JSONB, nullable=False, default=list)
    name = Column(String, nullable=False)
    expires_days = Column(Integer, nullable=True)
    resource = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    access_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── LLM usage — owner of the semantics: Hestia-Oracle (docs/work/2026-10-19-oracle-a-blocchi §E) ───

class LLMUsage(Base):
    """One LLM call made by Oracle (a chain step, Forge's chat, an agent run): who asked (module from the use case
    prefix, client, session), which step of which chain answered, tokens, duration, cost and outcome. Pushed by
    Oracle in small batches; rows older than Oracle's retention are removed on write."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True)
    at = Column(DateTime(timezone=True), nullable=False, index=True)
    module = Column(String, nullable=False, index=True)
    use_case = Column(String, nullable=False, index=True)
    chain = Column(String, nullable=True)
    step = Column(Integer, nullable=False, default=0)
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    client = Column(String, nullable=True)
    session_id = Column(String, nullable=True, index=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    context_window = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    cost_kind = Column(String, nullable=True)          # api | abbonamento | locale | sconosciuto
    outcome = Column(String, nullable=False, default="ok")   # ok | quota | error
    detail = Column(String, nullable=True)
