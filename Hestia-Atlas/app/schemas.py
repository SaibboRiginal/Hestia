from typing import Literal, Optional

from pydantic import BaseModel, Field


class FetchHtmlRequest(BaseModel):
    url: str = Field(min_length=8)
    timeout_seconds: int = Field(default=30, ge=3, le=120)
    wait_ms: int = Field(default=3000, ge=0, le=20000)
    strategy: Literal["edge_cdp", "cdp"] = "edge_cdp"
    cdp_endpoint: Optional[str] = None


class FetchHtmlResponse(BaseModel):
    status: Literal["ok", "error"]
    fetch_method: Optional[str] = None
    url: str
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    blocked: bool = False
    content_length: int = 0
    html: str = ""
    error: Optional[str] = None
