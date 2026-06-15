"""Tests — Athena relevance scoring, observer, strategist, and thinking loop.

Tests for AthenaRuntime core logic:
  • relevance signal scoring
  • commitment registration / resolution / pruning
  • retrospective snapshot boosting
  • _record_outcome cycling
  • observer snapshot (mocked Hub/Archive)
  • strategist prompt building and response parsing
  • thinking cycle end-to-end (mocked observer + strategist)
  • thinking record storage
  • API endpoints (health, status, trigger, commitments, thinking, observation)

All mocked — no Hub, no Hermes, no Oracle, no background thread.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def runtime():
    """Return an AthenaRuntime with loop and strategist disabled."""
    with patch("requests.post"), patch("requests.get"), patch("requests.Session"):
        from core.runtime import AthenaRuntime

        rt = AthenaRuntime()
        rt.loop_enabled = False
        rt.strategist.enabled = False
        rt.thinking_archive_enabled = False
        return rt


@pytest.fixture
def live_runtime():
    """Runtime with strategist enabled for thinking tests."""
    with patch("requests.post"), patch("requests.get"), patch("requests.Session"):
        from core.runtime import AthenaRuntime

        rt = AthenaRuntime()
        rt.loop_enabled = False
        rt.thinking_archive_enabled = False
        return rt


# ─────────────────────────────────────────────────────────────────────────────
# Relevance score
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAthenaScore:
    def test_score_returns_float(self, runtime):
        from core.schemas import RelevanceSignals

        signals = RelevanceSignals()
        assert isinstance(runtime.score(signals), float)

    def test_high_urgency_raises_score(self, runtime):
        from core.schemas import RelevanceSignals

        low = runtime.score(RelevanceSignals(urgency=0.1))
        high = runtime.score(RelevanceSignals(urgency=0.9))
        assert high > low

    def test_score_clamped_01(self, runtime):
        from core.schemas import RelevanceSignals

        s = runtime.score(
            RelevanceSignals(
                urgency=1.0, usefulness=1.0, novelty=1.0, confidence=1.0
            )
        )
        assert 0.0 <= s <= 1.0

    def test_high_interruption_cost_reduces_score(self, runtime):
        from core.schemas import RelevanceSignals

        low_cost = runtime.score(
            RelevanceSignals(interruption_cost=0.0, urgency=0.5)
        )
        high_cost = runtime.score(
            RelevanceSignals(interruption_cost=1.0, urgency=0.5)
        )
        assert low_cost >= high_cost


# ─────────────────────────────────────────────────────────────────────────────
# Commitment lifecycle
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAthenaCommitments:
    def test_register_commitment_stored(self, runtime):
        brief = {
            "brief_id": "b1",
            "title": "Test",
            "summary": "Summary",
            "domain": "test",
        }
        runtime._register_commitment(brief=brief, score=0.8, trace_id="t1")
        commitments = runtime.list_commitments()
        assert any(c["brief_id"] == "b1" for c in commitments)

    def test_resolve_commitment_marks_resolved(self, runtime):
        brief = {
            "brief_id": "b2",
            "title": "Test2",
            "summary": "S",
            "domain": "d",
        }
        runtime._register_commitment(brief=brief, score=0.7, trace_id="t2")
        result = runtime.resolve_commitment("b2", status="resolved", note="done")
        assert result is not None
        assert result["resolved"] is True

    def test_resolve_nonexistent_returns_none(self, runtime):
        assert runtime.resolve_commitment("nonexistent_id") is None

    def test_resolved_commitments_excluded_by_default(self, runtime):
        brief = {
            "brief_id": "b3",
            "title": "T",
            "summary": "S",
            "domain": "d",
        }
        runtime._register_commitment(brief=brief, score=0.6, trace_id="t3")
        runtime.resolve_commitment("b3")
        active = runtime.list_commitments(include_resolved=False)
        assert not any(c["brief_id"] == "b3" for c in active)

    def test_expired_commitments_pruned(self, runtime):
        brief = {
            "brief_id": "b4",
            "title": "T",
            "summary": "S",
            "domain": "d",
        }
        runtime._register_commitment(brief=brief, score=0.9, trace_id="t4")
        # Artificially expire
        with runtime._commitments_lock:
            runtime._open_commitments["b4"]["expires_at"] = time.time() - 1
        active = runtime.list_commitments()
        assert not any(c["brief_id"] == "b4" for c in active)

    def test_list_commitments_limit_respected(self, runtime):
        for i in range(10):
            brief = {
                "brief_id": f"blimit_{i}",
                "title": "T",
                "summary": "S",
                "domain": "d",
            }
            runtime._register_commitment(brief=brief, score=0.8, trace_id=f"t{i}")
        result = runtime.list_commitments(limit=3)
        assert len(result) <= 3

    def test_commitment_stores_kind_field(self, runtime):
        brief = {
            "brief_id": "bk",
            "title": "Kind test",
            "summary": "Test",
            "domain": "system",
            "kind": "remediation",
        }
        runtime._register_commitment(brief=brief, score=0.85, trace_id="tk")
        commitments = runtime.list_commitments()
        match = [c for c in commitments if c["brief_id"] == "bk"]
        assert len(match) == 1
        assert match[0].get("kind") == "remediation"


# ─────────────────────────────────────────────────────────────────────────────
# Record outcome and retrospective snapshot
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAthenaRetrospective:
    def test_record_outcome_appended(self, runtime):
        runtime._record_outcome({"outcome": "accepted", "accepted": True})
        assert len(runtime._recent_outcomes) == 1

    def test_retrospective_snapshot_fields_present(self, runtime):
        snap = runtime._retrospective_snapshot()
        assert "window" in snap

    def test_failure_streak_counted(self, runtime):
        for _ in range(3):
            runtime._record_outcome({"outcome": "failed", "accepted": False})
        snap = runtime._retrospective_snapshot()
        assert snap.get("failure_streak", 0) >= 3

    def test_retrospective_boost_raises_signals(self, runtime):
        from core.schemas import RelevanceSignals

        for _ in range(5):
            runtime._record_outcome({"outcome": "failed", "accepted": False})
        base_signals = RelevanceSignals()
        retro = runtime._retrospective_snapshot()
        boosted = runtime._apply_retrospective_to_signals(base_signals, retro)
        assert boosted.urgency >= base_signals.urgency


# ─────────────────────────────────────────────────────────────────────────────
# Observer
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestObserver:
    def test_snapshot_creates_valid_observation(self, runtime):
        """Even with no services, snapshot returns a valid ObservationSnapshot."""
        with patch.object(
            runtime.observer, "observe_services", return_value=([], [])
        ), patch.object(
            runtime.observer, "observe_domains", return_value=[]
        ):
            snap = runtime._observe()
            from core.schemas import ObservationSnapshot

            assert isinstance(snap, ObservationSnapshot)
            assert snap.observation_id
            assert isinstance(snap.services, list)
            assert isinstance(snap.domains, list)

    def test_snapshot_includes_unhealthy_services(self, runtime):
        svc = [
            {
                "name": "scout",
                "base_url": "http://scout:8003",
                "service_type": "module",
                "tags": [],
            }
        ]
        from core.schemas import ServiceSnapshot

        snapshots = [
            ServiceSnapshot(
                name="scout",
                base_url="http://scout:8003",
                service_type="module",
                status="down",
            )
        ]
        with patch.object(
            runtime.observer,
            "observe_services",
            return_value=(snapshots, ["scout"]),
        ), patch.object(
            runtime.observer, "observe_domains", return_value=[]
        ):
            snap = runtime._observe()
            assert "scout" in snap.unhealthy_services
            assert snap.services[0].status == "down"

    def test_observe_domains_no_services_returns_empty(self, runtime):
        """When no services are provided, domains are empty — no static fallback."""
        summaries = runtime.observer.observe_domains(services=None)
        assert summaries == []

    def test_observe_domains_no_domain_layer_services(self, runtime):
        """Services without managed_domain are skipped."""
        from core.schemas import ServiceSnapshot

        non_domain = [
            ServiceSnapshot(name="hub", service_type="core", managed_domain=None),
            ServiceSnapshot(name="oracle", service_type="core", managed_domain=None),
        ]
        summaries = runtime.observer.observe_domains(services=non_domain)
        assert summaries == []


# ─────────────────────────────────────────────────────────────────────────────
# Strategist disabled / Oracle unavailable — no static fallback
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestStrategistDisabled:
    def test_think_returns_empty_when_strategist_disabled(self, runtime):
        """When strategist is off, _think returns empty — no heuristic rules."""
        from core.schemas import ObservationSnapshot

        runtime.strategist.enabled = False
        candidates = runtime._think(ObservationSnapshot(), {})
        assert candidates == []

    def test_think_returns_empty_when_strategist_returns_none(self, live_runtime):
        """When Oracle returns no candidates, return empty — don't invent rules."""
        from core.schemas import ObservationSnapshot

        with patch.object(live_runtime.strategist, "reason", return_value=[]):
            candidates = live_runtime._think(ObservationSnapshot(), {})
            assert candidates == []

    def test_run_once_no_candidates_when_strategist_disabled(self, runtime):
        """Full cycle: strategist off → observe but no candidates emitted."""
        runtime.strategist.enabled = False
        with patch.object(runtime.observer, "observe_services", return_value=([], [])), \
             patch.object(runtime.observer, "observe_domains", return_value=[]):
            runtime._run_once()
        # Thinking record exists but emitted_count is 0
        assert runtime._thinking_records
        record = runtime._thinking_records[-1]
        assert record["emitted_count"] == 0
        # Candidates list is empty
        assert record.get("candidates") == []


