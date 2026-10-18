"""Wardrobe: domain normalisers, suggestions, statistics, goal/reminder and the service over a fake Hub.

Markers: unit (engines + service), format (MCP tools, plugin manifest)
"""
import base64
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core import domain, photos, stats, suggest  # noqa: E402
from app.core.domain import Invalid  # noqa: E402
from app.core.service import NotFound, Wardrobe  # noqa: E402
from app.core.store import Store, parse_dt  # noqa: E402


class FakeHub:
    """In-memory Archive (/api/wardrobe-store + /api/blobs) and a recorder for Hermes/Oracle calls."""

    def __init__(self):
        self.rows, self.seq, self.blobs, self.sent = {}, 0, {}, []

    def call(self, service, method, path, *, body=None, query=None, timeout=8):
        try:
            return 200, self.ok(service, method, path, body=body, query=query, timeout=timeout)
        except KeyError:
            return 404, {"detail": "not found"}

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        if service != "archive":
            self.sent.append((service, path, body))
            return {"ok": True}
        if path == "api/wardrobe-store/records":
            if method == "PUT":
                applied, stale = [], []
                for r in body["rows"]:
                    key = (r["kind"], r["id"])
                    old = self.rows.get(key)
                    if old and parse_dt(old["updated_at"]) > parse_dt(r["updated_at"]):
                        stale.append(old)
                        continue
                    self.seq += 1
                    self.rows[key] = {**r, "seq": self.seq}
                    applied.append({"kind": r["kind"], "id": r["id"], "seq": self.seq})
                return {"applied": applied, "stale": stale, "cursor": self.seq}
            since = int((query or {}).get("since_seq") or 0)
            return {"rows": sorted((r for r in self.rows.values() if r["seq"] > since), key=lambda r: r["seq"]),
                    "cursor": self.seq}
        if path == "api/blobs" and method == "POST":
            bid = f"b{len(self.blobs) + 1}"
            self.blobs[bid] = body
            return {"blob_id": bid, "size": len(body["data_base64"]), "deduped": False}
        if path.startswith("api/blobs/"):
            bid = path.split("/")[2]
            if method == "DELETE":
                self.blobs.pop(bid)
                return {"deleted": True}
            b = self.blobs[bid]
            return {"blob_id": bid, "mime": b["content_type"], "data_b64": b["data_base64"]}
        raise AssertionError(f"unexpected call {method} {path}")


SETTINGS: dict = {}


@pytest.fixture
def wd():
    SETTINGS.clear()
    hub = FakeHub()
    w = Wardrobe(Store(hub, min_refresh_seconds=0), hub, lambda key, default=None: SETTINGS.get(key, default),
                 tz="Europe/Rome")
    w.ensure_vocabularies()
    return w


def _basics(w):
    tee = w.save_piece({"name": "T-shirt bianca", "category": "tshirt", "colors": ["white"], "favorite": True})
    jeans = w.save_piece({"name": "Jeans blu", "category": "jeans", "colors": ["denim"]})
    sneak = w.save_piece({"name": "Sneakers bianche", "category": "sneakers", "colors": ["white"]})
    coat = w.save_piece({"name": "Cappotto cammello", "category": "coat", "colors": ["camel"], "seasons": ["autumn", "winter"]})
    return tee, jeans, sneak, coat


# ── domain ──────────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_piece_subcategory_given_as_category():
    cats = {c["key"]: c for c in domain.DEFAULT_CATEGORIES}
    p = domain.piece({"name": "Camicia oxford", "category": "shirt"}, cats)
    assert (p["category"], p["subcategory"], p["kind"]) == ("top", "shirt", "garment")
    assert p["formality"] == 3 and p["seasons"] == list(domain.SEASONS)


@pytest.mark.unit
def test_piece_rejects_bad_input():
    cats = {c["key"]: c for c in domain.DEFAULT_CATEGORIES}
    with pytest.raises(Invalid):
        domain.piece({"name": "", "category": "shirt"}, cats)
    with pytest.raises(Invalid):
        domain.piece({"name": "X", "category": "spaceship"}, cats)
    with pytest.raises(Invalid):
        domain.piece({"name": "X", "category": "shirt", "status": "lost_in_space"}, cats)


