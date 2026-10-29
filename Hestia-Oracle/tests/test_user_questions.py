"""The assistant asks the user (docs/work/2026-10-19-oracle-offline v3 A): tool ask_user stops the turn,
the answer becomes the next chat turn."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.agent_loop import ToolDefinition, run_agent_loop
from core.services import stream_emitter, user_questions


def _ask_tool() -> ToolDefinition:
    return ToolDefinition(name="ask_user", description=user_questions.TOOL_DESCRIPTION,
                          parameters=user_questions.TOOL_PARAMETERS, handler=user_questions.build_question)


@pytest.mark.unit
class TestBuildQuestion:
    def test_confirm_has_yes_no(self):
        ok, res = user_questions.build_question("Cancello l'evento di domani?", "confirm")
        assert ok and res["ask"]["kind"] == "confirm"
        assert [o["value"] for o in res["ask"]["options"]] == ["si", "no"]
        assert res["ask"]["question_id"].startswith("ask_")

    def test_choice_needs_two_options(self):
        ok, msg = user_questions.build_question("Quale?", "single_choice", ["solo una"])
        assert not ok and "2 options" in msg

    def test_multi_choice_keeps_labels_and_other(self):
        ok, res = user_questions.build_question("Quali tengo?", "multi_choice", ["A", "B", "C"], allow_other=True)
        assert ok and [o["label"] for o in res["ask"]["options"]] == ["A", "B", "C"]
        assert res["ask"]["allow_other"] is True

    def test_free_text_allows_other(self):
        ok, res = user_questions.build_question("Come lo chiamo?", "free_text")
        assert ok and res["ask"]["allow_other"] and res["ask"]["options"] == []

    def test_unknown_kind_falls_back_to_confirm(self):
        ok, res = user_questions.build_question("Procedo?", "weird")
        assert ok and res["ask"]["kind"] == "confirm"

    def test_empty_prompt_rejected(self):
        assert user_questions.build_question("")[0] is False


@pytest.mark.unit
class TestResumeMessage:
    def test_confirm_answer_readable(self):
        msg = user_questions.resume_message({"prompt": "Procedo?", "kind": "confirm"}, "si")
        assert msg == "Risposta alla tua domanda «Procedo?»: Sì"

    def test_multi_choice_joined(self):
        msg = user_questions.resume_message({"prompt": "Quali?", "kind": "multi_choice"}, "A\nC")
        assert msg.endswith(": A, C")

    def test_empty_answer_asks_for_safest_default(self):
        assert "decidi tu" in user_questions.resume_message({"prompt": "X?", "kind": "free_text"}, "")


@pytest.mark.unit
def test_agent_loop_stops_on_ask_user():
    other = ToolDefinition(name="calendar_delete", description="d", parameters={"type": "object", "properties": {}},
                           handler=MagicMock(return_value=(True, {"ok": True})))
    call = '<tool_call>' + json.dumps({"name": "ask_user", "params": {
        "prompt": "Cancello anche quello di venerdì?", "kind": "confirm"}}) + '</tool_call>'
    later = '<tool_call>' + json.dumps({"name": "calendar_delete", "params": {}}) + '</tool_call>'
    seq = iter([call, later, "fatto"])
    answer, tokens, log = run_agent_loop(user_message="cancella", history_text="", preference_facts=[],
                                         tools=[_ask_tool(), other], ask_fn=lambda p: next(seq))
    assert answer == "Cancello anche quello di venerdì?"
    assert tokens == [answer]
    assert log[0]["ask"]["kind"] == "confirm"
    other.handler.assert_not_called()  # nothing after the question runs in this turn


@pytest.mark.unit
def test_question_frame_carries_allow_other():
    frame = json.loads(stream_emitter.emit_question("q1", "Scegli", "", kind="single_choice",
                                                   options=[{"value": "a", "label": "a"}], allow_other=True))
    assert frame["allow_other"] is True and frame["kind"] == "single_choice"


@pytest.mark.unit
def test_open_for_session_skips_resolved_and_expired():
    hub = MagicMock()
    hub.route_to_service.return_value = (True, {"rows": [
        {"data": {"question_id": "ask_1", "resolved": False, "expires_at": "2999-01-01T00:00:00+00:00"}},
        {"data": {"question_id": "ask_2", "resolved": True}},
        {"data": {"question_id": "ask_3", "resolved": False, "expires_at": "2000-01-01T00:00:00+00:00"}},
    ]})
    assert [q["question_id"] for q in user_questions.open_for_session(hub, "s1")] == ["ask_1"]


@pytest.mark.unit
class TestQueuedChat:
    def test_many_messages_numbered_with_time(self):
        from datetime import datetime, timezone
        from core.services import queued_chat
        now = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
        text = queued_chat.compose([{"text": "che tempo fa?", "written_at": "2026-10-21T09:00:00+00:00"},
                                    {"text": "lascia stare", "written_at": "2026-10-22T09:50:00+00:00"}], now)
        assert text.startswith("Messaggi che ti ho scritto")
        assert "1. (" in text and "h fa) che tempo fa?" in text and "10 min fa) lascia stare" in text

    def test_single_message_kept_plain(self):
        from core.services import queued_chat
        assert queued_chat.compose([{"text": "ciao", "written_at": "2026-10-22T09:50:00+00:00"}]) == "ciao"

    def test_instructions_let_the_model_decide(self):
        from core.services import queued_chat
        many = queued_chat.instructions([{"text": "a"}, {"text": "b"}], "personal")
        assert many.startswith("personal") and "ask_user" in many
        assert "MESSAGGIO IN CODA" in queued_chat.instructions([{"text": "a"}], None)


@pytest.mark.api
def test_chat_endpoint_composes_queued_batch(monkeypatch):
    import main
    seen = {}

    def fake_chat(message, session_id, **kw):
        seen.update(message=message, mode=kw.get("mode"), instructions=kw.get("client_instructions"))
        yield '{"type":"final","reply":"ok"}\n'

    # A fresh engine stub: other modules' tests may leave main.engine as a spec'd or sealed mock.
    from unittest.mock import MagicMock
    engine = MagicMock()
    engine.chat = fake_chat
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "_no_usable_model", lambda: False)
    from fastapi.testclient import TestClient
    res = TestClient(main.app).post("/api/chat", json={"message": "", "session_id": "s1", "client": "telegram",
                                                       "queued": [{"text": "uno"}, {"text": "due"}]})
    assert res.status_code == 200 and "ok" in res.text
    assert "1. uno" in seen["message"] and "2. due" in seen["message"]
    assert seen["mode"] == "thinking" and "ask_user" in (seen["instructions"] or "")


@pytest.mark.api
def test_chat_refused_with_503_when_no_model(monkeypatch):
    """v3 E: no model can answer → 503 like an unreachable Oracle, so the client queues the message."""
    import main
    monkeypatch.setattr(main, "_models_state", lambda: "none")
    monkeypatch.setattr(main, "_no_usable_model", lambda: True)
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    res = client.post("/api/chat", json={"message": "ciao", "session_id": "s1"})
    assert res.status_code == 503 and res.json()["models"] == "none"
    assert client.get("/health").json()["models"] == "none"


@pytest.mark.unit
def test_recent_failure_does_not_refuse_the_chat(monkeypatch):
    """A chain that only failed recently is still tried (a success clears «none»); only no usable step refuses."""
    import main
    from core.services import llm_chains
    monkeypatch.setattr(llm_chains, "models_state", lambda: {"state": "none", "usable_steps": 2, "steps": 2})
    assert main._no_usable_model() is False
    monkeypatch.setattr(llm_chains, "models_state", lambda: {"state": "none", "usable_steps": 0, "steps": 2})
    assert main._no_usable_model() is True