# ─────────────────────────────────────────────────────────────────────────────
# Observer domain discovery from Hub topology tags
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDomainDiscovery:
    def test_extract_managed_domain_from_tag(self):
        from core.observer import _extract_managed_domain

        assert _extract_managed_domain(["layer:domain", "domain:real_estate"]) == "real_estate"
        assert _extract_managed_domain(["layer:domain", "domain:calendar"]) == "calendar"
        # _extract_managed_domain only looks for domain:X tag — layer check
        # is performed separately by _discover_domains_from_services()
        assert _extract_managed_domain(["layer:foundation", "domain:storage"]) == "storage"

    def test_extract_managed_domain_no_match(self):
        from core.observer import _extract_managed_domain

        assert _extract_managed_domain([]) is None
        assert _extract_managed_domain(["layer:cognition"]) is None
        assert _extract_managed_domain(["domain:"]) is None  # empty domain value

    def test_extract_layer(self):
        from core.observer import _extract_layer

        assert _extract_layer(["layer:domain", "domain:real_estate"]) == "domain"
        assert _extract_layer(["layer:foundation"]) == "foundation"
        assert _extract_layer([]) is None

    def test_discover_domains_from_services(self, runtime):
        services = [
            {
                "name": "scout",
                "topology_tags": ["layer:domain", "domain:real_estate", "status:stable"],
                "base_url": "http://scout:8003",
            },
            {
                "name": "chronos",
                "topology_tags": ["layer:domain", "domain:calendar", "status:stable"],
                "base_url": "http://chronos:8008",
            },
            {
                "name": "hub",
                "topology_tags": ["layer:foundation", "status:stable"],
                "base_url": "http://hub:19001",
            },
        ]
        domain_map = runtime.observer._discover_domains_from_services(services)
        assert domain_map == {"real_estate": "scout", "calendar": "chronos"}
        # Hub is not layer:domain so it's excluded

    def test_discover_domains_empty_services(self, runtime):
        assert runtime.observer._discover_domains_from_services([]) == {}

    def test_observe_services_includes_managed_domain(self, runtime):
        from core.schemas import ServiceSnapshot

        hub_response = {
            "services": [
                {
                    "name": "scout",
                    "base_url": "http://scout:8003",
                    "service_type": "module",
                    "tags": ["module"],
                    "topology_tags": ["layer:domain", "domain:real_estate", "status:stable"],
                },
                {
                    "name": "hub",
                    "base_url": "http://hub:19001",
                    "service_type": "core",
                    "tags": ["core"],
                    "topology_tags": ["layer:foundation", "status:stable"],
                },
            ]
        }
        with patch.object(
            runtime.observer,
            "_route_get",
            side_effect=[
                hub_response,  # /api/registry/services
                {"services": {}},  # /api/argus/status
            ],
        ):
            services, _ = runtime.observer.observe_services()
            scout = next((s for s in services if s.name == "scout"), None)
            assert scout is not None
            assert scout.managed_domain == "real_estate"
            hub = next((s for s in services if s.name == "hub"), None)
            assert hub is not None
            assert hub.managed_domain is None  # hub is not a domain module

    def test_observe_domains_uses_discovered_domains(self, runtime):
        from core.schemas import ServiceSnapshot

        domain_svc = ServiceSnapshot(
            name="scout",
            service_type="module",
            managed_domain="real_estate",
        )
        with patch.object(
            runtime.observer,
            "_observe_single_domain",
            return_value=None,  # Simulate Archive being down for this domain
        ):
            # Should still attempt to observe the discovered domain
            summaries = runtime.observer.observe_domains(services=[domain_svc])
            # When _observe_single_domain returns None, it's filtered out
            assert isinstance(summaries, list)


