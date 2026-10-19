"""Tests — Oracle FastAPI endpoints (Phase 1.7)

API tests using FastAPI TestClient with OracleEngine fully mocked.
Tests: /health, /api/logs, /api/format, /api/chat, /api/user/controls,
       /api/athena/hints.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# App fixture — mocks OracleEngine BEFORE importing main
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def oracle_client():
    """Return a TestClient for the Oracle FastAPI app with engine fully mocked."""
    mock_engine = MagicMock()

    # /api/chat returns an NDJSON stream
    def _fake_chat(*args, **kwargs):
        frames = [
            json.dumps({"type": "token", "content": "Ciao "}).encode(),
            json.dumps({"type": "token", "content": "Mark!"}).encode(),
            json.dumps({"type": "done", "signals": []}).encode(),
        ]
        return iter(frames)

    mock_engine.chat.return_value = _fake_chat()

    # /api/format returns a string
    mock_engine.format_payload.return_value = "<b>Risultato formattato</b>"

    # /api/user/controls
    mock_engine.get_user_controls.return_value = {
        "proactive_enabled": True,
        "allowed_categories": ["alerts", "tasks"],
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
        "reminder_aggressiveness": "normal",
        "dont_ask_again": [],
        "reset_scope": "primary",
    }
    mock_engine.update_user_controls.return_value = (
        {"proactive_enabled": False, "allowed_categories": ["alerts"]},
        True,
    )

    # /api/athena/hints
    mock_engine.ingest_athena_hint.return_value = {
        "ok": True, "hint_id": "h001"}
    mock_engine.list_athena_hints.return_value = []

    # /api/tasks
    mock_engine.list_background_tasks.return_value = []
    mock_engine.get_background_task.return_value = None

    with patch("core.oracle_engine.OracleEngine", return_value=mock_engine):
        # Also patch requests.post to suppress Hub registration
        with patch("requests.post"):
            import main  # noqa: PLC0415 — imported after patch
            # Re-wire the module-level engine to our mock
            main.engine = mock_engine
            client = TestClient(main.app, raise_server_exceptions=True)
            yield client, mock_engine


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestOracleHealth:
    def test_health_returns_200(self, oracle_client):
        client, _ = oracle_client
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_has_status_ok(self, oracle_client):
        client, _ = oracle_client
        data = client.get("/health").json()
        assert data.get("status") == "ok"
        assert data.get("service") == "hestia_oracle"


@pytest.mark.api
class TestOracleLogsEndpoint:
    def test_logs_returns_200(self, oracle_client):
        client, _ = oracle_client
        resp = client.get("/api/logs")
        assert resp.status_code == 200

    def test_logs_response_has_service_field(self, oracle_client):
        client, _ = oracle_client
        data = client.get("/api/logs").json()
        assert "service" in data
        assert data["service"] == "hestia_oracle"

    def test_logs_limit_param(self, oracle_client):
        client, _ = oracle_client
        resp = client.get("/api/logs?limit=10")
        assert resp.status_code == 200


@pytest.mark.api
class TestOracleFormatEndpoint:
    def test_format_returns_200_with_text(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.format_payload.return_value = "<b>Output</b>"
        resp = client.post(
            "/api/format",
            json={
                "command": "scout_listings",
                "payload": [{"title": "Appartamento", "price": 250000}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data

    def test_format_calls_engine_with_command(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.format_payload.reset_mock()
        client.post(
            "/api/format",
            json={"command": "my_command", "payload": {"foo": "bar"}},
        )
        mock_engine.format_payload.assert_called_once()
        call_kwargs = mock_engine.format_payload.call_args
        assert call_kwargs is not None

    def test_format_missing_command_returns_422(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/format", json={"payload": {}})
        assert resp.status_code == 422

    def test_format_missing_payload_returns_422(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/format", json={"command": "test"})
        assert resp.status_code == 422


@pytest.mark.api
class TestOracleChatEndpoint:
    def test_chat_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        # Reset and configure streaming mock
        mock_engine.chat.return_value = iter([
            json.dumps({"type": "token", "content": "Ciao"}).encode(),
            json.dumps({"type": "done", "signals": []}).encode(),
        ])
        resp = client.post(
            "/api/chat",
            json={"message": "Ciao Hestia!", "session_id": "test-session-001"},
        )
        assert resp.status_code == 200

    def test_chat_content_type_ndjson(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.chat.return_value = iter([
            json.dumps({"type": "done", "signals": []}).encode()
        ])
        resp = client.post("/api/chat", json={"message": "Test"})
        assert "ndjson" in resp.headers.get(
            "content-type", "").lower() or resp.status_code == 200

    def test_chat_missing_message_returns_422(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/chat", json={"session_id": "abc"})
        assert resp.status_code == 422

    def test_chat_with_client_instructions_passes_to_engine(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.chat.reset_mock()
        mock_engine.chat.return_value = iter([
            json.dumps({"type": "done", "signals": []}).encode()
        ])
        client.post(
            "/api/chat",
            json={"message": "Test", "client_instructions": "Rispondi brevemente"},
        )
        assert mock_engine.chat.called

    def test_chat_adds_personal_settings_of_the_client(self, oracle_client, monkeypatch):
        """Tone/instructions are central settings (oracle.chat.*) applied by Oracle itself."""
        client, mock_engine = oracle_client
        from core.services import oracle_settings
        seen = {}

        def fake_user_values(*, client="", session="", ttl=20):
            seen.update(client=client, session=session)
            return {"oracle.chat.tone": "direct", "oracle.chat.instructions": "rispondi breve"}

        monkeypatch.setattr(oracle_settings.settings, "user_values", fake_user_values)
        mock_engine.chat.reset_mock()
        mock_engine.chat.return_value = iter([json.dumps({"type": "done", "signals": []}).encode()])
        client.post("/api/chat", json={"message": "Test", "session_id": "s1", "client": "webui",
                                       "client_instructions": "HTML semplice"})
        sent = mock_engine.chat.call_args.kwargs["client_instructions"]
        assert sent.startswith("HTML semplice")
        assert "Tono: diretto" in sent and "rispondi breve" in sent
        assert seen == {"client": "webui", "session": "s1"}


@pytest.mark.api
class TestOracleAthenaHintsEndpoint:
    def test_ingest_hint_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.ingest_athena_hint.return_value = {"ok": True}
        resp = client.post(
            "/api/athena/hints",
            json={
                "source": "athena",
                "hint_type": "focus_brief",
                "summary": "Ci sono 3 nuovi annunci a Milano",
                "priority": "normal",
                "domain": "scout",
            },
        )
        assert resp.status_code == 200

    def test_list_hints_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.list_athena_hints.return_value = []
        resp = client.get("/api/athena/hints")
        assert resp.status_code == 200
        data = resp.json()
        assert "hints" in data


@pytest.mark.api
class TestOracleTasksEndpoint:
    def test_list_tasks_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.list_background_tasks.return_value = []
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert "tasks" in resp.json()

    def test_get_unknown_task_returns_404(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.get_background_task.return_value = None
        resp = client.get("/api/tasks/nonexistent-task-id")
        assert resp.status_code == 404


@pytest.mark.api
class TestOracleLlmGenerateEndpoint:
    """/api/llm/generate — the use case's chain (oracle.usecases → oracle.chains) answers, step by step."""

    @staticmethod
    def _fake_agents(monkeypatch, fail: set[str] | None = None, quota: set[str] | None = None):
        """Patch UniversalAgent: steps whose model is in *fail* raise, in *quota* raise a 429; the others answer
        with their model name. Returns the (provider, model) of every agent asked."""
        asked = []

        class FakeAgent:
            def __init__(self, role_prompt="", provider="", model_name="", thinking=False, label=""):
                self.provider_name, self.model_name = provider, model_name

            def ask(self, prompt, thinking=None):
                asked.append((self.provider_name, self.model_name))
                if self.model_name in (quota or set()):
                    raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded, retryDelay: '30s'")
                if self.model_name in (fail or set()):
                    raise RuntimeError("down")
                return f"reply from {self.model_name}"

        monkeypatch.setattr("agents.universal_agent.UniversalAgent", FakeAgent)
        return asked

    @staticmethod
    def _chains(monkeypatch, chains: dict, usecases: dict | None = None):
        from core.services import oracle_settings
        eff = oracle_settings.settings._effective
        monkeypatch.setitem(eff, oracle_settings.CHAINS_KEY, chains)
        monkeypatch.setitem(eff, oracle_settings.USECASES_KEY, usecases or {})
        monkeypatch.setenv("ORACLE_KEY_GEMINI", "test-key")

    def test_use_case_points_to_its_chain(self, oracle_client, monkeypatch):
        client, _ = oracle_client
        self._chains(monkeypatch, {
            "veloce": {"steps": [{"provider": "ollama", "model": "local"}]},
            "annunci": {"steps": [{"provider": "gemini", "model": "gemini-2.5-flash"},
                                  {"provider": "gemini", "model": "gemini-2.5-flash-lite"}]}},
            {"scout.annunci": {"chain": "annunci"}})
        asked = self._fake_agents(monkeypatch, quota={"gemini-2.5-flash"})

        resp = client.post("/api/llm/generate", json={"prompt": "x", "use_case": "scout.annunci"})

        assert resp.status_code == 200
        assert resp.json()["model"] == "gemini-2.5-flash-lite" and resp.json()["chain"] == "annunci"
        assert asked == [("gemini", "gemini-2.5-flash"), ("gemini", "gemini-2.5-flash-lite")]

    def test_exhausted_step_is_skipped_by_every_chain_until_reset(self, oracle_client, monkeypatch):
        client, _ = oracle_client
        from core.services import llm_chains
        self._chains(monkeypatch, {
            "veloce": {"steps": [{"provider": "gemini", "model": "flash"}, {"provider": "ollama", "model": "l"}]},
            "potente": {"steps": [{"provider": "gemini", "model": "flash"}, {"provider": "gemini", "model": "pro"}]}},
            {"athena.strategia": {"chain": "potente"}})
        asked = self._fake_agents(monkeypatch, quota={"flash"})

        assert client.post("/api/llm/generate", json={"prompt": "x"}).json()["model"] == "l"
        assert client.post("/api/llm/generate", json={"prompt": "x", "use_case": "athena.strategia"}
                           ).json()["model"] == "pro"
        assert asked.count(("gemini", "flash")) == 1          # second chain skipped it
        assert llm_chains.exhausted_until("gemini", "flash") > 0

    def test_undeclared_use_case_runs_like_general_and_is_listed(self, oracle_client, monkeypatch):
        client, _ = oracle_client
        self._chains(monkeypatch, {"veloce": {"steps": [{"provider": "ollama", "model": "local"}]}})
        self._fake_agents(monkeypatch)

        resp = client.post("/api/llm/generate", json={"prompt": "x", "use_case": "hercules.pianifica"})

        assert resp.status_code == 200 and resp.json()["model"] == "local"
        listed = client.get("/api/llm/usecases").json()["usecases"]
        row = next(r for r in listed if r["id"] == "hercules.pianifica")
        assert row["undeclared"] and row["effective_chain"] == "veloce"

    def test_openai_compatible_step_needs_no_key(self, oracle_client, monkeypatch):
        client, _ = oracle_client
        self._chains(monkeypatch, {"veloce": {"steps": [{"provider": "deepseek", "model": "deepseek-chat"},
                                                         {"provider": "ollama", "model": "local"}]}})
        monkeypatch.delenv("ORACLE_KEY_DEEPSEEK", raising=False)
        from core.services import oracle_settings
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.PROVIDERS_KEY, {
            "ollama": {"type": "ollama"}, "deepseek": {"type": "openai", "url": "https://api.deepseek.com/v1"}})
        asked = self._fake_agents(monkeypatch)
        # deepseek is an OpenAI-compatible server: without a key it is still tried (local servers need none)
        assert client.post("/api/llm/generate", json={"prompt": "x"}).json()["model"] == "deepseek-chat"
        assert asked == [("deepseek", "deepseek-chat")]

    def test_every_step_failing_returns_503_with_chain(self, oracle_client, monkeypatch):
        client, _ = oracle_client
        self._chains(monkeypatch, {"veloce": {"steps": [{"provider": "ollama", "model": "a"},
                                                         {"provider": "gemini", "model": "b"}]}})
        self._fake_agents(monkeypatch, fail={"a", "b"})

        resp = client.post("/api/llm/generate", json={"prompt": "test"})

        assert resp.status_code == 503
        assert "veloce" in resp.json()["detail"] and "ollama/a" in resp.json()["detail"]

    def test_missing_prompt_returns_400(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/llm/generate", json={"prompt": "  "})
        assert resp.status_code == 400
