from typing import Optional

from pydantic import BaseModel, Field, model_validator


def _first(d: dict, *keys):
    for key in keys:
        if isinstance(d, dict) and d.get(key) not in (None, ""):
            return d.get(key)
    return None


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

    @model_validator(mode="before")
    @classmethod
    def _from_filter_dicts(cls, data):
        """The tool used to advertise ``filters`` / ``filters_gt`` / ``filters_lt`` dicts that this model ignored,
        so «houses under 200k in <city>» from the chat came back unfiltered. Those dicts are still read
        (a model may keep sending them) and mapped on the flat fields; a flat field given explicitly wins."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        eq, gt, lt = data.get("filters") or {}, data.get("filters_gt") or {}, data.get("filters_lt") or {}
        mapped = {
            "city": _first(eq, "city", "location", "town"),
            "price_min": _first(gt, "price", "price_min"),
            "price_max": _first(lt, "price", "price_max"),
            "rooms_min": _first(gt, "rooms", "rooms_min"),
            "surface_min": _first(gt, "surface_m2", "surface", "surface_min"),
        }
        for key, value in mapped.items():
            if value is not None and data.get(key) in (None, ""):
                data[key] = value
        if data.get("limit") is not None:
            try:
                data["limit"] = max(1, min(50, int(data["limit"])))
            except (TypeError, ValueError):
                data.pop("limit")
        return data


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