class TestStrategistParsing:
    def test_parse_empty_response(self):
        from core.strategist import _parse_candidates

        assert _parse_candidates("") == []
        assert _parse_candidates(None) == []

    def test_parse_nessuna_azione(self):
        from core.strategist import _parse_candidates

        assert _parse_candidates("NESSUNA_AZIONE") == []
        assert _parse_candidates("qualcosa NESSUNA_AZIONE fine") == []

    def test_parse_single_candidate(self):
        from core.strategist import _parse_candidates

        raw = (
            "AZIONE: Controlla servizio scout\n"
            "TIPO: remediation\n"
            "PRIORITA: elevated\n"
            "DOMINIO: system\n"
            "MOTIVO: Scout risulta down\n"
            "RIASSUNTO: Verificare lo stato di Scout e riavviare"
        )
        candidates = _parse_candidates(raw)
        assert len(candidates) == 1
        assert candidates[0]["title"] == "Controlla servizio scout"
        assert candidates[0].get("tipo") == "remediation"
        assert candidates[0].get("priorita") == "elevated"

    def test_parse_multiple_candidates(self):
        from core.strategist import _parse_candidates

        raw = (
            "AZIONE: Azione 1\nTIPO: advisory\nPRIORITA: low\nDOMINIO: cognition\nMOTIVO: motivo1\nRIASSUNTO: riassunto1\n"
            "AZIONE: Azione 2\nTIPO: notification\nPRIORITA: normal\nDOMINIO: calendar\nMOTIVO: motivo2\nRIASSUNTO: riassunto2\n"
        )
        candidates = _parse_candidates(raw)
        assert len(candidates) == 2
        assert candidates[0]["title"] == "Azione 1"
        assert candidates[1]["title"] == "Azione 2"

    def test_map_to_action_candidates(self):
        from core.strategist import _map_to_action_candidates
        from core.schemas import ActionCandidate

        parsed = [
            {
                "title": "Test azione",
                "tipo": "remediation",
                "priorita": "high",
                "dominio": "system",
                "motivo": "Servizio non raggiungibile",
                "riassunto": "Riavvia il servizio",
            }
        ]
        candidates = _map_to_action_candidates(parsed)
        assert len(candidates) == 1
        assert isinstance(candidates[0], ActionCandidate)
        assert candidates[0].priority == "high"
        assert candidates[0].kind == "remediation"
        assert candidates[0].signals.urgency == 0.9  # high priority default

    def test_build_observation_prompt(self):
        from core.strategist import _build_observation_prompt
        from core.schemas import DomainEntitySummary, ObservationSnapshot, ServiceSnapshot

        snap = ObservationSnapshot(
            services=[
                ServiceSnapshot(name="hub", status="up", service_type="core"),
                ServiceSnapshot(name="scout", status="down", service_type="module"),
            ],
            unhealthy_services=["scout"],
            domains=[
                DomainEntitySummary(
                    domain="real_estate",
                    total_entities=42,
                    recent_count=3,
                    pending_count=2,
                    sample_titles=["Appartamento Milano", "Villa Roma"],
                )
            ],
            active_commitments=2,
            unresolved_commitments=1,
            failure_streak=0,
        )
        prompt = _build_observation_prompt(snap)
        assert "scout" in prompt
        assert "real_estate" in prompt
        assert "42" in prompt
        assert "Appartamento Milano" in prompt
        assert "impegni attivi" in prompt.lower()

    def test_build_strategist_prompt_includes_observation(self):
        from core.strategist import _build_strategist_prompt

        obs = "Servizi: hub, archive\nDominio real_estate: 10 entità"
        prompt = _build_strategist_prompt(obs)
        assert obs in prompt
        assert "AZIONE:" in prompt
        assert "NESSUNA_AZIONE" in prompt
        assert "Markdown" in prompt or "markdown" in prompt.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Thinking record storage
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestThinkingRecords:
    def test_store_thinking_record(self, runtime):
        from core.schemas import ThinkingRecord

        record = ThinkingRecord(trace_id="test-trace", trigger="periodic")
        initial_count = len(runtime.list_thinking_records())
        runtime._store_thinking_record(record)
        assert len(runtime.list_thinking_records()) == initial_count + 1

    def test_list_thinking_records_respects_limit(self, live_runtime):
        from core.schemas import ThinkingRecord

        for i in range(10):
            record = ThinkingRecord(
                trace_id=f"trace-{i}", trigger="periodic"
            )
            live_runtime._store_thinking_record(record)
        records = live_runtime.list_thinking_records(limit=5)
        assert len(records) <= 5

    def test_list_thinking_records_newest_first(self, live_runtime):
        from core.schemas import ThinkingRecord

        # Clear any existing records
        live_runtime._thinking_records.clear()

        record1 = ThinkingRecord(trace_id="trace-old", trigger="periodic")
        live_runtime._store_thinking_record(record1)
        record2 = ThinkingRecord(trace_id="trace-new", trigger="periodic")
        live_runtime._store_thinking_record(record2)

        records = live_runtime.list_thinking_records(limit=5)
        # newest first = trace-new
        assert records[0]["trace_id"] == "trace-new"

    def test_thinking_store_max_enforced(self, live_runtime):
        from core.schemas import ThinkingRecord

        live_runtime.thinking_store_max = 5
        for i in range(10):
            record = ThinkingRecord(
                trace_id=f"trace-{i}", trigger="periodic"
            )
            live_runtime._store_thinking_record(record)
        assert len(live_runtime._thinking_records) <= 5

    def test_thinking_record_includes_candidates(self, live_runtime):
        from core.schemas import ActionCandidate, ThinkingRecord

        candidate = ActionCandidate(
            domain="system",
            title="Test action",
            kind="remediation",
            priority="elevated",
            score=0.75,
            accepted=True,
        )
        record = ThinkingRecord(
            trace_id="tc",
            trigger="periodic",
            candidates=[candidate],
            emitted_count=1,
            hint_published=True,
        )
        live_runtime._store_thinking_record(record)
        records = live_runtime.list_thinking_records()
        stored = records[0]
        assert stored["emitted_count"] == 1
        assert stored["hint_published"] is True
        assert len(stored["candidates"]) == 1

    def test_build_brief_from_candidate(self, runtime):
        from core.schemas import ActionCandidate

        candidate = ActionCandidate(
            domain="system",
            title="Fix Scout",
            summary="Scout is down, needs restart",
            kind="remediation",
            target_service="scout",
            priority="high",
            reasoning="Health check shows scout down",
        )
        brief = runtime._build_brief_from_candidate(candidate)
        assert brief["title"] == "Fix Scout"
        assert brief["domain"] == "system"
        assert brief["kind"] == "remediation"
        assert brief["target_service"] == "scout"

    def test_fallback_brief_has_expected_fields(self, runtime):
        brief = runtime._build_fallback_brief()
        assert "brief_id" in brief
        assert "title" in brief
        assert "domain" in brief
        assert brief["domain"] == "cognition"


