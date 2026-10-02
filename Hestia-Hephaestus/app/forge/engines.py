"""Coding engines.  Same contract: ``run(workdir, prompt) -> EngineResult``.

- ``claude``       — Claude Code (Pro/Max subscription) run by Oracle in the task
  worktree via ``POST /api/llm/code``; Oracle holds the token.
- ``local`` / ``cloud`` — in-process tool-calling loop.  The LLM is reached via
  Oracle's ``/api/llm/chat`` (Hub route) on the profile of the same name:
  Oracle owns provider URLs and keys (microservice boundary).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from .agent_tools import AgentTools
from .config import ForgeConfig, normalize_engine
from .prompts import SYSTEM_PROMPT

logger = logging.getLogger("hestia_hephaestus.forge.engines")


@dataclass
class EngineResult:
    ok: bool
    summary: str
    engine: str
    log_tail: str = ""
    turns: int = 0
    cost_usd: float | None = None
    meta: dict = field(default_factory=dict)


class Engine:
    name = "base"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def run(self, workdir: Path, prompt: str, test_runner: Callable) -> EngineResult:
        raise NotImplementedError


# ── Claude Code via Oracle ─────────────────────────────────────────────────


class OracleClaudeEngine(Engine):
    """Claude Code runs inside Oracle (the LLM core, owner of the Pro token);
    Forge passes the task worktree path, shared by both containers."""
    name = "claude"

    def __init__(self, cfg: ForgeConfig):
        self.cfg = cfg

    def _route(self, method: str, path: str, body: dict | None, timeout: int) -> tuple[int, Any]:
        resp = requests.post(
            f"{self.cfg.hub_api_url}/route/oracle/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 5)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def available(self) -> tuple[bool, str]:
        try:
            status, payload = self._route("GET", "api/llm/code/status", None, 15)
        except Exception as exc:
            return False, f"Oracle unreachable via Hub: {exc}"
        payload = payload or {}
        if status >= 400 or not payload.get("available"):
            return False, str(payload.get("detail") or f"Oracle code status {status}")
        return True, "ok (Claude Code via Oracle)"

    def run(self, workdir: Path, prompt: str, test_runner: Callable) -> EngineResult:
        try:
            status, data = self._route("POST", "api/llm/code", {
                "workdir": str(workdir), "prompt": prompt, "append_system_prompt": SYSTEM_PROMPT,
                "max_turns": self.cfg.max_turns, "timeout_seconds": self.cfg.engine_timeout_seconds,
            }, self.cfg.engine_timeout_seconds + 30)
        except Exception as exc:
            return EngineResult(False, f"Oracle code call failed: {exc}", self.name)
        data = data if isinstance(data, dict) else {}
        if status >= 400:
            return EngineResult(False, f"Oracle code error {status}: {data.get('detail') or data}", self.name)
        return EngineResult(
            ok=bool(data.get("ok")), summary=str(data.get("summary") or ""), engine=self.name,
            log_tail=str(data.get("log_tail") or ""), turns=int(data.get("turns") or 0),
            cost_usd=data.get("cost_usd"), meta={"subtype": data.get("subtype")})


# ── Built-in agent (OpenAI-compatible tool calling) ────────────────────────


class BuiltinEngine(Engine):
    """Agent loop for ``local`` and ``cloud``.  LLM access goes through Oracle
    (``POST /api/llm/chat`` via Hub): Oracle owns provider URLs and keys,
    Forge only names a profile."""
    _CONTEXT_CHAR_BUDGET = 90000   # ~25k tokens: fits 32k-context local models

    def __init__(self, cfg: ForgeConfig, name: str):
        self.cfg = cfg
        self.name = name

    def _route(self, method: str, path: str, body: dict | None, timeout: int) -> tuple[int, Any]:
        resp = requests.post(
            f"{self.cfg.hub_api_url}/route/oracle/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 5)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def available(self) -> tuple[bool, str]:
        try:
            status, payload = self._route("GET", "api/llm/profiles", None, 15)
        except Exception as exc:
            return False, f"Oracle unreachable via Hub: {exc}"
        prof = ((payload or {}).get("profiles") or {}).get(self.name) if status < 400 else None
        if not prof:
            return False, f"Oracle has no '{self.name}' LLM profile (ORACLE_LLM_PROFILE_{self.name.upper()}_*)"
        if prof.get("available") is False:
            return False, f"{prof.get('model')}: {prof.get('detail')}"
        return True, f"ok ({prof.get('model')} via Oracle)"

    def _trim(self, messages: list[dict]) -> None:
        """Shrink old tool outputs when over budget (keep system + task + recent)."""
        total = sum(len(str(m.get("content") or "")) for m in messages)
        for msg in messages[2:-6]:
            if total <= self._CONTEXT_CHAR_BUDGET:
                break
            if msg.get("role") == "tool" and len(str(msg.get("content") or "")) > 200:
                total -= len(msg["content"]) - 20
                msg["content"] = "[old output trimmed]"

    def run(self, workdir: Path, prompt: str, test_runner: Callable) -> EngineResult:
        tools = AgentTools(workdir, test_runner)
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        nudged = False
        log: list[str] = []
        turn = 0
        for turn in range(1, self.cfg.max_turns + 1):
            self._trim(messages)
            try:
                status, data = self._route(
                    "POST", "api/llm/chat",
                    {"profile": self.name, "messages": messages,
                     "tools": AgentTools.schemas(), "temperature": 0.2},
                    self.cfg.llm_route_timeout)
                if status >= 400:
                    raise RuntimeError(f"Oracle llm/chat {status}: {str(data)[:300]}")
                msg = data["choices"][0]["message"]
            except Exception as exc:
                return EngineResult(False, f"LLM call failed: {exc}", self.name, "\n".join(log[-30:]), turn)

            calls = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             **({"tool_calls": calls} if calls else {})})
            if not calls:
                if nudged:
                    break
                nudged = True
                messages.append({"role": "user", "content": "Use tools. Edit files. Call finish when done."})
                continue

            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                result = tools.call(name, args if isinstance(args, dict) else {})
                log.append(f"[{turn}] {name}({', '.join(sorted(args)) if isinstance(args, dict) else ''}) -> {result[:120]!r}")
                messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": result})
            if tools.finished_summary is not None:
                return EngineResult(True, tools.finished_summary, self.name, "\n".join(log[-30:]), turn)

        return EngineResult(False, "agent stopped without finish (turn limit or no tool use)",
                            self.name, "\n".join(log[-30:]), turn)


# ── Selection ───────────────────────────────────────────────────────────────


def build_engines(cfg: ForgeConfig) -> dict[str, Engine]:
    engines: list[Engine] = [
        BuiltinEngine(cfg, "local"),
        BuiltinEngine(cfg, "cloud"),
        OracleClaudeEngine(cfg),
    ]
    return {e.name: e for e in engines}


def select_engine(engines: dict[str, Engine], requested: str, default: str,
                  fallback: list[str]) -> tuple[Engine | None, str]:
    """Explicit engine → that one only.  ``auto``/empty → default, then fallback chain."""
    requested = normalize_engine(requested)
    if requested and requested != "auto":
        engine = engines.get(requested)
        if not engine:
            return None, f"unknown engine '{requested}' (use: {', '.join(engines)})"
        ok, reason = engine.available()
        return (engine, reason) if ok else (None, f"{requested}: {reason}")
    tried = []
    for name in [default] + [f for f in fallback if f != default]:
        engine = engines.get(name)
        if not engine:
            continue
        ok, reason = engine.available()
        if ok:
            note = "" if name == default else f" (fallback: {default} unavailable)"
            return engine, reason + note
        tried.append(f"{name}: {reason}")
    return None, "no engine available — " + " | ".join(tried)


def wait_seconds(seconds: int) -> None:
    time.sleep(max(0, seconds))
