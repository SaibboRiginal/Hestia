"""One prompt for every situation (docs/work/2026-11-12-prompt-ogni-situazione).

The same building blocks reach the model whatever the mode (Rapida, auto, Pensata, CoT), the path (small talk
shortcut, agent loop, external agent, another AI, a text a module asks for) and the client: who the assistant is,
how it talks and the language rule exactly once; tool rules only with tools; no client format inside Oracle.
"""
import json
from unittest.mock import MagicMock

import pytest

from core import agent_loop
from core.oracle_engine import OracleEngine, external_agent_system_prompt
from core.services import assistant_profile, llm_chains, prompt_config
from test_oracle_engine_core import _collect_ndjson_lines, engine  # noqa: F401  (shared mocked engine)

STYLE_MARK, LANGUAGE_MARK, TOOLS_MARK = "STYLE (mandatory):", "LANGUAGE:", "TOOL RULES:"
# Italian words that only ever appeared as instructions to the model (quoted examples of what the owner or a bot
# writes are fine): a hit means a hidden text slipped back into Italian.
ITALIAN_INSTRUCTIONS = ("Sei ", "Rispondi", "Scrivi ", "obbligatorio", "VIETATO", "Mai inventare", "REGOLE", "l'utente")


@pytest.mark.unit
def test_system_identity_has_each_block_once_and_no_client_format():
    text = prompt_config.system_identity()
    assert text.startswith("You are Hestia")
    for mark in (STYLE_MARK, LANGUAGE_MARK):
        assert text.count(mark) == 1
    assert TOOLS_MARK not in text                      # tool rules travel with the tools
    for word in ("Telegram", "HTML", "Markdown", "<b>"):
        assert word not in text                        # Oracle does not know the client


@pytest.mark.unit
def test_every_hidden_text_is_english_and_names_nobody():
    for key, template in prompt_config._DEFAULT_PROMPTS.items():
        for word in ITALIAN_INSTRUCTIONS:
            assert word not in template, f"{key}: Italian instruction «{word}»"
        if key != "client_contract_claude":            # the product keeps its name there (tools «hestia»)
            assert "Hestia" not in template, f"{key}: fixed name instead of {{assistant}}"


@pytest.mark.unit
def test_language_rule_follows_the_owner_last_message():
    rule = prompt_config.prompt("language_rule")
    assert "LATEST message" in rule and "in English" in rule


def _loop_prompts(**kwargs):
    seen, trace = [], {}

    def _ask_tools(prompt, manifest):
        seen.append(prompt)
        return {"tool_call": None, "tool_calls": [], "text": "Ok."}
    agent_loop.run_agent_loop(user_message="spegni le notifiche", history_text="", preference_facts=["L'utente ama il tè"],
                              tools=[], ask_fn=lambda p: "Ok.", ask_tools_fn=_ask_tools, trace_out=trace, **kwargs)
    return seen, trace


@pytest.mark.unit
def test_agent_loop_adds_tool_rules_once_and_never_the_style_again():
    seen, trace = _loop_prompts(conversation_style=prompt_config.conversation_style_contract(), action_intent=True)
    system = trace["system"]
    assert system.count(TOOLS_MARK) == 1 and STYLE_MARK not in system      # style = system prompt, not here
    assert "OWNER PREFERENCES" in system and "L'utente ama il tè" in system
    # One order, not two opposite ones: «no tool → propose developing it», never «explain it cannot be done».
    assert "cannot be performed" not in seen[0] and "TOOL RULES 3" in seen[0]


@pytest.mark.unit
def test_small_talk_shortcut_knows_the_owner_and_adds_nothing_twice():
    eng = OracleEngine.__new__(OracleEngine)
    eng._ask_analyst = MagicMock(return_value="Bene, tu?")
    eng._quick_answer("come va?", "", "FORMAT: x", None, preference_facts=["L'utente lavora a Udine"])
    prompt = eng._ask_analyst.call_args[0][0]
    assert "OWNER PREFERENCES" in prompt and "L'utente lavora a Udine" in prompt
    assert STYLE_MARK not in prompt and "FORMAT: x" in prompt and "USER: come va?" in prompt


@pytest.mark.unit
@pytest.mark.parametrize("mode,thinking", [("quick", False), ("auto", True), ("thinking", True), ("cot", "deep")])
def test_every_mode_gets_the_same_prompt_and_differs_only_in_thinking(engine, mode, thinking):  # noqa: F811
    seen = []

    def _tools(prompt, manifest, agent_override=None, thinking=False):
        seen.append((prompt, thinking))
        return {"tool_call": None, "tool_calls": [], "text": "Fatto."}
    engine._ask_analyst_with_tools = _tools
    lines = _collect_ndjson_lines(engine.chat("Che impegni ho domani?", f"s-{mode}", mode=mode,
                                              client_instructions="FORMAT: plain"))
    assert any(line.get("type") == "final" for line in lines)
    prompt, level = seen[0]
    assert level == thinking
    assert prompt.count(TOOLS_MARK) == 1 and "FORMAT: plain" in prompt and STYLE_MARK not in prompt
    assert ("CHAIN OF THOUGHT" in prompt) == (mode == "cot")


@pytest.mark.unit
def test_external_agent_and_other_ai_use_the_same_identity():
    system = external_agent_system_prompt(["L'utente ama il tè"], "FORMAT: x")
    assert system.startswith(prompt_config.system_identity()) and system.count(TOOLS_MARK) == 1
    profile = assistant_profile.build(None)["text"]
    assert profile.count(STYLE_MARK) == 1 and profile.count(LANGUAGE_MARK) == 1


@pytest.mark.unit
def test_formatter_carries_no_client_format(engine):  # noqa: F811
    engine._ask_analyst = MagicMock(return_value="ok")
    engine.format_payload("alert:scout", {"title": "Casa"}, client_instructions="FORMAT: Telegram HTML")
    prompt = engine._ask_analyst.call_args[0][0]
    assert prompt.count("Telegram") == 1 and STYLE_MARK not in prompt      # only what the caller sent


@pytest.mark.unit
def test_module_text_for_the_owner_speaks_as_the_assistant():
    plain, voice = llm_chains.agent_for("athena.recap"), llm_chains.agent_for("athena.recap", voice=True)
    assert plain.role_prompt == "" and voice is not plain
    assert voice.role_prompt == prompt_config.system_identity()
    assert "writing to the owner yourself" in prompt_config.prompt("module_voice_instruction")


@pytest.mark.api
def test_generate_voice_flag_reaches_the_chain(monkeypatch):
    import main
    from fastapi.testclient import TestClient
    calls = {}

    class _Agent:
        def ask(self, prompt):
            calls["prompt"] = prompt
            return "Fatto."

    def _agent_for(use_case, voice=False):
        calls["voice"] = voice
        return _Agent()
    monkeypatch.setattr(llm_chains, "agent_for", _agent_for)
    monkeypatch.setattr("core.services.external_agent.mode_for", lambda uc: "interna")
    res = TestClient(main.app).post("/api/llm/generate", json={"prompt": "FACTS: x", "use_case": "athena.recap",
                                                               "voice": True})
    assert res.status_code == 200 and calls["voice"] is True
    assert calls["prompt"].startswith("You are writing to the owner yourself") and calls["prompt"].endswith("FACTS: x")
    TestClient(main.app).post("/api/llm/generate", json={"prompt": "x"})
    assert calls["voice"] is False and calls["prompt"] == "x"