# ─────────────────────────────────────────────────────────────────────────────
# Runtime _run_once with mocked observer/strategist
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestThinkingCycle:
    def test_run_once_no_candidates_completes(self, runtime):
        """Cycle completes cleanly when strategist returns no candidates."""
        with patch.object(
            runtime.observer,
            "observe_services",
            return_value=([], []),
        ), patch.object(
            runtime.observer,
            "observe_domains",
            return_value=[],
        ), patch.object(
            runtime.strategist, "reason", return_value=[]
        ):
            try:
                runtime._run_once()
            except Exception as e:
                pytest.fail(f"_run_once raised {e}")

        assert runtime._thinking_records
        record = runtime._thinking_records[-1]
        assert record["trigger"] == "periodic"
        assert record["emitted_count"] == 0

    def test_run_once_with_accepted_candidates(self, live_runtime):
        """Accepted candidates are emitted and stored."""
        from core.schemas import ActionCandidate, RelevanceSignals

        candidate = ActionCandidate(
            domain="system",
            title="Health check",
            kind="maintenance",
            priority="normal",
            signals=RelevanceSignals(
                urgency=0.8, usefulness=0.8, novelty=0.5,
                interruption_cost=0.1, confidence=0.9,
            ),
        )

        with patch.object(
            live_runtime.observer,
            "observe_services",
            return_value=([], []),
        ), patch.object(
            live_runtime.observer,
            "observe_domains",
            return_value=[],
        ), patch.object(
            live_runtime.strategist, "reason", return_value=[candidate]
        ), patch.object(
            live_runtime, "_emit_event"
        ) as mock_emit, patch.object(
            live_runtime, "_publish_oracle_hint", return_value=True
        ):
            live_runtime._run_once()
            # Candidate should pass the gate → emit called
            assert mock_emit.called

        assert live_runtime._thinking_records

    def test_run_once_rejected_candidates_not_emitted(self, live_runtime):
        """Candidates below threshold are not emitted but still recorded."""
        from core.schemas import ActionCandidate, RelevanceSignals

        candidate = ActionCandidate(
            domain="cognition",
            title="Low priority thought",
            kind="advisory",
            priority="low",
            signals=RelevanceSignals(
                urgency=0.1, usefulness=0.1, novelty=0.1,
                interruption_cost=0.9, confidence=0.2,
            ),
        )

        with patch.object(
            live_runtime.observer,
            "observe_services",
            return_value=([], []),
        ), patch.object(
            live_runtime.observer,
            "observe_domains",
            return_value=[],
        ), patch.object(
            live_runtime.strategist, "reason", return_value=[candidate]
        ), patch.object(
            live_runtime, "_emit_event"
        ) as mock_emit:
            live_runtime._run_once()
            assert not mock_emit.called

        # Still records the thinking cycle
        record = live_runtime._thinking_records[-1]
        assert record["emitted_count"] == 0

    def test_run_once_emit_failure_recorded(self, live_runtime):
        """When emit fails, error is captured in thinking record."""
        from core.schemas import ActionCandidate, RelevanceSignals

        candidate = ActionCandidate(
            domain="system",
            title="Will fail",
            kind="remediation",
            priority="high",
            signals=RelevanceSignals(
                urgency=1.0, usefulness=0.9, novelty=0.8,
                interruption_cost=0.0, confidence=0.9,
            ),
        )

        with patch.object(
            live_runtime.observer,
            "observe_services",
            return_value=([], []),
        ), patch.object(
            live_runtime.observer,
            "observe_domains",
            return_value=[],
        ), patch.object(
            live_runtime.strategist, "reason", return_value=[candidate]
        ), patch.object(
            live_runtime, "_emit_event", side_effect=Exception("Hermes down")
        ):
            live_runtime._run_once()

        record = live_runtime._thinking_records[-1]
        assert record.get("error") is not None or live_runtime._last_error is not None


