from typing import Optional

from pydantic import BaseModel, Field


class RealEstateSearchRequest(BaseModel):
    query: str = ""
    limit: int = Field(default=12, ge=1, le=50)
    city: Optional[str] = None
    nearby: bool = False
    radius_km: float = Field(default=20.0, ge=1.0, le=200.0)
    price_max: Optional[float] = None
    price_min: Optional[float] = None
    rooms_min: Optional[float] = None
    surface_min: Optional[float] = None


class ModuleToolQueryRequest(BaseModel):
    domain: str
    query: str = ""
    session_id: Optional[str] = None
    limit: int = Field(default=12, ge=1, le=50)
    filters: dict = Field(default_factory=dict)
    filters_gt: dict = Field(default_factory=dict)
    filters_lt: dict = Field(default_factory=dict)
    sort_by: Optional[str] = None
    sort_order: str = "desc"
    preferences: list[str] = Field(default_factory=list)
