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
    assert "una persona che vive con lui" in text and "l'assistente personale di" in text
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


# ── Identity: name, she/he, owner (docs/work/2026-11-12-identita-e-proattivita) ──────────────────────────────

@pytest.fixture
def ident(monkeypatch):
    """Set the personal settings Oracle follows for one test."""
    from core.services import oracle_settings

    def apply(**values):
        for key, value in values.items():
            monkeypatch.setitem(oracle_settings.settings._shared, f"themis.personal.{key}", value)
    return apply


@pytest.mark.unit
def test_identity_defaults_to_hestia_she_and_asks_the_name():
    text = prompt_config.analyst_persona_default()
    assert text.startswith("Sei Hestia, l'assistente personale di chi ti scrive: sua e di nessun altro.")
    assert "amica fidata" in text and "chiediglielo alla prima occasione" in text
    assert "{" not in text.split("REGOLE:")[0]                     # every token rendered


@pytest.mark.unit
def test_identity_follows_the_personal_settings(ident):
    ident(assistant_name="Leo", assistant_gender="lui", owner_name="Marco", owner_call="Marko")
    text = prompt_config.analyst_persona_default()
    assert text.startswith("Sei Leo, l'assistente personale di Marko: suo e di nessun altro.")
    assert "uomo, caldo, sveglio, schietto" in text and "amico fidato" in text and "Hestia stessa" in text
    assert "Si chiama Marko (nome: Marco)" in text and "donna" not in text
    assert prompt_config.prompt("quick_chat_static_instruction").startswith("Sei Leo, la persona descritta sopra")
    assert prompt_config.prompt("agent_loop_system_preamble_compact", tools_list="- t").startswith("Sei Leo,")
    assert "Spero di esserti stato utile" in prompt_config.conversation_style_contract()


@pytest.mark.unit
def test_chain_agent_reads_the_persona_at_every_call(ident):
    from core.services.agent_factory import AgentFactory
    agent = AgentFactory.create().generic
    assert agent.role_prompt.startswith("Sei Hestia,")
    ident(assistant_name="Leo")
    assert agent.role_prompt.startswith("Sei Leo,")


@pytest.mark.unit
def test_style_lets_her_chat_and_bans_bot_phrases():
    text = prompt_config.conversation_style_contract()
    assert "UNA domanda vera su di lui" in text and "Compito o dato: vai al punto" in text
    assert "saluto di una parola" not in text and "sono qui" in text


# ── She writes first («parla con te», docs/work/2026-11-12-identita-e-proattivita) ───────────────────────────

@pytest.mark.unit
def test_opener_prompt_carries_reasons_memories_and_what_she_already_wrote():
    from core.services import opener
    memory = MagicMock()
    memory.recall.return_value = (True, [{"fact": "L'utente lavora come sviluppatore"}])
    asked = []
    out = opener.write(lambda p: asked.append(p) or "Com'è andata poi la riunione di stamattina?",
                       reasons=["Umore di oggi: giù, per lavoro"], avoid=["Hai mangiato?"], memory_service=memory,
                       awareness=["[Contesto] x"])
    assert out == {"text": "Com'è andata poi la riunione di stamattina?"}
    prompt = asked[0]
    assert "ORA SCRIVI TU PER PRIMA" in prompt and "- Umore di oggi: giù, per lavoro" in prompt
    assert "- L'utente lavora come sviluppatore" in prompt and "- Hai mangiato?" in prompt and "persone care" in prompt


@pytest.mark.unit
@pytest.mark.parametrize("answer", ["NIENTE", "niente.", "", "NIENTE: è tardi"])
def test_opener_nothing_to_say_sends_nothing(answer):
    from core.services import opener
    assert opener.write(lambda p: answer, reasons=[], avoid=[]) == {"text": "", "skip": "nothing_to_say"}


@pytest.mark.unit
def test_opener_drops_a_reaction_marker_and_quotes():
    from core.services import opener
    assert opener.clean('[[r:👋]] «Come stai oggi?»') == "Come stai oggi?"


@pytest.mark.unit
def test_awareness_talk_line_is_whole_and_not_repeated_as_notification():
    now = datetime.now(timezone.utc).isoformat()
    payload = {"items": [{"title": "", "message": "Com'è andata la riunione?", "kind": "athena.talk", "created_at": now},
                         {"title": "Allenamento", "message": "x", "kind": "", "created_at": now}]}
    line = awareness.talk_line(payload)
    assert "Oggi gli hai scritto tu per prima" in line and "«Com'è andata la riunione?»" in line
    assert "riunione" not in awareness.notifications_line(payload, 3)


@pytest.mark.api
def test_opener_endpoint_writes_or_stays_silent(client):
    main, http = client
    main.engine._memory_service.recall.return_value = (True, [])
    main.engine._current_datetime_context.return_value = "martedì sera"
    with patch.object(main, "_no_usable_model", return_value=False), \
            patch.object(main, "_awareness_lines", return_value=[]):
        main.engine._ask_analyst.return_value = "Hai poi finito quel libro?"
        res = http.post("/api/chat/opener", json={"reasons": ["nessuno"], "avoid": []})
        assert res.status_code == 200 and res.json() == {"text": "Hai poi finito quel libro?"}
        main.engine._ask_analyst.return_value = "NIENTE"
        assert http.post("/api/chat/opener", json={}).json()["text"] == ""
    with patch.object(main, "_no_usable_model", return_value=True):
        assert http.post("/api/chat/opener", json={}).status_code == 503
