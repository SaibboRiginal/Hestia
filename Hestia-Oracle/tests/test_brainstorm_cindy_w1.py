"""Wave 1 of docs/work/2026-10-24-tutto-brainstorm-cindy: loop guard, no replay, origin, goal, changes,
components in answers, llama-server slots, vision bridge."""
from __future__ import annotations

import json

import pytest

from core.agent_loop import ToolDefinition, run_agent_loop
from core.services import conversation_goal, llm_chains, stream_emitter
from core.services.loop_guard import LoopGuard, fingerprint
from hestia_common import origin as origin_mod
from hestia_common import ui_blocks

pytestmark = pytest.mark.unit


def _tool(name, result=(True, {"ok": 1}), writes=False, method="GET"):
    calls = []

    def handler(**kw):
        calls.append(kw)
        return result
    return ToolDefinition(name=name, description=name, parameters={"type": "object", "properties": {}},
                          handler=handler, writes=writes, method=method), calls


def _xml(name, params=None):
    return f'<tool_call>{json.dumps({"name": name, "params": params or {}})}</tool_call>'


# ── Cindy 1: loop guard ──────────────────────────────────────────────────────
class TestLoopGuard:
    def test_same_call_four_times_stops(self):
        g = LoopGuard(repeat=4, window=12, wait_seconds=30)
        assert not any(g.add("a", {"x": 1}, at=i) for i in range(3))
        assert g.add("a", {"x": 1}, at=3) and g.reason == "ripetizione"

    def test_real_wait_is_not_a_loop(self):
        g = LoopGuard(repeat=3, window=12, wait_seconds=30)
        assert not any(g.add("status", {}, at=i * 60) for i in range(6))

    def test_ping_pong_and_rotation(self):
        g = LoopGuard(repeat=9, window=12)
        hits = [g.add(n, {}, at=i) for i, n in enumerate("ababab")]
        assert hits[-1] and g.reason == "ping-pong"
        r = LoopGuard(repeat=9, window=16)
        hits = [r.add(n, {}, at=i) for i, n in enumerate("abcabcabc")]
        assert hits[-1] and r.reason == "giro"

    def test_checker_says_waiting(self):
        g = LoopGuard(repeat=2, window=12, checker=lambda recent: "aspetta", max_checks=3)
        assert not g.add("a", {}, at=0) and not g.add("a", {}, at=1)
        assert g.checks == 1

    def test_fingerprint_ignores_key_order(self):
        assert fingerprint("t", {"a": 1, "b": 2}) == fingerprint("t", {"b": 2, "a": 1})

    def test_agent_loop_stops_repeating_and_answers(self, monkeypatch):
        from core.services import oracle_settings
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.MAX_TURNS, 20)
        tool, calls = _tool("spin")
        prompts = []

        def ask(prompt):
            prompts.append(prompt)
            return "Risposta con quello che ho." if "stai ripetendo" in prompt else _xml("spin", {"q": 1})
        answer, _, log = run_agent_loop(user_message="x", history_text="", preference_facts=[], tools=[tool],
                                        ask_fn=ask)
        assert len(calls) == 4 and answer == "Risposta con quello che ho."


# ── Cindy 2: no replay after a failed external attempt ───────────────────────
def test_prior_actions_are_in_the_scratchpad():
    tool, calls = _tool("finance_add", writes=True, method="POST")
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return "Fatto."
    run_agent_loop(user_message="spesa", history_text="", preference_facts=[], tools=[tool], ask_fn=ask,
                   prior_actions=[{"tool": "finance_add", "ok": True, "result_preview": "saved id=1"}])
    assert "GIÀ FATTO" in seen[0] and "finance_add" in seen[0] and not calls


def test_agent_error_carries_the_log():
    from core.services.external_agent import AgentError
    err = AgentError("boom", log=[{"tool": "x", "ok": True}])
    assert err.log == [{"tool": "x", "ok": True}]


# ── Cindy 6: origin and turn authority ───────────────────────────────────────
class TestOrigin:
    def test_parse(self):
        assert origin_mod.parse({}, "telegram")["level"] == "utente"
        assert origin_mod.parse({}, "")["level"] == "autonomo"
        o = origin_mod.parse({"x-hestia-origin": "routine:lunedi", "X-Hestia-Origin-Label": "Annunci"}, "")
        assert (o["level"], o["ref"], o["label"]) == ("routine", "lunedi", "Annunci")
        assert origin_mod.parse({"X-Hestia-Origin": "esterno:Claude"}, "")["level"] == "utente"

    def test_gate(self):
        from core.oracle_engine import OracleEngine
        write, wcalls = _tool("agenda_create", writes=True, method="POST")
        delete, dcalls = _tool("agenda_delete", writes=True, method="DELETE")
        propose, pcalls = _tool("settings_propose", writes=True, method="POST")
        tools = [write, delete, propose]
        OracleEngine._apply_origin_gate(tools, {"level": "autonomo", "kind": "autonomo"})
        assert tools[0].handler()[0] is False and tools[1].handler()[0] is False
        assert tools[2].handler()[0] is True
        write2, _ = _tool("agenda_create", writes=True, method="POST")
        delete2, _ = _tool("agenda_delete", writes=True, method="DELETE")
        OracleEngine._apply_origin_gate([write2, delete2], {"level": "routine", "kind": "routine"})
        assert write2.handler()[0] is True and delete2.handler()[0] is False

    def test_prompt_line_and_final(self):
        assert origin_mod.prompt_line({"level": "utente", "kind": "utente"}) == ""
        assert "routine" in origin_mod.prompt_line({"level": "routine", "kind": "routine", "ref": "r"})
        line = json.loads(stream_emitter.emit_final("ok", origin={"kind": "routine", "level": "routine",
                                                                  "label": "Da una tua routine"}))
        assert line["origin"]["label"] == "Da una tua routine"


