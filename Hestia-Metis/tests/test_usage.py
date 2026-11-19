"""Usage log, «Adesso», «Scopri» (dossier docs/work/2026-10-24-whole-cindy-brainstorm W6). Markers: unit, api"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, Store

from app.core.usage import Usage

pytestmark = pytest.mark.unit
TZ = ZoneInfo("Europe/Rome")

CATALOG = {"contributions": {"*": {"tool": [
    {"name": "gym_today", "module": "hercules", "title": "Allenamento di oggi", "description": "La scheda.",
     "clients": ["telegram", "ui"]},
    {"name": "expenses_add", "module": "plutus", "title": "Nuova spesa", "description": "Segna una spesa.",
     "clients": ["telegram", "ui"]},
    {"name": "expenses_delete", "module": "plutus", "title": "Elimina spesa", "clients": ["telegram"]},
    {"name": "weather_today", "module": "hecate", "title": "Meteo", "description": "Che tempo fa.", "clients": []},
    {"name": "webui_only", "module": "hera", "title": "Solo WebUI", "clients": ["ui"]},
    {"name": "diary_write", "module": "hygieia", "title": "Diario", "description": "Scrivi il diario.",
     "clients": ["telegram"]},
]}}}


class FakeAgenda:
    def __init__(self, rows=None):
        self.rows = rows or []

    def agenda(self, days=1):
        return self.rows


class LLMArchive(FakeArchive):
    def __init__(self, answer=None):
        super().__init__()
        self.answer = answer
        self.prompts = []

    def llm(self, prompt, **kw):
        self.prompts.append((prompt, kw))
        return self.answer


def _usage(agenda=None, answer=None):
    hub = LLMArchive(answer)
    return Usage(Store(hub, "metis-store", name="metis"), hub, agenda=agenda, catalog_fn=lambda: CATALOG), hub


def _tap(u, ref, at, client="telegram", kind="tool"):
    u.record([{"client": client, "kind": kind, "ref": ref, "at": at.isoformat()}])


def test_record_validates_and_stores_bucket():
    u, _ = _usage()
    at = datetime(2026, 10, 26, 7, 10, tzinfo=TZ)            # Monday
    assert u.record([{"client": "telegram", "kind": "tool", "ref": "gym_today", "at": at.isoformat()},
                     {"client": "fax", "ref": "x"}]) == {"recorded": 1}
    tap = u.taps(3650)[0]
    assert (tap["weekday"], tap["hour"], tap["client"]) == (0, 7, "telegram")
    with pytest.raises(Invalid):
        u.record([{"client": "fax", "ref": "x"}])


def test_adesso_habit_at_this_hour_and_day_beats_others():
    u, _ = _usage()
    now = datetime.now(TZ).replace(minute=5, second=0, microsecond=0)
    for weeks in (1, 2, 3):
        _tap(u, "gym_today", now - timedelta(days=7 * weeks))
    _tap(u, "expenses_add", now - timedelta(days=2, hours=6))
    out = u.right_now("telegram", now=now)
    assert out["items"][0]["tool"] == "gym_today"
    assert out["items"][0]["source"] == "habit" and "Di solito" in out["items"][0]["reason"]


def test_adesso_drops_tools_the_client_cannot_run_and_deletes():
    u, _ = _usage()
    now = datetime.now(TZ)
    for ref in ("webui_only", "expenses_delete", "sparita"):
        _tap(u, ref, now - timedelta(hours=1))
    names = [i["tool"] for i in u.right_now("telegram", now=now)["items"]]
    assert "webui_only" not in names and "expenses_delete" not in names and "sparita" not in names


def test_adesso_agenda_item_with_tool_comes_first():
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    u, _ = _usage(FakeAgenda([{"title": "Palestra", "start_at": start, "params": {"tool": "gym_today"}},
                              {"title": "Lontano", "start_at": (datetime.now(timezone.utc) + timedelta(hours=9))
                               .isoformat(), "params": {"tool": "weather_today"}}]))
    items = u.right_now("telegram")["items"]
    assert items[0]["tool"] == "gym_today" and items[0]["source"] == "agenda"
    assert "weather_today" not in [i["tool"] for i in items]


def test_ideas_are_validated_stored_and_shown():
    u, hub = _usage(answer='Ecco: [{"tool":"diary_write","reason":"Fine giornata"},'
                           '{"tool":"inventato","reason":"x"},{"tool":"expenses_delete","reason":"no"}]')
    assert u.refresh_ideas("telegram") == {"ideas": 1}
    assert hub.prompts[0][1]["use_case"] == "metis.now"
    items = u.right_now("telegram")["items"]
    assert [(i["tool"], i["source"], i["reason"]) for i in items] == [("diary_write", "idea", "Fine giornata")]


def test_ideas_fail_soft_when_the_model_is_away():
    u, _ = _usage(answer=None)
    assert u.refresh_ideas("telegram") == {"ideas": 0}
    assert u.right_now("telegram")["items"] == []


def test_scopri_lists_unused_one_per_module_first():
    u, _ = _usage()
    now = datetime.now(TZ)
    for _ in range(3):
        _tap(u, "gym_today", now)
    out = u.discover("telegram")
    names = [i["tool"] for i in out["items"]]
    assert "gym_today" not in names and "expenses_delete" not in names and "webui_only" not in names
    assert set(names) == {"expenses_add", "weather_today", "diary_write"}
    assert all(i["reason"] == "Non l'hai mai usata" for i in out["items"])
    # people read areas, never module names (dossier 2026-10-29-frontend-review-and-tests §6.1)
    by_tool = {i["tool"]: i for i in out["items"]}
    assert by_tool["expenses_add"]["area_label"] == "Expenses"
    assert by_tool["diary_write"]["area_label"] == "Self care"
    assert by_tool["weather_today"]["description"] == "Che tempo fa."


def test_prune_drops_old_taps():
    u, _ = _usage()
    _tap(u, "gym_today", datetime.now(TZ) - timedelta(days=400))
    _tap(u, "gym_today", datetime.now(TZ))
    assert u.prune() == 1
    assert len(u.taps(3650)) == 1


def test_catalog_failure_keeps_last_catalog():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("hub down")
        return CATALOG
    hub = FakeArchive()
    u = Usage(Store(hub, "metis-store"), hub, catalog_fn=flaky, catalog_ttl=0)
    assert len(u.catalog()) == 6
    assert len(u.catalog()) == 6


@pytest.mark.api
def test_endpoints_and_tool_cards():
    from fastapi.testclient import TestClient
    import app.main as main
    hub = LLMArchive()
    fake = Usage(Store(hub, "metis-store", name="metis"), hub, catalog_fn=lambda: CATALOG)
    with patch.object(main, "usage", fake), patch("app.main.hub", MagicMock()):
        c = TestClient(main.app)
        assert c.post("/api/metis/usage", json={"client": "telegram", "kind": "tool",
                                                "ref": "gym_today"}).json() == {"recorded": 1}
        assert c.post("/api/metis/usage", json={"taps": [{"client": "fax", "ref": "x"}]}).status_code == 422
        assert c.get("/api/metis/now", params={"client": "telegram"}).json()["items"][0]["tool"] == "gym_today"
        card = c.get("/api/metis/tools/now", params={"client": "telegram"}).json()
        assert card["display"]["title"] == "Adesso" and card["display"]["actions"][0]["tool"] == "gym_today"
        found = c.get("/api/metis/tools/discover").json()
        assert found["display"]["title"] == "Scopri" and found["items"]
        assert c.get("/api/metis/usage/stats").json()["taps"] == 1
        assert "pruned" in c.post("/api/metis/now/refresh", json={}).json()
    rules = main._agenda_rules()
    assert [r["key"] for r in rules if r["type"] == "job"] == ["metis.now.0700", "metis.now.1230",
                                                                "metis.now.1800", "metis.dataset.review"]
    assert [u["id"] for u in main._HUB_REGISTRATION_PAYLOAD["capabilities"]["llm_usecases"]] == [
        "metis.now", "metis.dataset.review"]


def test_recent_lists_last_taps_newest_first_within_hours():
    """Oracle's awareness lines read the owner's last taps (docs/work/2026-11-06-living-hestia F3)."""
    u, _ = _usage()
    now = datetime.now(timezone.utc)
    u.record([{"client": "telegram", "kind": "tool", "ref": "gym_today", "at": (now - timedelta(hours=30)).isoformat()},
              {"client": "webui", "kind": "page", "ref": "expenses", "label": "Spese", "at": (now - timedelta(hours=2)).isoformat()},
              {"client": "telegram", "kind": "tool", "ref": "weather_today", "at": (now - timedelta(minutes=5)).isoformat()}])
    items = u.recent(limit=5, hours=12)["items"]
    assert [i["ref"] for i in items] == ["weather_today", "expenses"]
    assert items[1]["label"] == "Spese" and items[0]["client"] == "telegram"
    assert len(u.recent(limit=1)["items"]) == 1
