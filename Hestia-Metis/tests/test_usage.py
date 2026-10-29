"""Usage log, «Adesso», «Scopri» (dossier docs/work/2026-10-24-tutto-brainstorm-cindy W6). Markers: unit, api"""
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
    {"name": "palestra_oggi", "module": "hercules", "title": "Allenamento di oggi", "description": "La scheda.",
     "clients": ["telegram", "ui"]},
    {"name": "spese_aggiungi", "module": "plutus", "title": "Nuova spesa", "description": "Segna una spesa.",
     "clients": ["telegram", "ui"]},
    {"name": "spese_elimina", "module": "plutus", "title": "Elimina spesa", "clients": ["telegram"]},
    {"name": "meteo_oggi", "module": "hecate", "title": "Meteo", "description": "Che tempo fa.", "clients": []},
    {"name": "solo_webui", "module": "hera", "title": "Solo WebUI", "clients": ["ui"]},
    {"name": "diario_scrivi", "module": "hygieia", "title": "Diario", "description": "Scrivi il diario.",
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
    assert u.record([{"client": "telegram", "kind": "tool", "ref": "palestra_oggi", "at": at.isoformat()},
                     {"client": "fax", "ref": "x"}]) == {"recorded": 1}
    tap = u.taps(3650)[0]
    assert (tap["weekday"], tap["hour"], tap["client"]) == (0, 7, "telegram")
    with pytest.raises(Invalid):
        u.record([{"client": "fax", "ref": "x"}])


def test_adesso_habit_at_this_hour_and_day_beats_others():
    u, _ = _usage()
    now = datetime.now(TZ).replace(minute=5, second=0, microsecond=0)
    for weeks in (1, 2, 3):
        _tap(u, "palestra_oggi", now - timedelta(days=7 * weeks))
    _tap(u, "spese_aggiungi", now - timedelta(days=2, hours=6))
    out = u.adesso("telegram", now=now)
    assert out["items"][0]["tool"] == "palestra_oggi"
    assert out["items"][0]["source"] == "habit" and "Di solito" in out["items"][0]["reason"]


def test_adesso_drops_tools_the_client_cannot_run_and_deletes():
    u, _ = _usage()
    now = datetime.now(TZ)
    for ref in ("solo_webui", "spese_elimina", "sparita"):
        _tap(u, ref, now - timedelta(hours=1))
    names = [i["tool"] for i in u.adesso("telegram", now=now)["items"]]
    assert "solo_webui" not in names and "spese_elimina" not in names and "sparita" not in names


def test_adesso_agenda_item_with_tool_comes_first():
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    u, _ = _usage(FakeAgenda([{"title": "Palestra", "start_at": start, "params": {"tool": "palestra_oggi"}},
                              {"title": "Lontano", "start_at": (datetime.now(timezone.utc) + timedelta(hours=9))
                               .isoformat(), "params": {"tool": "meteo_oggi"}}]))
    items = u.adesso("telegram")["items"]
    assert items[0]["tool"] == "palestra_oggi" and items[0]["source"] == "agenda"
    assert "meteo_oggi" not in [i["tool"] for i in items]


def test_ideas_are_validated_stored_and_shown():
    u, hub = _usage(answer='Ecco: [{"tool":"diario_scrivi","reason":"Fine giornata"},'
                           '{"tool":"inventato","reason":"x"},{"tool":"spese_elimina","reason":"no"}]')
    assert u.refresh_ideas("telegram") == {"ideas": 1}
    assert hub.prompts[0][1]["use_case"] == "metis.adesso"
    items = u.adesso("telegram")["items"]
    assert [(i["tool"], i["source"], i["reason"]) for i in items] == [("diario_scrivi", "idea", "Fine giornata")]


def test_ideas_fail_soft_when_the_model_is_away():
    u, _ = _usage(answer=None)
    assert u.refresh_ideas("telegram") == {"ideas": 0}
    assert u.adesso("telegram")["items"] == []


def test_scopri_lists_unused_one_per_module_first():
    u, _ = _usage()
    now = datetime.now(TZ)
    for _ in range(3):
        _tap(u, "palestra_oggi", now)
    out = u.scopri("telegram")
    names = [i["tool"] for i in out["items"]]
    assert "palestra_oggi" not in names and "spese_elimina" not in names and "solo_webui" not in names
    assert set(names) == {"spese_aggiungi", "meteo_oggi", "diario_scrivi"}
    assert all(i["reason"] == "Non l'hai mai usata" for i in out["items"])
    # people read areas, never module names (dossier 2026-10-29-revisione-e-test-frontend §6.1)
    by_tool = {i["tool"]: i for i in out["items"]}
    assert by_tool["spese_aggiungi"]["area_label"] == "Spese"
    assert by_tool["diario_scrivi"]["area_label"] == "Cura di sé"
    assert by_tool["meteo_oggi"]["description"] == "Che tempo fa."


def test_prune_drops_old_taps():
    u, _ = _usage()
    _tap(u, "palestra_oggi", datetime.now(TZ) - timedelta(days=400))
    _tap(u, "palestra_oggi", datetime.now(TZ))
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
                                                "ref": "palestra_oggi"}).json() == {"recorded": 1}
        assert c.post("/api/metis/usage", json={"taps": [{"client": "fax", "ref": "x"}]}).status_code == 422
        assert c.get("/api/metis/adesso", params={"client": "telegram"}).json()["items"][0]["tool"] == "palestra_oggi"
        card = c.get("/api/metis/tools/adesso", params={"client": "telegram"}).json()
        assert card["display"]["title"] == "Adesso" and card["display"]["actions"][0]["tool"] == "palestra_oggi"
        scopri = c.get("/api/metis/tools/scopri").json()
        assert scopri["display"]["title"] == "Scopri" and scopri["items"]
        assert c.get("/api/metis/usage/stats").json()["taps"] == 1
        assert "pruned" in c.post("/api/metis/adesso/refresh", json={}).json()
    rules = main._agenda_rules()
    assert [r["key"] for r in rules if r["type"] == "job"] == ["metis.adesso.0700", "metis.adesso.1230",
                                                                "metis.adesso.1800"]
    assert [u["id"] for u in main._HUB_REGISTRATION_PAYLOAD["capabilities"]["llm_usecases"]] == ["metis.adesso"]
