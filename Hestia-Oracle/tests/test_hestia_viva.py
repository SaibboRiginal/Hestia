"""Hestia viva (docs/work/2026-11-06-hestia-viva): persona, spoken turns, controls gate, awareness lines, reactions.

No LLM, no network: Hub, engine and settings are mocked. Markers: unit, api."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.services import awareness, prompt_config, reaction_marker
from core.services.user_control_service import UserControlService, looks_like_control


def _frames(lines):
    return [json.loads(x) for x in lines if x.strip()]


def _tok(text):
    return json.dumps({"type": "token", "text": text}) + "\n"


def _final(reply):
    return json.dumps({"type": "final", "reply": reply, "domain": "general"}, ensure_ascii=False) + "\n"


# ── F1 persona + spoken ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_persona_is_a_person_short_and_keeps_rules():
    text = prompt_config.analyst_persona_default()
    assert "una persona che vive con l'utente" in text
    assert "LUNGHEZZA: 1-2 frasi" in text and "Mai inventare" in text
    assert "REGOLE:" in text and "11. Mai dire fatto/salvato" in text      # operating rules untouched
    assert "professionale, lucida" not in text


@pytest.mark.unit
def test_voice_contract_forbids_lists_and_markup():
    text = prompt_config.voice_turn_contract()
    assert "1-2 frasi parlate" in text and "elenchi" in text and "markdown" in text


# ── F2 controls gate ───────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("message,expected", [
    ("ciao come stai", False), ("quanto ho speso ieri?", False), ("ho fatto palestra", False),
    ("non mandarmi notifiche di notte", True), ("smetti di chiedermi del meteo", True),
    ("ricordami meno spesso le cose", True), ("dalle 22 silenzio", True), ("basta con i promemoria", True),
])
def test_control_hint(message, expected):
    assert looks_like_control(message) is expected


@pytest.mark.unit
def test_controls_extraction_skips_the_llm_without_a_hint():
    scribe = MagicMock()
    svc = UserControlService(MagicMock(), scribe)
    with patch.object(svc, "_ask") as ask:
        assert svc.extract_and_save_controls("che tempo fa domani?") == []
        ask.assert_not_called()
        ask.return_value = "NONE"
        assert svc.extract_and_save_controls("non scrivermi di notte") == []
        ask.assert_called_once()


# ── F3 awareness ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_awareness_lines_from_three_sources():
    now = datetime.now(timezone.utc)
    payloads = {
        "psyche": {"summary": {"mood_word": "giù", "energy": 2, "stress": 4, "causes": ["lavoro"]}},
        "hermes": {"items": [{"title": "Allenamento di oggi", "created_at": now.isoformat()},
                             {"title": "Vecchia", "created_at": (now - timedelta(days=2)).isoformat()}]},
        "metis": {"items": [{"client": "webui", "kind": "page", "ref": "spese", "label": "Spese",
                             "at": now.isoformat()}]},
    }
    lines = awareness.build_lines(lambda service, path, query: payloads[service], limit=3)
    assert len(lines) == 3 and all(line.startswith(awareness.PREFIX) for line in lines)
    assert "giù, energia 2/5, stress 4/5, per lavoro" in lines[0]
    assert "«Allenamento di oggi»" in lines[1] and "Vecchia" not in lines[1]
    assert "Spese (sito" in lines[2]


@pytest.mark.unit
def test_awareness_source_down_or_zero_items_leaves_lines_out():
    def fetch(service, path, query):
        if service == "psyche":
            raise TimeoutError("slow")
        return None
    assert awareness.build_lines(fetch, limit=3) == []
    assert awareness.build_lines(lambda *a: {"summary": {"mood_word": "bene"}}, limit=0) == []


@pytest.mark.unit
def test_awareness_is_cached_per_limit():
    awareness.forget()
    hub = MagicMock()
    hub.route_to_service.return_value = (True, {"summary": {"mood_word": "bene"}, "items": []})
    first = awareness.lines_for_turn(hub, 3)
    calls = hub.route_to_service.call_count
    assert awareness.lines_for_turn(hub, 3) == first and hub.route_to_service.call_count == calls
    awareness.forget()


# ── F4 reactions ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_marker_becomes_reaction_frame_and_leaves_the_text():
    out = _frames(reaction_marker.filter_stream(iter([_tok("[[r:"), _tok("👍]] Fatto"), _tok(", a domani."),
                                                       _final("[[r:👍]] Fatto, a domani.")])))
    assert out[0] == {"type": "reaction", "emoji": "👍"}
    assert "".join(f["text"] for f in out if f["type"] == "token") == "Fatto, a domani."
    final = out[-1]
    assert final["reply"] == "Fatto, a domani." and final["reaction"] == "👍" and "reaction_only" not in final
    assert sum(1 for f in out if f["type"] == "reaction") == 1


@pytest.mark.unit
def test_reaction_alone_marks_final():
    out = _frames(reaction_marker.filter_stream(iter([_tok("[[r:❤]]"), _final("[[r:❤]]")])))
    assert out[0]["type"] == "reaction" and out[-1]["reaction_only"] is True and out[-1]["reply"] == ""


@pytest.mark.unit
def test_no_marker_streams_unchanged_and_fast():
    lines = [json.dumps({"type": "status", "content": "..."}) + "\n", _tok("Ciao"), _tok(" Marco"), _final("Ciao Marco")]
    out = _frames(reaction_marker.filter_stream(iter(lines)))
    assert [f["type"] for f in out] == ["status", "token", "token", "final"]
    assert out[-1]["reply"] == "Ciao Marco"


@pytest.mark.unit
def test_strip_helper():
    assert reaction_marker.strip("[[r:😂]] ahah") == ("😂", "ahah")
    assert reaction_marker.strip("[nota] testo") == ("", "[nota] testo")


@pytest.fixture(scope="module")
def client():
    with patch("core.oracle_engine.OracleEngine", return_value=MagicMock()), patch("requests.post"):
        import main  # noqa: PLC0415
        yield main, TestClient(main.app)


@pytest.mark.api
def test_owner_reaction_saves_one_history_line(client):
    main, http = client
    main.engine._hub.post.reset_mock()
    res = http.post("/api/chat/reaction", json={"session_id": "s1", "emoji": "👍", "text": "Domani piove."})
    assert res.status_code == 200
    body = main.engine._hub.post.call_args[0][1]
    assert body["role"] == "user" and body["session_id"] == "s1"
    assert body["content"] == "(reazione 👍 al tuo messaggio «Domani piove.»)"
    res = http.post("/api/chat/reaction", json={"session_id": "s1", "emoji": ""})
    assert "tolto la reazione" in res.json()["line"]


@pytest.mark.api
def test_spoken_turn_and_reaction_line_reach_the_engine(client):
    main, http = client
    main.engine.chat.reset_mock()
    main.engine.chat.return_value = iter([_final("Ok.")])
    with patch.object(main, "_no_usable_model", return_value=False), \
            patch.object(main, "_mark_user_activity", return_value=None):
        res = http.post("/api/chat", json={"message": "ciao", "session_id": "s2", "client": "webui", "spoken": True})
    assert res.status_code == 200
    instructions = main.engine.chat.call_args.kwargs["client_instructions"]
    assert "TURNO A VOCE" in instructions and "[[r:EMOJI]]" in instructions


# ── v1.3 identity: never «il motore di ragionamento di Hestia» (Marko's real run 2026-11-07) ──────────────────

@pytest.mark.unit
def test_agent_loop_preambles_speak_as_hestia():
    for key in ("agent_loop_system_preamble", "agent_loop_system_preamble_compact"):
        text = prompt_config.prompt(key, tools_json="[]", tools_list="")
        assert "motore" not in text and text.startswith("Sei Hestia, la persona descritta sopra")
    assert "1-2 frasi" in prompt_config.prompt("quick_chat_static_instruction")
    assert "NOME: Hestia" in prompt_config.analyst_persona_default()


@pytest.mark.unit
def test_ollama_native_tools_keep_the_persona_as_system(monkeypatch):
    from agents.universal_agent import UniversalAgent
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    agent = UniversalAgent(role_prompt="Sei Hestia. PERSONA", provider="ollama", model_name="m", thinking=False)
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": "Bene, tu?"}}
    with patch("agents.universal_agent.requests.post", return_value=resp) as post:
        agent._ask_with_tools_ollama_native("ciao", [{"name": "t", "description": "d", "parameters": {}}])
    system = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert system.startswith("Sei Hestia. PERSONA") and "engine" not in system and "STRUMENTI" in system