# ─────────────────────────────────────────────────────────────────────────────
# Manual trigger with observation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestManualTrigger:
    def test_trigger_includes_observation(self, runtime):
        from core.schemas import TriggerRequest, RelevanceSignals

        with patch.object(
            runtime.observer,
            "observe_services",
            return_value=([], []),
        ), patch.object(
            runtime.observer,
            "observe_domains",
            return_value=[],
        ), patch.object(runtime, "_emit_event"):
            req = TriggerRequest(
                title="Manual test",
                summary="Testing manual trigger",
                domain="cognition",
                signals=RelevanceSignals(
                    urgency=0.9, usefulness=0.9, novelty=0.8,
                    confidence=0.9, interruption_cost=0.1,
                ),
            )
            result = runtime.trigger(req)
            assert result["status"] == "ok"
            assert "observation_id" in result
            assert runtime._thinking_records


# ─────────────────────────────────────────────────────────────────────────────
# Athena FastAPI endpoints
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def athena_client():
    import sys
    import os

    svc_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if svc_dir not in sys.path:
        sys.path.insert(0, svc_dir)
    with patch("requests.post"), patch("requests.get"), patch("requests.Session"):
        from fastapi.testclient import TestClient
        import importlib
        import app.main as athena_main

        importlib.reload(athena_main)
        client = TestClient(athena_main.app)
        yield client


