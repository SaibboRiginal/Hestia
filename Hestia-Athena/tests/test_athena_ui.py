"""Athena inside view (WebUI plugin «Pensieri», SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/§B4):
every candidate kept with the gate's reason and outcome, «Pensa ora», compact summary, manifest, MCP tool."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from core import athena_settings as S
from core.schemas import ActionCandidate, RelevanceSignals

HIGH = RelevanceSignals(urgency=0.9, usefulness=0.9, novelty=0.6, interruption_cost=0.1, confidence=0.9)
LOW = RelevanceSignals(urgency=0.1, usefulness=0.1, novelty=0.1, interruption_cost=0.9, confidence=0.2)


def _set(monkeypatch, key, value):
    monkeypatch.setitem(S.settings._effective, key, value)


@pytest.fixture
def rt(monkeypatch):
    from core.runtime import AthenaRuntime
    _set(monkeypatch, S.LOOP_ENABLED, False)
    _set(monkeypatch, S.STRATEGIST_ENABLED, True)
    _set(monkeypatch, S.THINKING_ARCHIVE_ENABLED, False)
    r = AthenaRuntime()
    monkeypatch.setattr(r.observer, "observe_services", lambda *a, **k: ([], []))
    monkeypatch.setattr(r.observer, "observe_domains", lambda *a, **k: [])
    monkeypatch.setattr(r, "_emit_event", lambda **k: None)
    monkeypatch.setattr(r, "_publish_oracle_hint", lambda **k: True)
    monkeypatch.setattr(r, "_window_open", lambda *a, **k: True)
    monkeypatch.setattr(r, "_heavy_allowed", lambda: False)
    return r


def _cands():
    return [ActionCandidate(title="Controlla backup", kind="maintenance", signals=HIGH),
            ActionCandidate(title="Idea debole", kind="advisory", signals=LOW)]


@pytest.mark.unit
class TestGateHistory:
    def test_cycle_keeps_accepted_and_discarded_with_reasons(self, rt):
        with patch.object(rt.strategist, "reason", return_value=_cands()):
            rt._run_once()
        rec = rt._thinking_records[-1]
        assert rec["trigger"] == "periodic" and rec["threshold"] == rt.emit_threshold
        assert rec["duration_ms"] >= 0 and rec["emitted_count"] == 1
        by = {c["title"]: c for c in rec["candidates"]}
        ok, ko = by["Controlla backup"], by["Idea debole"]
        assert ok["accepted"] and ok["outcome"] == "emitted" and "≥ soglia" in ok["gate_reason"]
        assert not ko["accepted"] and ko["outcome"] == "discarded"
        assert "< soglia" in ko["gate_reason"] and "bassa" in ko["gate_reason"]

    def test_think_still_returns_accepted_only(self, rt):
        from core.schemas import ObservationSnapshot
        with patch.object(rt.strategist, "reason", return_value=_cands()):
            assert [c.title for c in rt._think(ObservationSnapshot(), {})] == ["Controlla backup"]

    def test_improvement_outcome_says_if_forge_took_it(self, rt, monkeypatch):
        c = ActionCandidate(title="Migliora prompt", kind="improvement", signals=HIGH)
        monkeypatch.setattr(rt, "_send_to_forge", lambda *a: False)
        with patch.object(rt.strategist, "reason", return_value=[c]):
            rt._run_once()
        assert rt._thinking_records[-1]["candidates"][0]["outcome"] == "forge_skipped"

    def test_gate_reason_names_weak_factors(self, rt):
        text = rt.gate_reason(LOW, rt.score(LOW), False)
        assert text.startswith("punteggio") and ("urgenza bassa" in text or "utilità bassa" in text)

    def test_periodic_cycle_skips_while_a_cycle_runs(self, rt):
        rt._cycle_lock.acquire()
        try:
            with patch.object(rt.strategist, "reason", return_value=_cands()) as reason:
                rt._run_once()
            assert not reason.called and not rt._thinking_records
        finally:
            rt._cycle_lock.release()


@pytest.mark.unit
class TestThinkNow:
    def test_think_now_runs_one_manual_cycle_and_reports_busy(self, rt):
        gate = threading.Event()
        done = threading.Event()
        real = rt._thinking_cycle

        def slow(trigger, trace_id):
            gate.wait(5)
            try:
                return real(trigger, trace_id)
            finally:
                done.set()
        rt._thinking_cycle = slow
        with patch.object(rt.strategist, "reason", return_value=_cands()):
            first = rt.think_now()
            assert first["status"] == "started" and rt.cycle_running
            assert rt.think_now()["status"] == "busy"
            gate.set()
            assert done.wait(5)
        for _ in range(100):
            if not rt.cycle_running:
                break
            threading.Event().wait(0.01)
        assert not rt.cycle_running
        rec = rt._thinking_records[-1]
        assert rec["trigger"] == "manual" and rec["trace_id"] == first["trace_id"]

    def test_summary_is_compact(self, rt):
        with patch.object(rt.strategist, "reason", return_value=_cands()):
            rt._run_once()
        out = rt.thinking_summary(limit=5)
        assert out["count"] == 1 and out["running"] is False and out["threshold"] == rt.emit_threshold
        assert set(out["weights"]) == {"urgency", "usefulness", "novelty", "confidence", "interruption_cost"}
        cyc = out["cycles"][0]
        assert isinstance(cyc["observation"]["services"], int)
        assert "raw_errors" not in cyc["observation"]
        assert {c["outcome"] for c in cyc["candidates"]} == {"emitted", "discarded"}
        assert set(cyc["candidates"][0]["signals"]) >= {"urgency", "interruption_cost"}


@pytest.fixture(scope="module")
def client():
    with patch("requests.post"), patch("requests.get"), patch("requests.Session"):
        from fastapi.testclient import TestClient
        import app.main as athena_main
        yield TestClient(athena_main.app), athena_main


@pytest.mark.api
class TestAthenaUiApi:
    def test_manifest_core_page_widget_quick_action(self, client):
        c, _ = client
        m = c.get("/api/ui/manifest").json()
        assert m["module"] == "athena" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["api_prefix"] == "/api/athena/" and web["entry"] == "/ui/webui/athena.js"
        page = web["page"][0]
        assert (page["id"], page["element"], page["order"]) == ("pensieri", "athena-thoughts", 130)
        w = web["widget"][0]
        assert w["element"] == "athena-last-widget" and w["auto"] is True and w["open_page"] == "pensieri"
        qa = web["quick_action"][0]
        assert qa["method"] == "POST" and qa["path"] == "/api/athena/think"

    def test_thinking_summary_endpoint(self, client):
        c, _ = client
        body = c.get("/api/athena/thinking/summary", params={"limit": 3}).json()
        assert body["status"] == "ok" and isinstance(body["cycles"], list) and "running" in body

    def test_think_endpoint(self, client):
        c, main = client
        with patch.object(main.runtime, "think_now", return_value={"status": "started", "trace_id": "t"}) as tn:
            assert c.post("/api/athena/think").json()["status"] == "started"
            assert tn.called

    def test_mcp_tool_athena_thinking_is_read_only_and_external(self, client):
        c, _ = client
        tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
        t = next(x for x in tools if x["name"] == "athena_thinking")
        assert "external" in t["clients"] and "ui" in t["clients"]
        assert t.get("method", "GET") == "GET" and t["path"] == "/api/athena/thinking/summary"
        assert t.get("telegram_visible") is False
        assert "limit" in t["inputSchema"]["properties"]

    def test_mcp_call_athena_thinking(self, client):
        c, _ = client
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                 "params": {"name": "athena_thinking", "arguments": {"limit": 2}}}).json()
        assert "error" not in r

    def test_hub_capabilities_carry_the_manifest(self, client):
        _, main = client
        caps = main.service.build_capabilities()
        assert caps["ui_manifest"].endswith("/api/ui/manifest") and caps["think_now_endpoint"] == "/api/athena/think"
