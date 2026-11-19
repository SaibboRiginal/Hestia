"""Operating mode «agents» (dossier docs/work/2026-11-06-modules-as-agents): module agents inside Oracle."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.agent_loop import ToolDefinition, run_agent_loop
from core.services import llm_chains, module_agents, oracle_settings, stream_emitter
from core.services.turn_guards import TurnGuards

from test_oracle_engine_core import _SAMPLE_COMMANDS, _collect_ndjson_lines, engine  # noqa: F401 (fixture)


def _tool(name, service="", writes=False, handler=None):
    return ToolDefinition(name=name, description=name, parameters={"type": "object", "properties": {}},
                          handler=handler or (lambda **kw: (True, {"items": [1]})), writes=writes, service=service)


class FakeChain:
    """ChainAgent stand-in: scripted ask_with_tools answers."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.model_name, self.provider = "fake-model", "fake"

    def ask_with_tools(self, prompt, tools, thinking=None):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else {"tool_call": None, "text": "done"}

    def ask(self, prompt, thinking=None):
        self.prompts.append(prompt)
        return "done"


def _run(chains: dict, **kw):
    lines: list[str] = []
    nested: list[dict] = []
    run = module_agents.AgentRun(
        run_loop=run_agent_loop, chain_for=lambda uc: chains[uc], emit=lines.append,
        emit_frame=stream_emitter.emit_agent, owner_message=kw.pop("owner", "quanto ho speso?"),
        history_text="user: ciao\nassistant: ciao!", preference_facts=[], board=module_agents.TurnBoard(),
        nested_log=nested, **kw)
    return run, lines, nested


@pytest.mark.unit
class TestGrouping:
    def test_module_tools_go_to_their_agent_oracle_tools_stay(self):
        tools = [_tool("memory.save"), _tool("finance_add", "plutus"), _tool("finance_search", "plutus"),
                 _tool("gym_log", "hercules"), _tool("routine_create", "chronos"), _tool("ask_user"),
                 _tool("module_manual")]
        guides = {"plutus": {"when": "expenses", "manual": "use finance_add", "title": "Expenses"}}
        main, specs = module_agents.group(tools, guides)
        assert [t.name for t in main] == ["memory.save", "routine_create", "ask_user"]
        assert [(s.module, [t.name for t in s.tools]) for s in specs] == [
            ("hercules", ["gym_log"]), ("plutus", ["finance_add", "finance_search"])]
        plutus = specs[1]
        assert plutus.tool_name == "agent_plutus" and plutus.use_case == "agent.plutus"
        assert plutus.label == "Expenses" and specs[0].when == "tools of the hercules module"

    def test_history_tail(self):
        assert module_agents.history_tail("a\nb\n\nc\nd", 2) == "c\nd"
        assert module_agents.history_tail("a\nb", 0) == ""

    def test_agent_use_cases_listed_and_follow_general(self):
        _, specs = module_agents.group([_tool("finance_add", "plutus")], {"plutus": {"when": "expenses"}})
        llm_chains.register_agent_usecases(specs)
        row = llm_chains.declared_usecases()["agent.plutus"]
        assert row["chain"] == "" and row["module"] == "plutus"


