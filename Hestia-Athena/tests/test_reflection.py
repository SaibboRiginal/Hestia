"""Life reflection («Vita»): links between weekly series, topics, dedup, observations only for the recap.
SPEC docs/work/2026-10-20-riflessione-a-livelli."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from core import athena_settings as S
from core.athena_settings import settings
from core.reflection import LifeReflection, choose_topics, correlate, link_text, local_day, pearson
from hestia_common.signals_client import Signals, iso_week, last_weeks, metric, signal


def _set(monkeypatch, key, value):
    monkeypatch.setitem(settings._effective, key, value)


def _series(n=9):
    """Workouts and routine adherence move together; spending is noise. Closed weeks only (current left out)."""
    weeks = last_weeks(n + 1)[:-1]
    sessions = [1, 3, 2, 4, 1, 3, 4, 2, 3][:n]
    return weeks, {
        "fitness.sessions": {"label": "Allenamenti", "module": "hercules", "domain": "fitness",
                             "values": dict(zip(weeks, sessions))},
        "selfcare.adherence": {"label": "Routine rispettate %", "module": "hygieia", "domain": "selfcare",
                               "values": dict(zip(weeks, [s * 20 + 10 for s in sessions]))},
        "fitness.volume": {"label": "Volume", "module": "hercules", "domain": "fitness",
                           "values": dict(zip(weeks, [s * 1000 for s in sessions]))},
        "finance.spent": {"label": "Spesa", "module": "plutus", "domain": "finance",
                          "values": dict(zip(weeks, [50, 52, 49, 51, 50, 48, 52, 50, 51][:n]))},
    }


@pytest.mark.unit
class TestCorrelate:
    def test_pearson(self):
        assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
        assert pearson([1, 1, 1], [2, 3, 4]) is None

    def test_links_only_across_domains_and_with_enough_weeks(self):
        _, series = _series()
        links = correlate(series, min_weeks=6, min_r=0.6)
        pairs = {(l["a"], l["b"]) for l in links} | {(l["b"], l["a"]) for l in links}
        assert ("fitness.sessions", "selfcare.adherence") in pairs
        assert ("fitness.sessions", "fitness.volume") not in pairs     # same domain
        best = next(l for l in links if {l["a"], l["b"]} == {"fitness.sessions", "selfcare.adherence"})
        assert best["r"] == pytest.approx(1.0) and best["weeks"] >= 6 and best["key"].startswith("link:")
        assert "settimane" in link_text(best)
        assert correlate(series, min_weeks=20, min_r=0.6) == []

    def test_current_week_is_left_out(self):
        _, series = _series()
        cur = iso_week()
        series["fitness.sessions"]["values"][cur] = 99
        series["selfcare.adherence"]["values"][cur] = -99
        assert any({l["a"], l["b"]} == {"fitness.sessions", "selfcare.adherence"}
                   for l in correlate(series, min_weeks=6, min_r=0.6, current_week=cur))


@pytest.mark.unit
class TestTopics:
    def test_order_and_dedup(self):
        sig = [{"module": "plutus", "key": "budget", "severity": "alta", "text": "x"},
               {"module": "hercules", "key": "stall:panca", "severity": "attenzione", "text": "y"},
               {"module": "hercules", "key": "pr:panca", "severity": "info", "text": "z"}]
        links = [{"key": "link:a|b|0", "r": 0.8}]
        t = choose_topics(sig, links, set(), 5)
        assert [x["key"] for x in t] == ["signal:plutus:budget", "link:a|b|0", "signal:hercules:stall:panca"]
        assert [x["key"] for x in choose_topics(sig, links, {"link:a|b|0"}, 5)] == \
            ["signal:plutus:budget", "signal:hercules:stall:panca"]
        assert len(choose_topics(sig, links, set(), 1)) == 1


class _Reader:
    def __init__(self, signals, series, observations=()):
        self._signals, self._series, self._obs = signals, series, list(observations)

    def signals(self, domain=None):
        return list(self._signals)

    def series(self, weeks=26):
        return self._series

    def rows(self, kind, ref_id=None, at_from=None, limit=500):
        return [{"id": f"athena:{o['id']}", "at": "2026-10-20T18:00:00Z", "data": o} for o in self._obs]


ORACLE_OK = ("AZIONE: Allenamento e routine\nTIPO: observation\nPRIORITA: elevated\nDOMINIO: fitness\nTEMA: T2\n"
             "MOTIVO: r=+1.00 su 8 settimane\nRIASSUNTO: Nelle settimane in cui ti alleni di più rispetti anche le "
             "routine.\n")


@pytest.fixture
def life(monkeypatch):
    from core.runtime import AthenaRuntime
    _set(monkeypatch, S.LOOP_ENABLED, False)
    _set(monkeypatch, S.THINKING_ARCHIVE_ENABLED, False)
    _set(monkeypatch, S.REFLECTION_MIN_WEEKS, 6)
    _set(monkeypatch, S.REFLECTION_MIN_CORRELATION, 0.6)
    _set(monkeypatch, S.REFLECTION_MAX_PER_DAY, 2)
    _set(monkeypatch, S.GATE_THRESHOLD, 0.3)
    rt = AthenaRuntime()
    _, series = _series()
    rt.reflection.reader = _Reader([{"module": "plutus", "domain": "finance", "key": "budget", "severity": "alta",
                                     "text": "Budget del mese già al 95%", "page": "budget"}], series)
    monkeypatch.setattr(rt.reflection, "detail", lambda module, topic="": f"dettaglio {module} {topic}".strip())
    monkeypatch.setattr(rt.observer, "observe_settings", lambda limit=40: [])
    stored = []
    monkeypatch.setattr(rt.reflection, "_store", lambda obs: stored.extend(obs) or True)
    rt._stored = stored
    return rt


@pytest.mark.unit
class TestLifeCycle:
    def test_observation_is_stored_not_sent(self, life):
        sent = []
        life._emit_event = lambda **k: sent.append(k)
        with patch.object(life.reflection, "_ask_oracle", return_value=ORACLE_OK) as ask:
            rec = life._life_cycle("manual", "t1")
        prompt = ask.call_args[0][0]
        assert "COLLEGAMENTO" in prompt and "Budget del mese" in prompt and "dettaglio" in prompt
        assert "Servizi" not in prompt                         # no system data in the life track
        assert rec["track"] == "vita" and rec["emitted_count"] == 1 and not sent
        obs = life._stored[0]
        assert obs["day"] == local_day() and obs["topic_key"].startswith("link:") and obs["link"]["weeks"] >= 6
        assert set(obs["domains"]) == {"fitness", "selfcare"}
        assert rec["candidates"][0]["outcome"] == "observed" and rec["life"]["links"]
        assert life.thinking_summary(track="vita")["cycles"][0]["track"] == "vita"
        assert life.thinking_summary(track="sistema")["count"] == 0

    def test_already_told_topic_is_skipped(self, life):
        told = [{"id": "o1", "day": "2026-10-01", "topic_key": k} for k in
                ["signal:plutus:budget"] + [l["key"] for l in correlate(_series()[1], min_weeks=6, min_r=0.6)]]
        life.reflection.reader._obs = told
        with patch.object(life.reflection, "_ask_oracle") as ask:
            rec = life._life_cycle("manual", "t2")
        assert not ask.called and rec["candidates"] == [] and life._stored == []

    def test_daily_limit(self, life, monkeypatch):
        life.reflection.reader._obs = [{"id": f"o{i}", "day": local_day(), "topic_key": f"x{i}"} for i in range(2)]
        with patch.object(life.reflection, "_ask_oracle") as ask:
            life._life_cycle("manual", "t3")
        assert not ask.called

    def test_oracle_down_records_error_no_fallback(self, life):
        with patch.object(life.reflection, "_ask_oracle", return_value=None):
            rec = life._life_cycle("manual", "t4")
        assert rec["error"] == "modello non disponibile" and life._stored == []

    def test_setting_goes_to_themis(self, life):
        out = ("AZIONE: Alza obiettivo\nTIPO: setting\nPRIORITA: high\nDOMINIO: fitness\nTEMA: T1\n"
               "MOTIVO: m\nRIASSUNTO: r\nCHIAVE: hercules.week_goal\nVALORE: 4\n")
        with patch.object(life.reflection, "_propose_setting", return_value=True) as prop, \
                patch.object(life.reflection, "_ask_oracle", return_value=out):
            rec = life._life_cycle("manual", "t5")
        assert prop.called and rec["candidates"][0]["outcome"] == "setting_proposed" and life._stored == []


@pytest.mark.unit
class TestRecapPiece:
    def test_piece_lists_only_that_day(self, life):
        life.reflection.reader._obs = [{"id": "a", "day": "2026-10-20", "text": "Osservazione", "score": 0.7},
                                       {"id": "b", "day": "2026-10-19", "text": "Ieri", "score": 0.9}]
        p = life.reflection.recap_piece("2026-10-20")
        assert p["module"] == "athena" and p["title"] == "Da tenere d'occhio" and p["icon"] == "eye"
        assert [d["text"] for d in p["done"]] == ["Osservazione"]
        assert life.reflection.recap_piece("2026-10-10")["empty"] is True


@pytest.mark.unit
class TestSignalsClient:
    def test_signal_and_metric_shapes(self):
        s = signal("stall:panca", "Panca ferma da 3 sedute", kind="trend", severity="attenzione", page="schede")
        assert s["topic"] == "stall:panca" and s["ttl_days"] == 7
        with pytest.raises(ValueError):
            signal("x", "y", severity="rossa")
        m = metric("fitness.sessions", iso_week(date(2026, 10, 20)), 3)
        assert m["week"] == "2026-W43" and m["value"] == 3.0

    def test_sync_writes_only_changes_and_retracts(self):
        pub = Signals("hercules", "fitness", hub_api_url="http://hub/api")
        week = iso_week(date.today() - timedelta(weeks=1))
        existing = [
            {"kind": "signal", "id": "hercules:stall:panca", "data": {
                **signal("stall:panca", "Panca ferma", severity="attenzione"),
                "expires_at": "2999-01-01T00:00:00+00:00"}},
            {"kind": "signal", "id": "hercules:old", "data": {"key": "old"}},
            {"kind": "metric", "id": f"hercules:fitness.sessions:{week}", "data": {"value": 3.0}},
        ]
        calls = []

        def fake_call(method, path, body=None, query=None, timeout=10):
            calls.append((method, body))
            return {"rows": existing} if method == "GET" else {"applied": []}

        with patch.object(pub, "_call", side_effect=fake_call):
            out = pub.sync([signal("stall:panca", "Panca ferma", severity="attenzione"),
                            signal("pr:squat", "Nuovo record squat", kind="milestone")],
                           [metric("fitness.sessions", week, 3), metric("fitness.sessions", iso_week(), 1)])
        rows = calls[-1][1]["rows"]
        ids = {(r["id"], bool(r.get("deleted"))) for r in rows}
        assert ("hercules:pr:squat", False) in ids and ("hercules:old", True) in ids
        assert ("hercules:stall:panca", False) not in ids              # unchanged, still fresh
        assert not any(r["id"].endswith(week) for r in rows)            # unchanged metric
        assert out == {"written": 2, "retracted": 1}


@pytest.mark.api
class TestApi:
    @pytest.fixture(scope="class")
    def client(self):
        with patch("requests.post"), patch("requests.get"), patch("requests.Session"):
            from fastapi.testclient import TestClient
            import app.main as athena_main
            yield TestClient(athena_main.app), athena_main

    def test_recap_endpoint_and_capability(self, client):
        c, main = client
        with patch.object(main.runtime.reflection, "recap_piece", return_value={"module": "athena", "empty": True}) as rp:
            assert c.get("/api/module/recap", params={"day": "2026-10-20"}).json()["empty"] is True
            rp.assert_called_with("2026-10-20")
        caps = main.service.build_capabilities()
        assert caps["recap_endpoint"] == "/api/module/recap"
        assert any(u.get("id") == "athena.riflessione" or u.get("key") == "athena.riflessione"
                   for u in caps.get("llm_usecases") or [])

    def test_think_vita_and_bad_track(self, client):
        c, main = client
        with patch.object(main.runtime, "think_now", return_value={"status": "started"}) as tn:
            assert c.post("/api/athena/think", params={"track": "vita"}).json()["status"] == "started"
            tn.assert_called_with(track="vita")
        assert c.post("/api/athena/think", params={"track": "altro"}).status_code == 422

    def test_signals_endpoint(self, client):
        c, main = client
        _, series = _series()
        r = _Reader([{"module": "plutus", "domain": "finance", "key": "b", "severity": "alta", "text": "x"}], series)
        with patch.object(main.runtime.reflection, "reader", r):
            body = c.get("/api/athena/signals").json()
        assert body["signals"][0]["key"] == "b" and "fitness.sessions" in body["series"] and body["links"]

    def test_manifest_has_segnali_page_and_tool(self, client):
        c, _ = client
        pages = c.get("/api/ui/manifest").json()["clients"]["webui"]["page"]
        assert [(p["id"], p["order"]) for p in pages] == [("pensieri", 130), ("segnali", 131), ("recap", 132), ("imparato", 133)]
        tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
        t = next(x for x in tools if x["name"] == "athena_signals")
        assert "external" in t["clients"] and t["path"] == "/api/athena/signals"
