"""Scout's WebUI plugin: the data API under ``/api/ui/`` and the plugin manifest.

Contract: ``docs/work/2026-10-17-client-plugins/SPEC.md`` §4–5. The browser bundle (``Hestia-Scout/ui``) calls
only these endpoints, through the WebUI proxy and Hub. Listings live in Archive (domain ``real_estate``); this
module reads them (short cache) and writes only two fields of a listing payload: ``user_flag`` (favorite /
discarded, the user's own choice) and ``listing_status`` (when the user corrects it).

A listing is addressed by a short stable key (``listing_key``: 12 hex of the URL's sha1) because entity ids are
URLs, which do not travel well inside a path.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.archive_client import ArchiveClient
from domain.listing_key import listing_key
from domain.listing_status import ListingStatus

try:
    from hestia_common.plugin_client import PluginClient, page, quick_action, widget
except ModuleNotFoundError:  # local run outside Docker
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))
    from hestia_common.plugin_client import PluginClient, page, quick_action, widget

logger = logging.getLogger("hestia_scout.ui")

USER_FLAGS = ("favorite", "discarded")
STATUS_LABELS = {
    "available": "Disponibile", "in_negotiation": "In trattativa", "investment_occupied": "Occupato (investimento)",
    "sold": "Venduto", "unknown": "Da verificare",
}
CACHE_SECONDS = 30
NEW_DAYS = 7


# ── plugin manifest ────────────────────────────────────────────────────────
def _dist_dir() -> Path:
    here = Path(__file__).resolve().parent
    env = os.getenv("SCOUT_UI_DIST", "")                                     # Docker: /ui/dist (baked in the image)
    for candidate in ((Path(env),) if env else ()) + (here / "ui" / "dist", here.parent / "ui" / "dist"):   # repo: Hestia-Scout/ui/dist
        if candidate.is_dir():
            return candidate
    return here / "ui" / "dist"


plugin = PluginClient("scout", title="Scout", icon="home", color="amber",
                      description="Case trovate dalle email degli annunci: elenco, preferite, statistiche.",
                      dist=_dist_dir(), version=os.getenv("SCOUT_SERVICE_VERSION", "1.0.0"))
plugin.webui(
    entry="scout.js", api_prefix="/api/ui/",
    pages=[
        page("case", "Case", element="scout-listings", icon="home", order=20,
             help="Tutte le case trovate: filtri, preferite, scartate."),
        page("case/:id", "Annuncio", element="scout-listing", parent="case", detail=True),
        page("statistiche", "Statistiche case", element="scout-stats", icon="chart", order=21, parent="case",
             help="Prezzi per città, nuove case per settimana, stato degli annunci."),
    ],
    widgets=[
        widget("numeri", "Case in numeri", element="scout-kpi-widget", sizes=["m", "xl"], size="m", auto=True,
               open_page="case", icon="home"),
        widget("nuove", "Nuove case", element="scout-new-widget", sizes=["m", "l", "xl"], size="l", auto=True,
               open_page="case", icon="home",
               params={"city": {"type": "string", "label": "Città (vuoto = tutte)"},
                       "days": {"type": "int", "label": "Ultimi giorni", "default": NEW_DAYS}}),
        widget("preferite", "Case preferite", element="scout-favorites-widget", sizes=["m", "l"], size="l",
               open_page="case", icon="star"),
        widget("prezzi", "Prezzi per città", element="scout-prices-widget", sizes=["l", "xl"], size="l",
               open_page="statistiche", icon="chart"),
    ],
    quick_actions=[
        quick_action("controlla", "Controlla email annunci", "POST", "/api/ui/cycle", icon="refresh",
                     group="Case", order=21),
        quick_action("preferita", "Preferita", "POST", "/api/ui/listings/{id}/favorite", icon="star",
                     group="Nuove case", source="/api/ui/quick/new", order=20,
                     undo={"method": "DELETE", "path": "/api/ui/listings/{id}/favorite"}),
    ],
)


# ── listings cache ─────────────────────────────────────────────────────────
def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.]", "", str(value))
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") >= 1 and len(text.split(".")[-1]) == 3:
        text = text.replace(".", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_CAP_RE = re.compile(r"\b\d{5}\b")


def city_of(payload: dict) -> str:
    """Best-effort city: the last address part that is not a CAP/province, else the geocoding query."""
    address = str(payload.get("address") or "")
    parts = [p.strip() for p in address.split(",") if p.strip()]
    for part in reversed(parts):
        cleaned = re.sub(r"\(\s*\w{2}\s*\)", "", _CAP_RE.sub("", part)).strip(" -()")
        if cleaned and not cleaned.isdigit() and len(cleaned) > 2 and not re.match(r"^(via|viale|piazza|corso|vicolo|largo)\b", cleaned, re.I):
            return cleaned.title()
    loc = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    query = str(loc.get("query") or "").split(",")[-1].strip()
    return query.title() if query else ""


def to_view(record: dict) -> dict:
    """One Archive record → the listing shape the plugin draws."""
    p = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    specs = p.get("specs") if isinstance(p.get("specs"), dict) else {}
    pricing = p.get("pricing") if isinstance(p.get("pricing"), dict) else {}
    media = p.get("media") if isinstance(p.get("media"), dict) else {}
    images = [i for i in (media.get("images") or []) if isinstance(i, str) and i.startswith("http")]
    image = p.get("image") if str(p.get("image") or "").startswith("http") else (images[0] if images else "")
    price = _num(p.get("price"))
    surface = _num(specs.get("surface_m2"))
    ppm2 = _num(pricing.get("price_per_m2")) or (round(price / surface) if price and surface else None)
    status = str(p.get("listing_status") or "unknown").strip().lower()
    status = status if status in STATUS_LABELS else "unknown"
    flag = str(p.get("user_flag") or "").strip().lower()
    entity_id = str(record.get("entity_id") or p.get("url") or "")
    return {
        "id": listing_key(entity_id),
        "url": str(p.get("url") or entity_id),
        "title": p.get("title") or p.get("address") or "Annuncio",
        "address": p.get("address") or "",
        "city": city_of(p),
        "price": int(price) if price else None,
        "price_per_m2": int(ppm2) if ppm2 else None,
        "surface_m2": surface,
        "rooms": specs.get("rooms"),
        "bedrooms": specs.get("bedrooms"),
        "bathrooms": specs.get("bathrooms"),
        "floor": specs.get("floor"),
        "elevator": bool(specs.get("elevator")),
        "balcony": bool(specs.get("balcony_or_terrace")),
        "parking": bool(specs.get("garage_or_parking")),
        "image": image,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "flag": flag if flag in USER_FLAGS else "",
        "source": p.get("source_site") or "",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "_entity_id": entity_id,
    }


def detail_view(record: dict) -> dict:
    view = to_view(record)
    p = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    media = p.get("media") if isinstance(p.get("media"), dict) else {}
    loc = p.get("location") if isinstance(p.get("location"), dict) else {}
    energy = p.get("energy") if isinstance(p.get("energy"), dict) else {}
    pricing = p.get("pricing") if isinstance(p.get("pricing"), dict) else {}
    contact = p.get("contact") if isinstance(p.get("contact"), dict) else {}
    view.update({
        "summary": p.get("summary") or "",
        "images": [i for i in (media.get("images") or []) if isinstance(i, str) and i.startswith("http")][:24],
        "lat": loc.get("lat"), "lon": loc.get("lon"),
        "features": [str(f) for f in (p.get("additional_features") or [])][:40],
        "characteristics": {str(k): str(v) for k, v in (p.get("characteristics") or {}).items()} if isinstance(p.get("characteristics"), dict) else {},
        "heating": (p.get("specs") or {}).get("heating") if isinstance(p.get("specs"), dict) else None,
        "year_built": energy.get("year_built"), "property_state": energy.get("property_state"),
        "condo_fees": pricing.get("condo_fees_monthly_eur") or pricing.get("condo_fees"),
        "agency": contact.get("agency_name") or "",
    })
    return view


class ListingStore:
    """Short cache of the domain's active records (Archive is the owner; Scout only reads + patches two fields)."""

    def __init__(self, archive: ArchiveClient, domain: str):
        self.archive = archive
        self.domain = domain
        self._lock = threading.Lock()
        self._at = 0.0
        self._records: list[dict] = []

    def records(self, fresh: bool = False) -> list[dict]:
        with self._lock:
            if fresh or time.time() - self._at > CACHE_SECONDS or not self._records:
                rows = self.archive.get_entity_records(domain=self.domain, status="active", limit=2000,
                                                       include_embedding=False)
                if rows or not self._records:
                    self._records = [r for r in rows if isinstance(r, dict)]
                    self._at = time.time()
                else:
                    logger.warning("[🔄] event=scout_ui_records_empty keeping_cached=%d", len(self._records))
            return self._records

    def views(self, fresh: bool = False) -> list[dict]:
        return [to_view(r) for r in self.records(fresh)]

    def find(self, key: str) -> dict | None:
        for fresh in (False, True):
            for r in self.records(fresh):
                if listing_key(str(r.get("entity_id") or "")) == key:
                    return r
        return None

    def patch(self, key: str, fields: dict) -> dict:
        record = self.find(key)
        if not record:
            raise HTTPException(status_code=404, detail="annuncio non trovato")
        ok = self.archive.upsert_entity({"entity_id": record["entity_id"], "domain": record.get("domain") or self.domain,
                                         "status": record.get("status") or "active", "payload": fields})
        if not ok:
            raise HTTPException(status_code=502, detail="archivio non raggiungibile")
        with self._lock:   # local copy updated at once, so the next read shows the change
            record["payload"] = {**(record.get("payload") or {}), **fields}
        logger.info("event=scout_listing_patched key=%s fields=%s", key, ",".join(fields))
        return to_view(record)