@pytest.mark.unit
def test_wear_needs_something_and_no_future():
    today = date(2026, 10, 18)
    with pytest.raises(Invalid):
        domain.wear({}, {}, {}, today)
    with pytest.raises(Invalid):
        domain.wear({"piece_ids": ["a"], "date": "2026-10-19"}, {"a": {}}, {}, today)
    w = domain.wear({"outfit_id": "o"}, {"a": {}}, {"o": {"slots": [{"slot": "top", "piece_id": "a"}]}}, today)
    assert w["piece_ids"] == ["a"] and w["date"] == "2026-10-18"


@pytest.mark.unit
def test_photo_decode_limits():
    up = {"name": "x.jpg", "mime": "image/jpeg", "data_b64": base64.b64encode(b"abc").decode()}
    assert photos.decode(up, 1)[0] == b"abc"
    with pytest.raises(photos.PhotoError):
        photos.decode({**up, "mime": "application/pdf"}, 1)
    with pytest.raises(photos.PhotoError):
        photos.decode({**up, "data_b64": base64.b64encode(b"x" * 2048).decode()}, 0.001)


# ── suggestions ─────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_season_and_warmth_band():
    assert suggest.season_of(date(2026, 1, 10)) == "winter"
    assert suggest.season_of(date(2026, 7, 10)) == "summer"
    assert suggest.warmth_band(30, "summer") == (1, 2)
    assert suggest.warmth_band(None, "winter")[0] >= 5


@pytest.mark.unit
def test_suggest_needs_a_coat_when_cold(wd):
    tee, jeans, sneak, coat = _basics(wd)
    out = wd.suggest(day="2026-01-10", temp_c=3, count=1)
    assert out["items"], out
    ids = {p["id"] for p in out["items"][0]["pieces"]}
    assert {tee["id"], jeans["id"], sneak["id"], coat["id"]} <= ids
    assert out["items"][0]["reasons"]


@pytest.mark.unit
def test_suggest_skips_laundry_and_recent(wd):
    tee, jeans, sneak, _ = _basics(wd)
    wd.save_piece({"status": "laundry"}, jeans["id"], partial=True)
    assert not wd.suggest(day="2026-07-10", temp_c=28)["items"]
    assert "hint" in wd.suggest(day="2026-07-10", temp_c=28)


# ── service ─────────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_search_and_filters(wd):
    _basics(wd)
    assert [p["name"] for p in wd.pieces(q="bianc")["items"]] == ["Sneakers bianche", "T-shirt bianca"] or \
        {p["name"] for p in wd.pieces(q="bianc")["items"]} == {"Sneakers bianche", "T-shirt bianca"}
    assert wd.pieces(kind="shoes")["total"] == 1
    assert wd.pieces(season="summer")["total"] == 3


@pytest.mark.unit
def test_outfit_mark_once_per_day_and_undo(wd):
    tee, jeans, sneak, _ = _basics(wd)
    o = wd.save_outfit({"piece_ids": [tee["id"], jeans["id"], sneak["id"]], "favorite": True})
    assert [s["slot"] for s in o["slots"]] == ["top", "bottom", "shoes"]
    first = wd.mark_worn({"outfit_id": o["id"]})
    again = wd.mark_worn({"outfit_id": o["id"]})
    assert again.get("already") and wd.wears()["total"] == 1
    assert first["label"].endswith("indossato")
    assert wd.piece_detail(tee["id"])["wear_count"] == 1
    wd.quick_undo(o["id"])
    assert wd.wears()["total"] == 0
    with pytest.raises(NotFound):
        wd.quick_undo(o["id"])


@pytest.mark.unit
def test_quick_chips_favourites_then_suggestion(wd):
    tee, jeans, sneak, _ = _basics(wd)
    o = wd.save_outfit({"name": "Base", "piece_ids": [tee["id"], jeans["id"], sneak["id"]], "favorite": True})
    chips = wd.quick_chips()
    assert chips[0]["id"] == o["id"] and chips[0]["state"] == "todo"
    wd.quick_mark(o["id"])
    assert wd.quick_chips()[0]["state"] == "done"