@pytest.mark.unit
class TestAgentRun:
    def test_agent_uses_its_tools_posts_board_and_frames(self):
        calls = []
        spec = module_agents.AgentSpec("plutus", "expenses", manual="RULE-X",
                                       tools=[_tool("finance_search", "plutus",
                                                    handler=lambda **kw: (calls.append(kw) or True, {"total": 42}))])
        chain = FakeChain([{"tool_call": {"name": "finance_search", "params": {"month": "11"}}, "text": ""},
                           {"tool_call": None, "text": "Hai speso 42 euro."}])
        run, lines, nested = _run({"agent.plutus": chain})
        ok, out = run.run(spec, "spese di novembre")
        assert ok and out["answer"] == "Hai speso 42 euro."
        assert calls == [{"month": "11"}]
        assert "RULE-X" in chain.prompts[0] and "OWNER'S OWN WORDS: quanto ho speso?" in chain.prompts[0]
        assert [e["tool"] for e in nested] == ["finance_search"] and nested[0]["agent"] == "plutus"
        frames = [json.loads(l) for l in lines]
        assert [f["event"] for f in frames] == ["start", "tool", "end"]
        assert frames[0]["model"] == "fake-model" and frames[1]["tool"] == "finance_search"
        assert frames[2]["summary"] == "Hai speso 42 euro." and all(f["type"] == "agent" for f in frames)
        assert "plutus: Hai speso 42 euro." in run.board.text()

    def test_later_agent_reads_the_board(self):
        a = module_agents.AgentSpec("plutus", "expenses", tools=[_tool("finance_search", "plutus")])
        b = module_agents.AgentSpec("hercules", "gym", tools=[_tool("gym_log", "hercules")])
        ca = FakeChain([{"tool_call": None, "text": "Speso 42."}])
        cb = FakeChain([{"tool_call": None, "text": "Allenamento ok."}])
        run, _, _ = _run({"agent.plutus": ca, "agent.hercules": cb})
        run.run(a, "spese")
        run.run(b, "allenamento")
        assert "TURN BOARD" in cb.prompts[0] and "plutus: Speso 42." in cb.prompts[0]
        assert "TURN BOARD" not in ca.prompts[0]

    def test_agent_loop_gets_its_own_models_window(self):
        """Like the chat: the agent's loop budgets and shapes with the window of the model that answers it."""
        seen = {}

        def loop(**kw):
            seen["window"] = kw.get("context_window")
            return "ok", [], []

        spec = module_agents.AgentSpec("plutus", "expenses", tools=[_tool("finance_search", "plutus")])
        chain = FakeChain([])
        chain.provider, chain.model_name = "gemini", "flash"
        run, _, _ = _run({"agent.plutus": chain}, window_for=lambda c: 1_000_000 if c.provider == "gemini" else 0)
        run.run_loop = loop
        assert run.run(spec, "spese")[0] is True and seen["window"] == 1_000_000

    def test_max_agents_per_turn(self):
        spec = module_agents.AgentSpec("plutus", "expenses", tools=[_tool("finance_search", "plutus")])
        run, _, _ = _run({"agent.plutus": FakeChain([])}, max_agents=1)
        assert run.run(spec, "a")[0] is True
        ok, msg = run.run(spec, "b")
        assert ok is False and msg.startswith("LIMIT")

    def test_turn_guards_judge_the_owners_words_not_the_task(self):
        """A question of the owner stays a question even if the main brain writes «add it» in the task."""
        wrote = []
        add = _tool("finance_add", "plutus", writes=True, handler=lambda **kw: (wrote.append(kw) or True, {}))
        TurnGuards("quanto ho speso questo mese?").wrap([add])
        spec = module_agents.AgentSpec("plutus", "expenses", tools=[add])
        chain = FakeChain([{"tool_call": {"name": "finance_add", "params": {"amount": 10}}, "text": ""},
                           {"tool_call": None, "text": "Non ho registrato nulla."}])
        run, _, nested = _run({"agent.plutus": chain})
        run.run(spec, "registra una spesa di 10 euro")
        assert wrote == []
        assert nested[0]["refused"] is True


@pytest.mark.unit
class TestDirectAnswerAndLiveNotes:
    def test_only_call_of_the_turn_answers_directly(self):
        agent = ToolDefinition(name="agent_plutus", description="", parameters={},
                               handler=lambda **kw: (True, {"answer": "Speso 42."}), direct=True)
        ask_tools = MagicMock(side_effect=[{"tool_call": {"name": "agent_plutus", "params": {"task": "x"}},
                                            "text": ""}])
        answer, tokens, log = run_agent_loop("quanto?", "", [], [agent], ask_fn=MagicMock(),
                                             ask_tools_fn=ask_tools, stream_fn=MagicMock())
        assert answer == "Speso 42." and ask_tools.call_count == 1 and len(log) == 1

    def test_live_notes_read_every_step(self):
        seen = []
        ask_tools = MagicMock(side_effect=lambda p, tm: seen.append(p) or {"tool_call": None, "text": "ok"})
        run_agent_loop("q", "", [], [_tool("x")], ask_fn=MagicMock(), ask_tools_fn=ask_tools,
                       live_notes=lambda: "BOARD-LINE")
        assert "BOARD-LINE" in seen[0]


