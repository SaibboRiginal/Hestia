"""Coding engines.  Same contract: ``run(workdir, prompt) -> EngineResult``.

- ``claude``       — Claude Code CLI headless (``claude -p``).  Works with a Claude
  Pro/Max subscription via ``CLAUDE_CODE_OAUTH_TOKEN`` (``claude setup-token``) or
  pay-per-use ``ANTHROPIC_API_KEY``.
- ``aider``        — Aider CLI, any model (Ollama, OpenRouter, ...).  Optional.
- ``local`` / ``cloud`` — in-process tool-calling loop on an OpenAI-compatible
  endpoint.  Two independent profiles, both active at once: ``local`` (Ollama
  by default) and ``cloud`` (OpenRouter, Gemini, ...).  Zero extra install.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .agent_tools import AgentTools
from .config import ForgeConfig, LLMProfile, normalize_engine
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


# ── Claude Code CLI ─────────────────────────────────────────────────────────


class ClaudeCodeEngine(Engine):
    name = "claude"
    _ALLOWED_TOOLS = ("Read,Edit,Write,Glob,Grep,"
                      "Bash(python -m pytest:*),Bash(pytest:*),Bash(git status:*),Bash(git diff:*)")

    def __init__(self, cfg: ForgeConfig):
        self.cfg = cfg

    def available(self) -> tuple[bool, str]:
        if not shutil.which(self.cfg.claude_bin):
            return False, f"'{self.cfg.claude_bin}' CLI not installed"
        creds = Path(os.path.expanduser("~/.claude/.credentials.json"))
        if os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY") or creds.exists():
            return True, "ok"
        return False, "no auth: set CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) or ANTHROPIC_API_KEY"

    def run(self, workdir: Path, prompt: str, test_runner: Callable) -> EngineResult:
        cmd = [self.cfg.claude_bin, "-p", prompt,
               "--output-format", "json",
               "--max-turns", str(self.cfg.max_turns),
               "--permission-mode", "acceptEdits",
               "--allowedTools", self._ALLOWED_TOOLS,
               "--append-system-prompt", SYSTEM_PROMPT]
        if self.cfg.claude_model:
            cmd += ["--model", self.cfg.claude_model]
        try:
            proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True,
                                  timeout=self.cfg.engine_timeout_seconds)
        except subprocess.TimeoutExpired:
            return EngineResult(False, "claude timed out", self.name)
        raw = (proc.stdout or "").strip()
        try:
            data = json.loads(raw.splitlines()[-1]) if raw else {}
        except (ValueError, IndexError):
            data = {}
        is_error = bool(data.get("is_error")) or proc.returncode != 0
        summary = str(data.get("result") or proc.stderr or raw)[:3000]
        return EngineResult(
            ok=not is_error, summary=summary, engine=self.name,
            log_tail=(proc.stderr or "")[-2000:], turns=int(data.get("num_turns") or 0),
            cost_usd=data.get("total_cost_usd"), meta={"subtype": data.get("subtype")})


# ── Aider CLI ───────────────────────────────────────────────────────────────


class AiderEngine(Engine):
    name = "aider"

    def __init__(self, cfg: ForgeConfig):
        self.cfg = cfg

    def available(self) -> tuple[bool, str]:
        if not shutil.which(self.cfg.aider_bin):
            return False, f"'{self.cfg.aider_bin}' CLI not installed"
        return True, "ok"

    def run(self, workdir: Path, prompt: str, test_runner: Callable) -> EngineResult:
        env = dict(os.environ)
        env.setdefault("OLLAMA_API_BASE", self.cfg.local.base_url.removesuffix("/v1"))
        cmd = [self.cfg.aider_bin, "--yes-always", "--no-auto-commits", "--no-check-update",
               "--no-show-model-warnings", "--no-pretty", "--model", self.cfg.aider_model,
               "--message", f"{SYSTEM_PROMPT}\n\n{prompt}"]
        try:
            proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True,
                                  timeout=self.cfg.engine_timeout_seconds, env=env)
        except subprocess.TimeoutExpired:
            return EngineResult(False, "aider timed out", self.name)
        out = proc.stdout or ""
        return EngineResult(proc.returncode == 0, out[-2000:], self.name, log_tail=(proc.stderr or "")[-2000:])


# ── Built-in agent (OpenAI-compatible tool calling) ────────────────────────


class BuiltinEngine(Engine):
    """Same agent loop for ``local`` and ``cloud``: only the profile differs."""
    _CONTEXT_CHAR_BUDGET = 90000   # ~25k tokens: fits 32k-context local models

    def __init__(self, cfg: ForgeConfig, name: str, profile: LLMProfile):
        self.cfg = cfg
        self.name = name
        self.profile = profile

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.profile.api_key}", "Content-Type": "application/json"}

    def available(self) -> tuple[bool, str]:
        if not self.profile.configured:
            return False, f"not configured (HEPHAESTUS_FORGE_{self.name.upper()}_BASE_URL/_MODEL)"
        try:
            resp = requests.get(f"{self.profile.base_url}/models", headers=self._headers(), timeout=5)
            if resp.status_code in (401, 403):
                return False, f"auth refused by {self.profile.base_url} (check API key)"
            if resp.status_code < 500:
                return True, f"ok ({self.profile.model} @ {self.profile.base_url})"
            return False, f"LLM endpoint status {resp.status_code}"
        except Exception as exc:
            return False, f"LLM endpoint unreachable: {exc}"

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
                resp = requests.post(
                    f"{self.profile.base_url}/chat/completions", headers=self._headers(),
                    json={"model": self.profile.model, "messages": messages,
                          "tools": AgentTools.schemas(), "temperature": 0.2},
                    timeout=600)
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
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
        BuiltinEngine(cfg, "local", cfg.local),
        BuiltinEngine(cfg, "cloud", cfg.cloud),
        ClaudeCodeEngine(cfg),
        AiderEngine(cfg),
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
