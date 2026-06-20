from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# --- INGEST & ARCHIVE SCHEMAS ---


class RecordCreate(BaseModel):
    reference_id: Optional[str] = Field(
        None, description="Unique fingerprint (Message-ID, URL, etc.)")
    domain: str = Field(...,
                        description="The category of data (e.g., 'real_estate')")
    source: str = Field(...,
                        description="Where it came from (e.g., 'gmail_imap')")
    payload: Dict[str, Any] = Field(...,
                                    description="The actual flexible data")


class RecordResponse(RecordCreate):
    id: int
    is_evaluated: bool

    class Config:
        from_attributes = True


class RecordUpdate(BaseModel):
    evaluation: Dict[str, Any] = Field(...,
                                       description="The AI's score and reasoning")

# --- ENTITY SCHEMAS ---


class EntityUpsert(BaseModel):
    entity_id: str = Field(...,
                           description="The unique link or ID of the house")
    domain: str = Field(..., description="e.g., 'real_estate'")
    status: str = Field(
        "active", description="e.g., 'active', 'sold', 'removed'")
    payload: Dict[str, Any] = Field(...,
                                    description="The structured house data")
    embedding: Optional[List[float]] = Field(
        None, description="The mathematical vector for RAG")


class EntityResponse(EntityUpsert):
    id: int
    created_at: Any
    updated_at: Any

    class Config:
        from_attributes = True

# 🆕 SEARCH SCHEMAS (Moved from main.py)