@pytest.mark.unit
class TestSettingAndFrames:
    def test_operating_mode_default_classic_unknown_classic(self):
        with patch.object(oracle_settings.settings, "get", return_value=None):
            assert oracle_settings.operating_mode() == "classic"
        with patch.object(oracle_settings.settings, "get", return_value="weird"):
            assert oracle_settings.operating_mode() == "classic"
        with patch.object(oracle_settings.settings, "get", return_value="agents"):
            assert oracle_settings.operating_mode() == "agents"

    def test_final_carries_operating_mode_only_when_set(self):
        assert "operating_mode" not in json.loads(stream_emitter.emit_final("x"))
        assert json.loads(stream_emitter.emit_final("x", operating_mode="agents"))["operating_mode"] == "agents"


@pytest.mark.unit
class TestEngineAgentsMode:
    def _chat(self, engine, message, agent_chain, main_replies):
        engine._hub.get_commands = MagicMock(return_value=_SAMPLE_COMMANDS)
        engine._agents.generic.ask_with_tools.side_effect = main_replies
        with patch.object(oracle_settings, "operating_mode", return_value="agents"), \
                patch.object(llm_chains, "agent_for", return_value=agent_chain):
            return _collect_ndjson_lines(engine.chat(message, "s-agents", client="webui"))

    def test_small_talk_is_one_call_without_classifier(self, engine):
        lines = self._chat(engine, "ciao!", FakeChain([]), [{"tool_call": None, "text": "Ciao Marko!"}])
        engine._agents.generic.ask.assert_not_called()          # no classifier
        assert engine._agents.generic.ask_with_tools.call_count == 1
        final = [l for l in lines if l["type"] == "final"][0]
        assert final["reply"] == "Ciao Marko!" and final["operating_mode"] == "agents"

    def test_main_brain_sees_agents_not_module_tools_and_agent_answers_directly(self, engine):
        seen_tools = []
        replies = [{"tool_call": {"name": "agent_chronos", "params": {"task": "agenda di oggi"}}, "text": ""}]

        def _main(prompt, tools, thinking=None):
            seen_tools.append([t["name"] for t in tools])
            return replies.pop(0)
        engine._hub.get_commands = MagicMock(return_value=_SAMPLE_COMMANDS)
        engine._agents.generic.ask_with_tools.side_effect = _main
        chain = FakeChain([{"tool_call": {"name": "agenda", "params": {}}, "text": ""},
                           {"tool_call": None, "text": "Oggi hai la riunione."}])
        with patch.object(oracle_settings, "operating_mode", return_value="agents"), \
                patch.object(llm_chains, "agent_for", return_value=chain):
            lines = _collect_ndjson_lines(engine.chat("cosa ho oggi?", "s-agents", client="webui"))
        names = seen_tools[0]
        assert "agent_chronos" in names and "agent_scout" in names
        assert not {"agenda", "create_event", "scout_listings", "module_manual"} & set(names)
        agent_frames = [l for l in lines if l["type"] == "agent"]
        assert [f["event"] for f in agent_frames] == ["start", "tool", "end"]
        types = [l["type"] for l in lines]
        assert types.index("agent") < types.index("final")
        final = [l for l in lines if l["type"] == "final"][0]
        assert final["reply"] == "Oggi hai la riunione."
        assert engine._agents.generic.ask_with_tools.call_count == 1   # direct answer: no extra main call

    def test_agent_writes_reach_changes_and_notices(self, engine):
        main = [{"tool_call": {"name": "agent_chronos", "params": {"task": "crea evento dentista domani"}},
                 "text": ""}]
        chain = FakeChain([{"tool_call": {"name": "create_event",
                                          "params": {"title": "Dentista", "start_datetime": "2026-11-18T10:00"}},
                            "text": ""},
                           {"tool_call": None, "text": "Fatto, dentista domani alle 10."}])
        lines = self._chat(engine, "crea un evento dentista domani alle 10", chain, main)
        notices = [l for l in lines if l["type"] == "notice" and l.get("kind", "").startswith("action.")]
        assert notices and notices[0]["kind"] == "action.done"

    def test_classic_mode_unchanged(self, engine):
        engine._agents.generic.ask.side_effect = [json.dumps({
            "mode": "quick_chat", "domain": None, "confidence": 0.9, "domains": ["general"], "filters": {},
            "filters_gt": {}, "filters_lt": {}, "sort_by": None, "sort_order": "desc", "action_intent": False}),
            "Ciao!"]
        lines = _collect_ndjson_lines(engine.chat("ciao", "s-classic"))
        final = [l for l in lines if l["type"] == "final"][0]
        assert "operating_mode" not in final and not [l for l in lines if l["type"] == "agent"]