@pytest.mark.unit
def test_goal_and_reminder_rules(wd):
    tee, jeans, sneak, _ = _basics(wd)
    assert wd.goal_progress() is None
    assert wd.reminder_decision()["why"] == "disabled"
    SETTINGS.update({"wardrobe.tracking.goal_times": 1, "wardrobe.tracking.goal_per": "day",
                     "wardrobe.reminder.enabled": True})
    assert wd.reminder_decision()["send"] is True
    wd.mark_reminder_sent()
    wd.mark_worn({"piece_ids": [tee["id"], jeans["id"]]})
    g = wd.goal_progress()
    assert g["met"] and g["marked_today"]
    assert wd.reminder_decision()["why"] == "done_today"
    closes = [b for s, p, b in wd.hub.sent if s == "hermes"]
    assert closes and closes[-1]["payload"]["closes"] == "wardrobe.reminder"
    assert "_message" not in closes[-1]["payload"]


@pytest.mark.unit
def test_stats_forgotten_and_gaps(wd):
    tee, jeans, sneak, _ = _basics(wd)
    old = (wd.today() - timedelta(days=400)).isoformat()
    wd.save_piece({"last_worn_manual": old}, jeans["id"], partial=True)
    s = wd.stats()
    assert s["totals"]["garments"] == 3 and s["totals"]["shoes"] == 1
    assert jeans["id"] in [f["id"] for f in s["forgotten"]]
    assert any("pioggia" in g for g in s["gaps"])
    assert s["usage"]["has_marks"] is False


@pytest.mark.unit
def test_cost_per_wear():
    pieces = [{"id": "a", "name": "A", "kind": "garment", "category": "top", "status": "active",
               "purchase": {"price": 40}}]
    out = stats.compute(pieces, [], [{"date": "2026-10-01", "piece_ids": ["a"]}] * 4, {}, {}, date(2026, 10, 18), 180)
    assert out["usage"]["cost_per_wear"][0]["cost_per_wear"] == 10.0


@pytest.mark.unit
def test_photos_go_to_archive_blobs(wd):
    tee, *_ = _basics(wd)
    try:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1200, 900), (200, 30, 30)).save(buf, "JPEG")
        raw = base64.b64encode(buf.getvalue()).decode()
    except ModuleNotFoundError:                       # no Pillow: bytes are stored as they are
        raw = base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()
    r = wd.add_photo("piece", tee["id"], {"name": "t.jpg", "mime": "image/jpeg", "data_b64": raw})
    assert len(wd.hub.blobs) == 3                     # original, medium, thumb
    assert r["item"]["photos"] == [r["photo_id"]]
    assert wd.photo_file(r["photo_id"], "thumb")["data_b64"]
    wd.remove_photo("piece", tee["id"], r["photo_id"])
    assert not wd.hub.blobs


@pytest.mark.unit
def test_packing_and_collection_check(wd):
    _basics(wd)
    c = wd.packing(name="Milano", date_from="2026-11-02", date_to="2026-11-04")
    assert c["piece_ids"] or c.get("items")
    some = (c["piece_ids"] or [i["id"] for i in c["items"]])[0]
    assert some in wd.toggle_check(c["id"], some)["checked"]


@pytest.mark.unit
def test_export_import_roundtrip(wd):
    _basics(wd)
    dump = wd.export()
    hub = FakeHub()
    other = Wardrobe(Store(hub, min_refresh_seconds=0), hub, lambda k, d=None: d)
    other.ensure_vocabularies()
    import json
    assert dump["filename"].endswith(".json")
    other.import_json(dump["text"])
    assert other.pieces()["total"] == 4


@pytest.mark.unit
def test_context_respects_budget(wd):
    _basics(wd)
    ctx = wd.context(budget=80)
    assert ctx["module"] == "wardrobe" and len(ctx["text"]) <= 80


# ── format: MCP tools and plugin manifest ───────────────────────────────────
@pytest.mark.format
def test_mcp_tools_and_manifest():
    from app import main
    tools = main._tools
    names = {t.name for t in tools}
    assert {"guardaroba_riepilogo", "guardaroba_suggerisci", "guardaroba_indossato", "guardaroba_elimina"} <= names
    for t in tools:
        assert t.description and t.parameters["type"] == "object"
        assert t.path.startswith("/api/wardrobe/tools/")
    manifest = main.ui.manifest()
    assert manifest["module"] == "wardrobe"
    webui = manifest["clients"]["webui"]
    assert any(q["id"] == "indossato" for q in webui.get("quick_action") or [])
    assert {"capi", "outfit", "cosa-mi-metto"} <= {p["id"] for p in webui["page"]}
