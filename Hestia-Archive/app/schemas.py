from typing import Dict, Any, Optional, List
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