class AdvancedSearchRequest(BaseModel):
    domain: Optional[str] = None
    limit: int = 20
    query_vector: Optional[List[float]] = None
    filters: Optional[Dict[str, Any]] = None
    filters_gt: Optional[Dict[str, float]] = None
    filters_lt: Optional[Dict[str, float]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = Field(
        default="desc", pattern="^(asc|desc)$")


class EntityCleanupRequest(BaseModel):
    domain: Optional[str] = None
    required_fields: List[str] = Field(default_factory=list)
    require_created_at: bool = True
    delete_limit: int = 500
    dry_run: bool = False


class EntityCleanupResponse(BaseModel):
    scanned: int
    deleted: int
    sampled_deleted_ids: List[str]
    dry_run: bool


class ModuleMaintenanceRequest(BaseModel):
    source: str = "oracle"
    task_id: Optional[str] = None
    issue: Optional[str] = None
    requested_action: Optional[str] = "reconcile_entities"
    environment: str = "dev"
    dry_run: bool = True
    domain: Optional[str] = None
    required_fields: List[str] = Field(default_factory=list)
    require_created_at: bool = True
    delete_limit: int = 500
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModuleMaintenanceResponse(BaseModel):
    status: str
    service: str
    dry_run: bool
    task_id: str
    executed_at: datetime
    retriable: bool
    summary: str
    mutation_count: int
    details: Dict[str, Any]

# --- CHAT HISTORY SCHEMAS ---


class ChatMessageCreate(BaseModel):
    session_id: str
    role: str
    content: str


class ChatMessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    timestamp: datetime

    class Config:
        from_attributes = True

# --- USER PREFERENCE SCHEMAS ---


class PreferenceCreate(BaseModel):
    fact: str
    domain: str = "general"
    weight: float = 1.0
    memory_class: Optional[str] = None
    embedding: Optional[list[float]] = None
    domains: Optional[list[str]] = None
    extra_data: Optional[dict] = None


class PreferenceUpdate(BaseModel):
    is_active: bool
    weight: Optional[float] = None


class PreferenceResponse(BaseModel):
    id: int
    fact: str
    domain: str
    weight: float
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    memory_class: Optional[str] = None
    embedding: Optional[list[float]] = None
    domains: Optional[list[str]] = None
    extra_data: Optional[dict] = None

    class Config:
        from_attributes = True


class SubscriptionUpsert(BaseModel):
    subscription_id: str
    owner: str
    domain: str
    event_type: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    channels: List[Dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class SubscriptionResponse(SubscriptionUpsert):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class SubscriptionActiveUpdate(BaseModel):
    is_active: bool


class DispatchLogCreate(BaseModel):
    subscription_id: str
    event_type: str
    domain: str
    entity_id: str
    channel: str
    target: str
    success: bool
    detail: Optional[str] = None


class DispatchLogResponse(DispatchLogCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class InteractionLedgerCreate(BaseModel):
    session_id: Optional[str] = None
    actor: str = "assistant"
    event_type: str
    domain: str = "general"
    source_service: str = "oracle"
    reference_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class InteractionLedgerResponse(InteractionLedgerCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


OutboundLifecycleState = Literal[
    "created",
    "queued",
    "delivered",
    "seen",
    "answered",
    "dismissed",
    "superseded",
    "failed",
]


class OutboundEventUpsert(BaseModel):
    outbound_event_id: str
    dedupe_key: str
    lifecycle_state: OutboundLifecycleState = "created"
    event_type: str
    domain: str = "general"
    entity_id: Optional[str] = None
    subscription_id: Optional[str] = None
    channel: Optional[str] = None
    target: Optional[str] = None
    question_id: Optional[str] = None
    brief_id: Optional[str] = None
    source_service: str = "hermes"
    superseded_by: Optional[str] = None
    detail: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class OutboundEventStateUpdate(BaseModel):
    lifecycle_state: OutboundLifecycleState
    detail: Optional[str] = None
    superseded_by: Optional[str] = None


class OutboundEventResponse(OutboundEventUpsert):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


FeedbackQualityLabel = Literal[
    "excellent",
    "good",
    "mixed",
    "poor",
    "rejected",
]


class FeedbackCreate(BaseModel):
    feedback_id: Optional[str] = None
    session_id: Optional[str] = None
    interaction_id: Optional[str] = None
    source_service: str = "oracle"
    source_client: Optional[str] = None
    quality_label: FeedbackQualityLabel
    quality_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="Optional 1-5 explicit score from user/client",
    )
    outcome_label: Optional[str] = None
    feedback_text: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)


class FeedbackResponse(FeedbackCreate):
    id: int
    feedback_id: str
    created_at: datetime

    class Config:
        from_attributes = True


# --- CALENDAR ITEM SCHEMAS ---


class CalendarItemCreate(BaseModel):
    """Upsert payload for a calendar event / task / reminder.

    If ``external_id`` + ``source`` already exist the existing row is updated;
    otherwise a new row is inserted.  When ``external_id`` is omitted a new row
    is always inserted (used for Hestia-native items without a provider id).
    """
    external_id: Optional[str] = Field(
        None, description="Provider-issued id (Google event id, Outlook event id, …)")
    source: str = Field(
        ..., description="Origin system: 'google', 'outlook', 'hestia', …")
    kind: str = Field(
        "event", description="'event', 'task', or 'reminder'")
    title: str
    description: Optional[str] = None
    start_at: datetime = Field(..., description="Event start (timezone-aware)")
    end_at: Optional[datetime] = Field(
        None, description="Event end — may be None for reminders/tasks")
    all_day: bool = False
    location: Optional[str] = None
    attendees: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list, description='[{"name": "…", "email": "…"}, …]')
    recurrence: Optional[str] = Field(
        None, description="RRULE string for recurring items")
    status: str = Field(
        "confirmed", description="confirmed / tentative / cancelled / completed")
    html_link: Optional[str] = None
    nag_enabled: bool = Field(
        True, description="Whether the notification worker should nag about this item")


class CalendarItemRead(CalendarItemCreate):
    id: int
    last_notified_bucket: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CalendarItemNagUpdate(BaseModel):
    """Toggle nag on or off for a specific calendar item."""
    nag_enabled: bool


class CalendarItemNotifiedUpdate(BaseModel):
    """Record which notification bucket was last sent for deduplication."""
    last_notified_bucket: str = Field(
        ..., description="'1d', '2h', or '30m'")


# --- DOCUMENT STORAGE & RAG SCHEMAS ---

class DocumentChunkIngest(BaseModel):
    """A single chunk to store alongside a DocumentRecord."""
    chunk_index: int
    chunk_text: str
    embedding: Optional[List[float]] = Field(
        None, description="Pre-computed embedding vector for this chunk")


class DocumentIngest(BaseModel):
    """Full payload to store a document with all its chunks in one request."""
    document_id: str = Field(...,
                             description="Caller-assigned UUID hex (no dashes)")
    session_id: str
    chat_id: Optional[str] = Field(
        None, description="Telegram chat_id as string")
    filename: Optional[str] = None
    mime_type: str
    file_size_bytes: Optional[int] = None
    # SHA-256 hex digest of original file bytes (for dedup / future blob recall)
    file_hash: Optional[str] = None
    title: Optional[str] = Field(
        None, description="LLM-generated document title")
    summary: Optional[str] = Field(
        None, description="2-3 sentence LLM summary")
    extracted_text: Optional[str] = Field(
        None, description="Truncated full extracted text (max ~40k chars)")
    embedding: Optional[List[float]] = Field(
        None, description="Document-level summary embedding")
    is_permanent: bool = False
    # Hestia domain this document belongs to (LLM-assigned)
    domain: Optional[str] = Field(
        None, description="Hestia domain slug, e.g. 'real_estate'")
    # JSON-encoded list of keyword tags, e.g. '["lease","2024","contract"]'
    tags: Optional[str] = Field(
        None, description="JSON-encoded list of keyword tags")
    chunks: List[DocumentChunkIngest] = Field(default_factory=list)


class DocumentRead(BaseModel):
    """Public representation of a stored document (no raw text or embeddings)."""
    document_id: str
    session_id: str
    chat_id: Optional[str] = None
    filename: Optional[str] = None
    mime_type: str
    file_size_bytes: Optional[int] = None
    file_hash: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    chunk_count: int
    is_permanent: bool
    domain: str = "documents"
    tags: Optional[str] = None          # JSON-encoded list string
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentPermanentUpdate(BaseModel):
    is_permanent: bool


class DocumentSearchRequest(BaseModel):
    """Semantic chunk search request."""
    query_vector: List[float]
    chat_id: Optional[str] = None
    session_id: Optional[str] = None
    is_permanent: Optional[bool] = None
    # Filter by domain (e.g. only search within 'real_estate' docs)
    domain: Optional[str] = None
    limit: int = Field(5, ge=1, le=20)
    threshold: float = Field(
        1.2, description="Maximum L2 distance to consider relevant (lower = stricter)")
    # When True, update last_accessed_at + access_count for matched documents
    track_access: bool = True


class DocumentSearchResult(BaseModel):
    """A chunk that matched the semantic query, with its parent document metadata."""
    document_id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    chunk_text: str
    chunk_index: int
    distance: float
    is_permanent: bool
    domain: str = "documents"
    tags: Optional[str] = None
    created_at: datetime
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0


class DocumentPruneRequest(BaseModel):
    """Parameters for bulk-pruning old non-permanent documents."""
    # Prune docs not accessed for more than this many days
    idle_days: int = Field(
        30, ge=1, description="Days since last access (or creation if never accessed)")
    # Also require total access count to be below this threshold (0 = never retrieved)
    max_access_count: int = Field(0, ge=0)
    # Dry-run: return what would be deleted without actually deleting
    dry_run: bool = False
