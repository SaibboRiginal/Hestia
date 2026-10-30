"""Real model for the llm_live tests: local Ollama or Gemini (cloud bench, no local GPU).

Provider = ``HESTIA_LIVE_PROVIDER`` (``ollama`` | ``gemini``); unset → ``gemini`` when ``ORACLE_KEY_GEMINI``
is in the environment, else ``ollama``. Models = ``HESTIA_LIVE_MODEL`` (comma list; default ``gemma4:e4b`` for
Ollama, four Gemini models for Gemini). The Gemini free tier gives each model about 20 requests a day and a few per
minute: a per-minute 429 waits and retries, a per-day 429 moves the rest of the run to the next model.
Every call goes through ``UniversalAgent`` like in production. Answers are not deterministic: the tests check
behaviour (tool chosen, data used, format), never exact wording.
"""
from __future__ import annotations

import os
import re
import time
import urllib.request

PROVIDER = (os.getenv("HESTIA_LIVE_PROVIDER") or ("gemini" if os.getenv("ORACLE_KEY_GEMINI") else "ollama")).lower()
_DEFAULT_MODELS = (os.getenv("OLLAMA_MODEL", "gemma4:e4b") if PROVIDER == "ollama" else
                   "gemini-flash-lite-latest,gemini-3.1-flash-lite,gemma-4-26b-a4b-it,gemini-2.5-flash")
MODELS = [m.strip() for m in (os.getenv("HESTIA_LIVE_MODEL") or _DEFAULT_MODELS).split(",") if m.strip()]
MODEL = MODELS[0]
PAUSE_SEC = float(os.getenv("HESTIA_LIVE_PAUSE_SEC", "0" if PROVIDER == "ollama" else "5"))

TOOL_SYSTEM = ("You are Hestia's tool-calling engine. When the user asks for something you can do with a tool, "
               "call it. If no tool matches, respond in plain text.")

_dead: set[str] = set()   # models out of daily quota in this run


def ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate").rsplit("/api/", 1)[0]


def reachable() -> tuple[bool, str]:
    """Can the live tests run? No model call (Gemini: key present; Ollama: /api/tags answers)."""
    if PROVIDER == "gemini":
        return (bool(os.getenv("ORACLE_KEY_GEMINI")), "ORACLE_KEY_GEMINI missing")
    try:
        urllib.request.urlopen(f"{ollama_base()}/api/tags", timeout=3)
        return True, ""
    except Exception as exc:
        return False, f"Ollama not reachable at {ollama_base()} ({exc})"


class LiveAgent:
    """``ask`` / ``ask_with_tools`` of a UniversalAgent per model, paced, moving on when a model is out of quota."""

    def __init__(self, role_prompt: str = "", thinking: bool = False):
        from agents.universal_agent import UniversalAgent
        self._agents = {m: UniversalAgent(role_prompt=role_prompt, provider=PROVIDER, model_name=m, thinking=thinking)
                        for m in MODELS}

    def _call(self, method: str, *args, **kwargs):
        last: Exception | None = None
        for model in [m for m in MODELS if m not in _dead]:
            for attempt in range(3):
                if PAUSE_SEC:
                    time.sleep(PAUSE_SEC)
                try:
                    return getattr(self._agents[model], method)(*args, **kwargs)
                except Exception as exc:
                    last, text = exc, str(exc)
                    if re.search(r"per ?day|PerDay|no longer available|NOT_FOUND", text, re.IGNORECASE):
                        _dead.add(model)
                        break
                    if not re.search(r"429|RESOURCE_EXHAUSTED|503|UNAVAILABLE", text) or attempt == 2:
                        raise
                    time.sleep(30)
        raise last or RuntimeError(f"every live model is out of quota: {MODELS}")

    def ask(self, prompt: str, thinking=None) -> str:
        return self._call("ask", prompt, thinking=thinking)

    def ask_with_tools(self, prompt: str, tools: list[dict], thinking=None) -> dict:
        return self._call("ask_with_tools", prompt, tools, thinking=thinking)


def make_agent(role_prompt: str = "", thinking: bool = False) -> LiveAgent:
    return LiveAgent(role_prompt, thinking)


def ask_fns(role_prompt: str = TOOL_SYSTEM, thinking: bool = False):
    """(ask_fn, ask_tools_fn) for run_agent_loop; errors come back as text so the test prints them."""
    agent = make_agent(role_prompt, thinking)

    def ask(prompt: str) -> str:
        try:
            return agent.ask(prompt)
        except Exception as exc:
            return f"[LLM_ERROR: {exc}]"

    def ask_tools(prompt: str, tools_manifest: list[dict]) -> dict:
        try:
            return agent.ask_with_tools(prompt, tools_manifest)
        except Exception as exc:
            return {"tool_call": None, "text": f"[LLM_ERROR: {exc}]"}

    return ask, ask_tools