def _public(view: dict) -> dict:
    return {k: v for k, v in view.items() if not k.startswith("_")}


SORTS: dict[str, tuple[Callable[[dict], Any], bool]] = {
    "new": (lambda v: str(v.get("created_at") or ""), True),
    "price_asc": (lambda v: v.get("price") or 10**12, False),
    "price_desc": (lambda v: v.get("price") or 0, True),
    "ppm2": (lambda v: v.get("price_per_m2") or 10**9, False),
    "surface": (lambda v: v.get("surface_m2") or 0, True),
}


def filter_views(views: list[dict], *, q: str = "", city: str = "", status: str = "", flag: str = "",
                 price_min: float | None = None, price_max: float | None = None, rooms_min: float | None = None,
                 surface_min: float | None = None, days: int | None = None) -> list[dict]:
    q = q.strip().lower()
    city = city.strip().lower()
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    out = []
    for v in views:
        if flag == "favorite" and v["flag"] != "favorite":
            continue
        if flag == "discarded" and v["flag"] != "discarded":
            continue
        if flag in ("", "active") and v["flag"] == "discarded":
            continue
        if q and q not in f"{v['title']} {v['address']} {v['city']}".lower():
            continue
        if city and v["city"].lower() != city:
            continue
        if status and v["status"] != status:
            continue
        if price_min is not None and (v["price"] or 0) < price_min:
            continue
        if price_max is not None and (not v["price"] or v["price"] > price_max):
            continue
        if rooms_min is not None and (_num(v["rooms"]) or 0) < rooms_min:
            continue
        if surface_min is not None and (v["surface_m2"] or 0) < surface_min:
            continue
        if since and ((_ts(v["created_at"]) or since) < since):
            continue
        out.append(v)
    return out