# ── Cindy 23: goal ───────────────────────────────────────────────────────────
def test_goal_prefix_and_stop():
    assert conversation_goal.parse_prefix("obiettivo: sistema le spese") == "sistema le spese"
    assert conversation_goal.parse_prefix("ciao") == ""
    assert conversation_goal.is_stop("ferma l'obiettivo")
    assert not conversation_goal.is_stop("ferma la musica")


def test_goal_storage_round_trip():
    class Hub:
        rows = []

        def route_to_service(self, svc, path, method, body=None, query=None, timeout=0):
            if method == "PUT":
                self.rows.extend(body["rows"])
                return True, {}
            return True, {"rows": [r for r in self.rows if r["ref_id"] == query["ref_id"]]}
    hub = Hub()
    conversation_goal._cache.clear()
    g = conversation_goal.set_goal(hub, "s1", "fare X")
    assert conversation_goal.active(hub, "s1")["id"] == g["id"]
    conversation_goal.end(hub, "s1", "raggiunto", "ok")
    assert conversation_goal.active(hub, "s1") is None
    assert "fare X" in conversation_goal.continuation_message(g)


# ── Cindy 13: changes with undo ──────────────────────────────────────────────
def test_changes_from_log():
    log = [{"tool": "finance_add", "ok": True, "writes": True, "title": "Registra spesa", "params": {"amount": 3},
            "undo": {"tool": "finance_delete", "args": {"id": "t1"}}},
           {"tool": "finance_update", "ok": True, "writes": True, "params": {"id": "t2"}, "undo": "finance_restore"},
           {"tool": "finance_search", "ok": True, "writes": False},
           {"tool": "x", "ok": False, "writes": True}]
    items = stream_emitter.changes_from_log(log)
    assert [i["tool"] for i in items] == ["finance_add", "finance_update"]
    assert items[0]["undo"] == {"tool": "finance_delete", "args": {"id": "t1"}, "label": "Annulla"}
    assert items[1]["undo"]["args"] == {"id": "t2"}
    frame = json.loads(stream_emitter.emit_changes(items, "s"))
    assert frame["type"] == "changes" and len(frame["items"]) == 2


# ── Cindy 9: components ──────────────────────────────────────────────────────
def test_ui_blocks_segments_and_text():
    answer = ("Ecco:\n```hestia-ui\n{\"c\":\"stat\",\"label\":\"Speso\",\"value\":\"12 €\",\"tone\":\"warning\"}\n"
              "{\"c\":\"table\",\"cols\":[\"A\",\"B\"],\"rows\":[[1,2]]}\n{\"c\":\"bogus\"}\nnot json\n"
              "{\"c\":\"button\",\"label\":\"Dettagli\",\"send\":\"mostra i dettagli\"}\n```\nFine.")
    segs = ui_blocks.segments(answer)
    assert [list(s) for s in segs] == [["text"], ["ui"], ["text"]]
    assert [c["c"] for c in segs[1]["ui"]] == ["stat", "table", "button"]
    text = ui_blocks.to_text(answer)
    assert "Speso: 12 €" in text and "A · B" in text and "```" not in text
    assert ui_blocks.buttons(answer)[0]["send"] == "mostra i dettagli"
    assert ui_blocks.to_text("plain") == "plain"


# ── D17: llama-server slots ──────────────────────────────────────────────────
def test_llamacpp_slots_lru_save_restore(monkeypatch):
    from agents.providers import llamacpp
    actions = []

    class _R:
        status_code = 200
        text = ""
    monkeypatch.setattr(llamacpp.requests, "post",
                        lambda url, params=None, json=None, timeout=0: actions.append(
                            (url.rsplit("/", 1)[-1], params["action"], json["filename"])) or _R())
    monkeypatch.setattr(llamacpp, "slot_count", lambda: 3)
    llamacpp._slots.clear()
    llamacpp._save_disabled.clear()
    p = llamacpp.LlamaCppProvider({"base_url": "http://ls:8080/v1"})
    assert p.slot_for("") == 0
    assert p.slot_for("a") == 1 and p.slot_for("b") == 2 and p.slot_for("a") == 1
    actions.clear()
    assert p.slot_for("c") == 2        # b was the least recently used
    assert ("2", "save", "hestia-b.bin") in actions and ("2", "restore", "hestia-c.bin") in actions


def test_llamacpp_is_first_in_default_chain():
    assert llm_chains.DEFAULT_CHAINS["veloce"]["steps"][0]["provider"] == "llamacpp"


# ── Cindy 16: vision bridge ──────────────────────────────────────────────────
def test_vision_bridge_describes_for_text_only_steps(monkeypatch):
    class Agent:
        def __init__(self, name):
            self.name = name
            self.calls = []

        def ask(self, prompt, thinking=None):
            self.calls.append(("ask", prompt))
            return f"{self.name}:{prompt[:40]}"

        def ask_with_attachment(self, b, m, p):
            self.calls.append(("img", p))
            return "descrizione: un gatto"

    text_only = Agent("locale")
    chain = llm_chains.ChainAgent("oracle.test")
    monkeypatch.setattr(chain, "steps", lambda: [(0, {"provider": "ollama", "model": "qwen3:8b"}, text_only)])
    describer = Agent("visore")
    monkeypatch.setattr(llm_chains, "agent_for", lambda uc: describer)
    out = chain.ask_with_attachment(file_bytes=b"x", mime_type="image/png", user_message="cosa vedi?")
    assert text_only.calls and text_only.calls[0][0] == "ask" and "un gatto" in text_only.calls[0][1]
    assert out.startswith("locale:")