@pytest.mark.api
class TestAthenaApiHealth:
    def test_health_returns_200(self, athena_client):
        resp = athena_client.get("/health")
        assert resp.status_code == 200

    def test_health_body_ok(self, athena_client):
        body = athena_client.get("/health").json()
        assert body.get("status") == "ok"
        assert "athena" in body.get("service", "").lower()


@pytest.mark.api
class TestAthenaApiStatus:
    def test_status_endpoint_returns_200(self, athena_client):
        resp = athena_client.get("/api/athena/status")
        assert resp.status_code == 200

    def test_status_body_has_emit_threshold(self, athena_client):
        body = athena_client.get("/api/athena/status").json()
        runtime_data = body.get("runtime", body)
        assert "emit_threshold" in runtime_data

    def test_status_body_has_strategist_field(self, athena_client):
        body = athena_client.get("/api/athena/status").json()
        runtime_data = body.get("runtime", body)
        assert "strategist_enabled" in runtime_data


@pytest.mark.api
class TestAthenaApiTrigger:
    def test_trigger_returns_200(self, athena_client):
        with patch("requests.post"):
            resp = athena_client.post(
                "/api/athena/trigger",
                json={
                    "title": "Test brief",
                    "summary": "Test summary",
                    "domain": "test",
                    "signals": {
                        "urgency": 0.9,
                        "usefulness": 0.9,
                        "novelty": 0.8,
                        "confidence": 0.9,
                        "interruption_cost": 0.1,
                    },
                },
            )
        assert resp.status_code == 200

    def test_trigger_accepted_in_response(self, athena_client):
        with patch("requests.post"):
            resp = athena_client.post(
                "/api/athena/trigger",
                json={
                    "title": "High urgency",
                    "domain": "cognition",
                    "signals": {
                        "urgency": 1.0,
                        "usefulness": 1.0,
                        "novelty": 1.0,
                        "confidence": 1.0,
                        "interruption_cost": 0.0,
                    },
                },
            )
        body = resp.json()
        assert "accepted" in body


