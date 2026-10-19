"""Oracle inside view (WebUI plugin «Cervello», SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2):
manifest, /api/ui/activity · /api/ui/stats · /api/ui/code, daily LLM totals, recent turns, Claude Code runs."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.services import activity_log, claude_code_runner, llm_stats


@pytest.fixture(autouse=True)
def _clean():
    llm_stats.reset()
    activity_log.reset()
    yield
    llm_stats.reset()
    activity_log.reset()


@pytest.fixture(scope="module")
def client():
    with patch("core.oracle_engine.OracleEngine", return_value=MagicMock()), patch("requests.post"):
        import main  # noqa: PLC0415
        yield TestClient(main.app)


# ── llm_stats daily totals ───────────────────────────────────────────────────

@pytest.mark.unit
class TestDailyTotals:
    def test_today_totals_and_split_per_use_case_model(self):
        llm_stats.record("generic", "ollama", "m1", prompt_tokens=100, cached_tokens=20, output_tokens=10)
        llm_stats.record("generic", "ollama", "m1", prompt_tokens=50, output_tokens=5)
        llm_stats.record("reasoning", "gemini", "g1", prompt_tokens=30, output_tokens=3, cost_usd=0.002)
        out = llm_stats.daily(7)
        assert len(out["days"]) == 7 and out["days"][-1]["day"] == date.today().isoformat()
        t = out["today"]
        assert (t["calls"], t["input_tokens"], t["cached_tokens"], t["output_tokens"]) == (3, 180, 20, 18)
        assert t["cost_usd"] == pytest.approx(0.002)
        split = out["today_by_model"]
        assert split[0] == {"use_case": "generic", "provider": "ollama", "model": "m1", "calls": 2,
                            "input_tokens": 150, "cached_tokens": 20, "output_tokens": 15, "cost_usd": 0.0}
        assert {r["use_case"] for r in split} == {"generic", "reasoning"}

    def test_empty_days_are_zero_and_old_days_are_dropped(self):
        old = datetime.now() - timedelta(days=60)
        with patch("core.services.llm_stats.time.time", return_value=old.timestamp()):
            llm_stats.record("generic", "ollama", "m", prompt_tokens=10)
        llm_stats.record("generic", "ollama", "m", prompt_tokens=10)
        assert len(llm_stats._daily) <= llm_stats._DAYS
        out = llm_stats.daily(3)
        assert [d["calls"] for d in out["days"]] == [0, 0, 1]

    def test_days_param_is_clamped(self):
        assert len(llm_stats.daily(999)["days"]) == llm_stats._DAYS
        assert len(llm_stats.daily(0)["days"]) == 14


# ── recent turns ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestActivityLog:
    def test_record_turn_newest_first_with_usage_delta(self):
        activity_log.record_turn(session_id="s1", mode="auto", route="quick", model="m", provider="ollama",
                                 message="primo")
        row = activity_log.record_turn(
            session_id="s1", client="webui", mode="auto", route="agent", model="m", provider="ollama",
            domains=["agenda"], tool_log=[{"tool": "a", "ok": True}, {"tool": "b", "ok": False, "writes": True}],
            total_ms=1234, message="x" * 200,
            usage_before={"calls": 1, "input_tokens": 10, "output_tokens": 1, "cost_usd": 0.0},
            usage_after={"calls": 3, "input_tokens": 70, "output_tokens": 9, "cost_usd": 0.001})
        assert row["usage"] == {"calls": 2, "input_tokens": 60, "output_tokens": 8, "cost_usd": 0.001}
        assert row["tools_failed"] == 1 and row["tools"][1] == {"tool": "b", "ok": False, "writes": True}
        assert len(row["preview"]) == 81 and row["preview"].endswith("…")
        rows = activity_log.recent(10)
        assert [r["route"] for r in rows] == ["agent", "quick"]

    def test_ring_is_bounded_and_never_raises(self):
        for i in range(activity_log._MAX + 5):
            activity_log.record_turn(session_id=str(i), mode="auto", route="quick", model="m", provider="p")
        assert len(activity_log.recent(10_000)) == activity_log._MAX
        assert activity_log.record_turn(session_id="x", mode="auto", route="quick", model="m", provider="p",
                                        tool_log=[object()]) == {}


# ── Claude Code recent runs ──────────────────────────────────────────────────

@pytest.mark.unit
class TestClaudeCodeRuns:
    def test_runs_are_kept_ok_and_failed(self, monkeypatch):
        claude_code_runner._runs.clear()
        monkeypatch.setattr(claude_code_runner, "_run", lambda *a, **k: {"ok": True, "turns": 4, "cost_usd": 0.5})
        claude_code_runner.run("/forge/worktrees/task-abc", "do it")

        def boom(*a, **k):
            raise claude_code_runner.ClaudeCodeError("claude timed out", 504)
        monkeypatch.setattr(claude_code_runner, "_run", boom)
        with pytest.raises(claude_code_runner.ClaudeCodeError):
            claude_code_runner.run("/forge/worktrees/task-def", "do it")
        out = claude_code_runner.runs()
        assert out["running"] == 0
        assert [(r["task"], r["state"], r["ok"]) for r in out["runs"]] == [
            ("task-def", "failed", False), ("task-abc", "done", True)]
        assert out["runs"][1]["turns"] == 4 and out["runs"][0]["error"] == "claude timed out"


# ── HTTP: manifest + /api/ui/* ───────────────────────────────────────────────

@pytest.mark.api
class TestUiApi:
    def test_manifest_is_core_with_cervello_and_widget(self, client):
        m = client.get("/api/ui/manifest").json()
        assert m["module"] == "oracle" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["entry"] == "/ui/webui/oracle.js" and web["api_prefix"] == "/api/ui/"
        pages = {p["id"]: p for p in web["page"]}
        assert pages["cervello"]["element"] == "oracle-brain" and pages["cervello"]["order"] == 120
        widgets = {w["id"]: w for w in web["widget"]}
        assert widgets["uso-oggi"]["element"] == "oracle-usage-widget"
        assert widgets["uso-oggi"]["open_page"] == "cervello"

    def test_activity(self, client):
        activity_log.record_turn(session_id="s", mode="auto", route="agent", model="m", provider="p",
                                 domains=["agenda"], tool_log=[{"tool": "t", "ok": True}])
        data = client.get("/api/ui/activity", params={"limit": 5}).json()
        assert data["count"] == 1 and data["turns"][0]["domains"] == ["agenda"]
        assert "idle_seconds" in data and "last_user_activity_ts" in data

    def test_stats_has_days_today_and_use_case_labels(self, client):
        llm_stats.record("generic", "ollama", "m", prompt_tokens=10, output_tokens=2)
        llm_stats.record("claude_code", "claude_code", "default", prompt_tokens=5, cost_usd=0.1)
        data = client.get("/api/ui/stats", params={"days": 3}).json()
        assert len(data["days"]) == 3 and data["today"]["calls"] == 2
        labels = {r["use_case"]: r["label"] for r in data["today_by_model"]}
        assert labels == {"generic": "Uso generale", "claude_code": "Claude Code (Forge)"}
        assert {r["use_case"] for r in data["use_cases"]} == {"generic", "claude_code"}
        assert data["use_cases"][0]["label"]

    def test_code_status_and_runs(self, client, monkeypatch):
        monkeypatch.setattr(claude_code_runner, "status", lambda: {"available": False, "detail": "not installed"})
        data = client.get("/api/ui/code").json()
        assert data["available"] is False and data["detail"] == "not installed"
        assert "running" in data and isinstance(data["runs"], list)

    def test_hub_capabilities_carry_the_manifest(self):
        import main  # noqa: PLC0415
        with patch("main.requests.post") as post:
            post.return_value.status_code = 200
            main._register_on_hub()
        caps = post.call_args.kwargs["json"]["capabilities"]
        assert caps["ui_manifest"].endswith("/api/ui/manifest") and caps["ui_version"]


# ── Cervello → Modelli / Uso (dossier 2026-10-19-oracle-a-blocchi) ─────────────

@pytest.mark.api
class TestModelsTab:
    def test_models_view_has_no_keys(self, client, monkeypatch):
        monkeypatch.setenv("ORACLE_KEY_DEEPSEEK", "sk-secret")
        out = client.get("/api/ui/models").json()
        assert "sk-secret" not in str(out)
        assert {"providers", "types", "chains", "usecases", "modes"} <= set(out)
        assert any(u["id"] == "oracle.generale" for u in out["usecases"])

    def test_write_goes_through_themis_and_validates(self, client, monkeypatch):
        from core.services import oracle_settings
        puts = []
        monkeypatch.setattr(oracle_settings.settings, "put", lambda k, v, **kw: puts.append((k, v, kw)) or True)
        ok = client.put("/api/ui/models/chains", json={"value": {"veloce": {"steps": [{"provider": "ollama", "model": "m"}]}}})
        assert ok.status_code == 200 and puts[0][0] == oracle_settings.CHAINS_KEY and puts[0][2]["actor"] == "user"
        assert client.put("/api/ui/models/providers", json={"value": {"x": {"type": "nope"}}}).status_code == 400
        assert client.put("/api/ui/models/chains", json={"value": {"c": {}}}).status_code == 400
        assert client.put("/api/ui/models/other", json={"value": {}}).status_code == 404

    def test_quota_reset_one_pair(self, client):
        from core.services import llm_chains
        import time as _t
        llm_chains._exhausted[("gemini", "a")] = _t.time() + 600
        llm_chains._exhausted[("gemini", "b")] = _t.time() + 600
        client.post("/api/ui/models/quota/reset", params={"provider": "gemini", "model": "a"})
        assert set(llm_chains.exhausted_for("gemini")) == {"b"}
