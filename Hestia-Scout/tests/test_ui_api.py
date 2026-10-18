"""Scout WebUI plugin API (client plugins SPEC §5): listings, flags, stats, manifest."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ui_api
from domain.listing_key import listing_key

pytestmark = pytest.mark.unit

NOW = datetime.now(timezone.utc)
URL1 = "https://www.example.it/annunci/1/"


def _records():
    return [
        {"entity_id": URL1, "domain": "real_estate", "status": "active", "created_at": (NOW - timedelta(days=1)).isoformat(),
         "payload": {"url": URL1, "title": "Trilocale", "price": 320000, "address": "Via Roma 3, 20100 Milano (MI)",
                     "specs": {"surface_m2": 90, "rooms": 3}, "listing_status": "available"}},
        {"entity_id": "https://www.example.it/2", "domain": "real_estate", "status": "active",
         "created_at": (NOW - timedelta(days=20)).isoformat(),
         "payload": {"title": "Bilocale", "price": "180.000 €", "address": "Corso Francia, Torino",
                     "specs": {"surface_m2": 55, "rooms": 2}, "user_flag": "favorite"}},
    ]


class FakeArchive:
    def __init__(self):
        self.recs = _records()
        self.upserts = []

    def get_entity_records(self, **kw):
        assert kw.get("include_embedding") is False
        return self.recs

    def upsert_entity(self, body):
        self.upserts.append(body)
        return True


@pytest.fixture
def client():
    archive = FakeArchive()
    app = FastAPI()
    app.include_router(ui_api.plugin.router())
    app.include_router(ui_api.build_router(ui_api.ListingStore(archive, "real_estate"),
                                           lambda: {"status": "started"}, lambda: {}))
    return TestClient(app), archive


def test_city_from_address_drops_cap_and_province():
    assert ui_api.city_of({"address": "Via Roma 3, 20100 Milano (MI)"}) == "Milano"
    assert ui_api.city_of({"address": "Corso Francia, Torino"}) == "Torino"


def test_listings_filters_and_price_parsing(client):
    c, _ = client
    data = c.get("/api/ui/listings").json()
    assert data["total"] == 2 and data["cities"] == ["Milano", "Torino"]
    assert {i["price"] for i in data["items"]} == {320000, 180000}
    assert c.get("/api/ui/listings", params={"flag": "favorite"}).json()["total"] == 1
    assert c.get("/api/ui/listings", params={"days": 7}).json()["total"] == 1


def test_discard_hides_and_clear_writes_none(client):
    c, archive = client
    key = listing_key(URL1)
    assert c.patch(f"/api/ui/listings/{key}", json={"flag": "discarded"}).json()["flag"] == "discarded"
    assert c.get("/api/ui/listings").json()["total"] == 1
    c.patch(f"/api/ui/listings/{key}", json={"flag": ""})
    assert archive.upserts[-1]["payload"] == {"user_flag": "none"}   # Archive keeps old values on ""
    assert c.patch(f"/api/ui/listings/{key}", json={"status": "bogus"}).status_code == 422


def test_favorite_quick_action_and_undo(client):
    c, _ = client
    key = listing_key(URL1)
    assert [ch["id"] for ch in c.get("/api/ui/quick/new").json()] == [key]
    assert c.post(f"/api/ui/listings/{key}/favorite").json()["flag"] == "favorite"
    assert c.get("/api/ui/quick/new").json() == []
    assert c.delete(f"/api/ui/listings/{key}/favorite").json()["flag"] == ""


def test_stats_and_manifest(client):
    c, _ = client
    s = c.get("/api/ui/stats").json()
    assert s["total"] == 2 and s["new"] == 1 and s["favorites"] == 1 and len(s["weeks"]) == 8
    m = c.get("/api/ui/manifest").json()
    assert {p["id"] for p in m["clients"]["webui"]["page"]} == {"case", "case/:id", "statistiche"}
    assert c.get("/api/ui/listings/doesnotexist").status_code == 404