@pytest.mark.api
class TestAthenaApiCommitments:
    def test_commitments_endpoint_returns_200(self, athena_client):
        resp = athena_client.get("/api/athena/commitments")
        assert resp.status_code == 200

    def test_commitments_body_has_items_list(self, athena_client):
        body = athena_client.get("/api/athena/commitments").json()
        items = body.get("items") or body.get("commitments", [])
        assert isinstance(items, list)


@pytest.mark.api
class TestAthenaApiThinking:
    def test_thinking_endpoint_returns_200(self, athena_client):
        resp = athena_client.get("/api/athena/thinking")
        assert resp.status_code == 200

    def test_thinking_body_has_thinking_list(self, athena_client):
        body = athena_client.get("/api/athena/thinking").json()
        assert body.get("status") == "ok"
        assert isinstance(body.get("thinking", []), list)
        assert "count" in body

    def test_thinking_limit_respected(self, athena_client):
        resp = athena_client.get("/api/athena/thinking?limit=3")
        body = resp.json()
        assert len(body.get("thinking", [])) <= 3


@pytest.mark.api
class TestAthenaApiObservation:
    def test_observation_endpoint_returns_200(self, athena_client):
        resp = athena_client.get("/api/athena/observation")
        assert resp.status_code == 200

    def test_observation_body_has_services_list(self, athena_client):
        body = athena_client.get("/api/athena/observation").json()
        assert body.get("status") == "ok"
        obs = body.get("observation", {})
        assert isinstance(obs.get("services", []), list)


@pytest.mark.api
class TestAthenaApiTasks:
    def test_tasks_endpoint_returns_200(self, athena_client):
        resp = athena_client.get("/api/athena/tasks")
        assert resp.status_code == 200

    def test_tasks_body_has_tasks_list(self, athena_client):
        body = athena_client.get("/api/athena/tasks").json()
        assert isinstance(body.get("tasks", []), list)

    def test_task_by_id_404_for_unknown(self, athena_client):
        resp = athena_client.get("/api/athena/tasks/nonexistent-id")
        assert resp.status_code == 404