def compute_stats(views: list[dict], city: str = "") -> dict:
    active = [v for v in views if v["flag"] != "discarded"]
    if city:
        active = [v for v in active if v["city"].lower() == city.strip().lower()]
    now = datetime.now(timezone.utc)
    new = [v for v in active if (_ts(v["created_at"]) or now - timedelta(days=999)) >= now - timedelta(days=NEW_DAYS)]
    prices = [v["price"] for v in active if v["price"]]
    ppm2 = [v["price_per_m2"] for v in active if v["price_per_m2"]]
    weeks: list[dict] = []
    for i in range(7, -1, -1):
        start = (now - timedelta(days=now.weekday(), weeks=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        weeks.append({"week": start.date().isoformat(), "label": f"{start.day}/{start.month}",
                      "count": sum(1 for v in active if (t := _ts(v["created_at"])) and start <= t < end)})
    by_city: dict[str, list[dict]] = defaultdict(list)
    for v in active:
        if v["city"]:
            by_city[v["city"]].append(v)
    cities = sorted(by_city.items(), key=lambda kv: -len(kv[1]))
    price_by_city = []
    for name, items in cities[:10]:
        ps = [i["price"] for i in items if i["price"]]
        pm = [i["price_per_m2"] for i in items if i["price_per_m2"]]
        price_by_city.append({"city": name, "count": len(items),
                              "avg_price": round(sum(ps) / len(ps)) if ps else None,
                              "avg_ppm2": round(sum(pm) / len(pm)) if pm else None})
    return {
        "total": len(active),
        "new": len(new),
        "favorites": sum(1 for v in active if v["flag"] == "favorite"),
        "discarded": sum(1 for v in views if v["flag"] == "discarded"),
        "available": sum(1 for v in active if v["status"] == "available"),
        "avg_price": round(sum(prices) / len(prices)) if prices else None,
        "avg_ppm2": round(sum(ppm2) / len(ppm2)) if ppm2 else None,
        "by_status": [{"status": s, "label": STATUS_LABELS[s], "count": c}
                      for s, c in Counter(v["status"] for v in active).most_common()],
        "weeks": weeks,
        "price_by_city": price_by_city,
        "cities": [name for name, _ in cities],
    }


class ListingPatch(BaseModel):
    flag: str | None = None          # favorite | discarded | "" (clear)
    status: str | None = None        # ListingStatus value


def build_router(store: ListingStore, run_cycle: Callable[[], dict], cycle_status: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/api/ui", tags=["scout-ui"])

    @router.get("/listings")
    def listings(q: str = "", city: str = "", status: str = "", flag: str = "",
                 price_min: float | None = None, price_max: float | None = None,
                 rooms_min: float | None = None, surface_min: float | None = None, days: int | None = None,
                 sort: str = "new", offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=200)):
        views = store.views()
        items = filter_views(views, q=q, city=city, status=status, flag=flag, price_min=price_min,
                             price_max=price_max, rooms_min=rooms_min, surface_min=surface_min, days=days)
        key, reverse = SORTS.get(sort, SORTS["new"])
        items.sort(key=key, reverse=reverse)
        cities = sorted({v["city"] for v in views if v["city"]})
        return {"total": len(items), "offset": offset, "items": [_public(v) for v in items[offset:offset + limit]],
                "cities": cities, "statuses": [{"value": k, "label": l} for k, l in STATUS_LABELS.items()]}

    @router.get("/listings/{key}")
    def listing(key: str):
        record = store.find(key)
        if not record:
            raise HTTPException(status_code=404, detail="annuncio non trovato")
        return _public(detail_view(record))

    @router.patch("/listings/{key}")
    def patch_listing(key: str, body: ListingPatch):
        fields: dict[str, Any] = {}
        if body.flag is not None:
            if body.flag not in (*USER_FLAGS, ""):
                raise HTTPException(status_code=422, detail="flag: favorite | discarded | ''")
            fields["user_flag"] = body.flag or "none"   # Archive keeps old values on "", so clear = "none"
        if body.status is not None:
            try:
                fields["listing_status"] = ListingStatus(body.status).value
            except ValueError:
                raise HTTPException(status_code=422, detail="status non valido")
        if not fields:
            raise HTTPException(status_code=422, detail="niente da cambiare")
        return _public(store.patch(key, fields))

    @router.post("/listings/{key}/favorite")
    def favorite(key: str):
        return _public(store.patch(key, {"user_flag": "favorite"}))

    @router.delete("/listings/{key}/favorite")
    def unfavorite(key: str):
        return _public(store.patch(key, {"user_flag": "none"}))

    @router.get("/stats")
    def stats(city: str = ""):
        return compute_stats(store.views(), city)

    @router.get("/quick/new")
    def quick_new(limit: int = Query(3, ge=1, le=10)):
        """Chips for the Home strip: newest listings not yet marked (tap = Preferita)."""
        items = [v for v in filter_views(store.views(), days=NEW_DAYS) if not v["flag"]]
        items.sort(key=SORTS["new"][0], reverse=True)
        chips = []
        for v in items[:limit]:
            hint = " · ".join(x for x in (v["city"], f"€ {v['price']:,}".replace(",", ".") if v["price"] else "",
                                          f"{v['surface_m2']:g} m²" if v["surface_m2"] else "") if x)
            chips.append({"id": v["id"], "label": str(v["title"])[:48], "icon": "home", "state": "todo", "hint": hint})
        return chips

    @router.post("/cycle")
    def cycle():
        return run_cycle()

    @router.get("/cycle")
    def cycle_state():
        return cycle_status()

    return router
