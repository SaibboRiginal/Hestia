"""External brain mode (dossier ``docs/work/2026-10-19-oracle-a-blocchi`` §D): an agent CLI runs the loop.

Interna = Oracle's own machine (classifier, modes, agent loop, chains). Esterna = an agent (Claude Code through the
subscription, Codex through `codex login`) runs the tool loop; Oracle keeps the door work: context, the domain-filtered
tools, saving messages to Archive, memory, usage rows.

- Tools: the agent gets Hestia's tools through ``core.services.mcp_bridge``, a stdio MCP server the CLI starts. The
  bridge only forwards ``tools/list`` / ``tools/call`` back to this Oracle (loopback, one random token per turn) where
  the same tool handlers run: same domain filter, same approval gate, same logs and Hub routing. The agent's own
  file/shell tools stay off.
- Sessions: Archive is the source of truth. The agent's session id is only a cache keyed by (Archive session, agent,
  model), kept in memory; missing, another agent/model, or older than the last turn answered in interna → a new agent
  session primed with the context Oracle builds for its own loop (summary + recent messages + memory).
- Fails (not installed, no login, error, limit) → ``AgentError``; the caller redoes the turn in interna when
  ``oracle.brain.fallback`` = interna.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("hestia_oracle.external_agent")

SELF_URL = "http://127.0.0.1:19004"          # this Oracle (Dockerfile CMD port): the bridge calls back here only
_RUN_TTL = 3600
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}
_sessions: dict[tuple[str, str, str], tuple[str, float]] = {}
_internal_at: dict[str, float] = {}


class AgentError(RuntimeError):
    pass


# ── settings ─────────────────────────────────────────────────────────────────

def brain() -> dict[str, str]:
    from core.services import oracle_settings as s
    get = s.settings.get
    return {"mode": str(get(s.BRAIN_MODE, "interna") or "interna"), "agent": str(get(s.BRAIN_AGENT, "claude") or "claude"),
            "model": str(get(s.BRAIN_MODEL, "") or "").strip(), "fallback": str(get(s.BRAIN_FALLBACK, "interna") or "interna")}


def mode_for(use_case: str) -> str:
    """interna | esterna for *use_case*: its own mode (Modelli) or, with «segui», the global one."""
    from core.services import llm_chains
    own = llm_chains.usecase_config(use_case)["mode"]
    return own if own in ("interna", "esterna") else ("esterna" if brain()["mode"] == "esterna" else "interna")


def available(agent: str = "") -> tuple[bool, str]:
    adapter = _ADAPTERS.get(agent or brain()["agent"])
    if adapter is None:
        return False, f"unknown agent {agent!r}"
    return adapter.available()


# ── tool runs (one per turn, read by the MCP bridge through /api/agent-bridge/<token>) ───────────────────────

def open_run(tools: list) -> str:
    token = secrets.token_urlsafe(24)
    with _lock:
        now = time.time()
        for old in [k for k, r in _runs.items() if r["expires"] < now]:
            del _runs[old]
        _runs[token] = {"tools": {t.name: t for t in tools}, "log": [], "expires": now + _RUN_TTL}
    return token


def close_run(token: str) -> list[dict]:
    with _lock:
        run = _runs.pop(token, None)
    return run["log"] if run else []


def _run(token: str) -> dict:
    with _lock:
        run = _runs.get(token)
    if run is None or run["expires"] < time.time():
        raise KeyError("unknown or expired run")
    return run


def list_tools(token: str) -> list[dict]:
    return [{"name": t.name, "description": t.description,
             "inputSchema": t.parameters if isinstance(t.parameters, dict) and t.parameters else {"type": "object"}}
            for t in sorted(_run(token)["tools"].values(), key=lambda t: t.name)]


def call_tool(token: str, name: str, params: dict) -> dict:
    """Run one of the turn's tools (same handler as the internal loop) and log it like the internal loop."""
    run = _run(token)
    tool = run["tools"].get(name)
    if tool is None:
        return {"ok": False, "result": f"Unknown tool: {name}"}
    t0 = time.perf_counter()
    try:
        ok, result = tool.handler(**(params or {}))
    except Exception as exc:
        ok, result = False, str(exc)
    preview = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    logger.info("event=external_agent_tool tool=%s ok=%s duration_ms=%d result_chars=%d", name, ok,
                int((time.perf_counter() - t0) * 1000), len(preview))
    with _lock:
        run["log"].append({"tool": name, "ok": bool(ok), "result_preview": preview[:300], "turn": len(run["log"]) + 1,
                           "writes": bool(getattr(tool, "writes", False)), "title": getattr(tool, "title", "") or name,
                           "confirm": result.get("confirm") if ok and isinstance(result, dict)
                           and isinstance(result.get("confirm"), dict) else None})
    return {"ok": bool(ok), "result": preview}


def _bridge_server(token: str) -> dict:
    """How the CLI starts the stdio MCP bridge (this interpreter, Oracle's code dir)."""
    code_dir = str(Path(__file__).resolve().parents[2])
    return {"command": sys.executable, "args": ["-m", "core.services.mcp_bridge"],
            "env": {"HESTIA_BRIDGE_URL": f"{SELF_URL}/api/agent-bridge/{token}", "PYTHONPATH": code_dir}}


# ── sessions cache ───────────────────────────────────────────────────────────

def note_internal_turn(session_id: str) -> None:
    """A turn of *session_id* was answered in interna: a cached agent session no longer has the full history."""
    if session_id:
        with _lock:
            _internal_at[session_id] = time.time()


def _cached(session_id: str, agent: str, model: str) -> str:
    with _lock:
        hit = _sessions.get((session_id, agent, model))
        if not hit or hit[1] < _internal_at.get(session_id, 0.0):
            return ""
        return hit[0]


def _remember(session_id: str, agent: str, model: str, agent_session: str) -> None:
    if session_id and agent_session:
        with _lock:
            _sessions[(session_id, agent, model)] = (agent_session, time.time())


def forget(session_id: str) -> None:
    with _lock:
        for key in [k for k in _sessions if k[0] == session_id]:
            del _sessions[key]


# ── turns ────────────────────────────────────────────────────────────────────

def run_turn(*, session_id: str, user_message: str, system_prompt: str, primer: str, tools: list,
             use_case: str = "oracle.generale") -> tuple[str, list[dict]]:
    """One chat turn by the external agent with Hestia's tools. Returns (answer, tool log)."""
    cfg = brain()
    adapter = _ADAPTERS.get(cfg["agent"])
    if adapter is None:
        raise AgentError(f"unknown agent {cfg['agent']!r}")
    ok, detail = adapter.available()
    if not ok:
        raise AgentError(detail)
    resume = _cached(session_id, cfg["agent"], cfg["model"])
    prompt = user_message if resume else (f"{primer.strip()}\n\nUSER: {user_message}" if primer.strip() else user_message)
    token = open_run(tools)
    try:
        result = _timed(adapter, use_case, cfg, system_prompt, prompt, resume, token)
    finally:
        log = close_run(token)
    _remember(session_id, cfg["agent"], cfg["model"], result.get("session_id", ""))
    return result["text"], log


def ask(prompt: str, system: str = "", use_case: str = "oracle.generale") -> str:
    """One shot without tools (``/api/llm/generate`` of a use case in esterna)."""
    cfg = brain()
    adapter = _ADAPTERS.get(cfg["agent"])
    if adapter is None:
        raise AgentError(f"unknown agent {cfg['agent']!r}")
    ok, detail = adapter.available()
    if not ok:
        raise AgentError(detail)
    return _timed(adapter, use_case, cfg, system, prompt, "", "")["text"]


def _timed(adapter, use_case: str, cfg: dict, system: str, prompt: str, resume: str, token: str) -> dict:
    from core.services import llm_stats, llm_usage
    model = cfg["model"] or adapter.DEFAULT_MODEL
    with llm_usage.step(use_case, f"agente:{cfg['agent']}", 0, cfg["agent"], model) as usage:
        t0 = time.perf_counter()
        try:
            result = adapter.run(model=cfg["model"], system=system, prompt=prompt, resume=resume,
                                 bridge=_bridge_server(token) if token else None)
        except Exception as exc:
            llm_usage.finish(usage, "error", str(exc)[:300])
            logger.warning("[🔄] event=external_agent_failed agent=%s model=%s error=%s", cfg["agent"], model,
                           str(exc)[:300])
            raise AgentError(str(exc)) from exc
        u = result.get("usage") or {}
        llm_stats.record(f"agente:{cfg['agent']}", cfg["agent"], model, prompt_tokens=int(u.get("input", 0)),
                         cached_tokens=int(u.get("cached", 0)), output_tokens=int(u.get("output", 0)),
                         cost_usd=float(u.get("cost_usd", 0) or 0))
        llm_usage.finish(usage)
    logger.info("event=external_agent_turn agent=%s model=%s resumed=%s ms=%d tools=%s", cfg["agent"], model,
                bool(resume), int((time.perf_counter() - t0) * 1000), bool(token))
    return result


# ── adapters ─────────────────────────────────────────────────────────────────

def _subprocess(cmd: list[str], prompt: str, timeout: int) -> subprocess.CompletedProcess:
    from agents.llm_config import cli_env
    with tempfile.TemporaryDirectory(prefix="oracle-agent-") as cwd:   # empty dir: no project files picked up
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=cwd, env=cli_env(), timeout=timeout)


def _timeout() -> int:
    from core.services import oracle_settings
    return max(30, oracle_settings.get_int(oracle_settings.GATEWAY_CHAT_TIMEOUT, 600))


class ClaudeCodeAgent:
    """`claude -p` with the subscription login; only Hestia's MCP tools (built-in tools off)."""
    DEFAULT_MODEL = "sonnet"

    @staticmethod
    def bin() -> str:
        return os.getenv("ORACLE_CLAUDE_BIN", "claude")

    @classmethod
    def available(cls) -> tuple[bool, str]:
        if not shutil.which(cls.bin()):
            return False, "claude CLI not installed (ORACLE_INSTALL_CLAUDE_CODE=1)"
        creds = Path.home() / ".claude" / ".credentials.json"
        if not os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip() and not creds.exists():
            return False, "no subscription login (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`)"
        return True, "ok"

    @classmethod
    def command(cls, model: str, system: str, resume: str, mcp_file: str) -> list[str]:
        cmd = [cls.bin(), "-p", "--output-format", "json", "--tools", ""]
        if model:
            cmd += ["--model", model]
        if system:
            cmd += ["--system-prompt", system]
        if mcp_file:
            cmd += ["--mcp-config", mcp_file, "--strict-mcp-config", "--allowedTools", "mcp__hestia"]
        else:
            cmd += ["--strict-mcp-config"]
        if resume:
            cmd += ["--resume", resume]
        return cmd

    @classmethod
    def run(cls, *, model: str, system: str, prompt: str, resume: str, bridge: dict | None) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="oracle-mcp-", delete=False) as fh:
            json.dump({"mcpServers": {"hestia": bridge}} if bridge else {"mcpServers": {}}, fh)
            mcp_file = fh.name
        try:
            proc = _subprocess(cls.command(model, system, resume, mcp_file if bridge else ""), prompt, _timeout())
        finally:
            os.unlink(mcp_file)
        try:
            data = json.loads(proc.stdout or "{}")
        except ValueError:
            data = {}
        if proc.returncode != 0 or data.get("is_error") or "result" not in data:
            raise AgentError(f"claude rc={proc.returncode}: {(data.get('result') or proc.stderr or proc.stdout or '')[:300]}")
        usage = data.get("usage") or {}
        fresh, read = int(usage.get("input_tokens") or 0), int(usage.get("cache_read_input_tokens") or 0)
        write = int(usage.get("cache_creation_input_tokens") or 0)
        return {"text": str(data.get("result") or "").strip(), "session_id": str(data.get("session_id") or ""),
                "usage": {"input": fresh + read + write, "cached": read, "output": int(usage.get("output_tokens") or 0),
                          "cost_usd": float(data.get("total_cost_usd") or 0)}}


class CodexAgent:
    """`codex exec --json` with the ChatGPT login (`codex login`, mounted ~/.codex); Hestia's MCP tools only."""
    DEFAULT_MODEL = ""

    @staticmethod
    def bin() -> str:
        return os.getenv("ORACLE_CODEX_BIN", "codex")

    @classmethod
    def available(cls) -> tuple[bool, str]:
        if not shutil.which(cls.bin()):
            return False, "codex CLI not installed (ORACLE_INSTALL_CODEX=1)"
        home = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
        if not (home / "auth.json").exists():
            return False, f"no Codex login ({home}/auth.json from `codex login`)"
        return True, "ok"

    @staticmethod
    def _toml(value: Any) -> str:
        return json.dumps(value) if not isinstance(value, dict) else \
            "{" + ", ".join(f"{k} = {json.dumps(v)}" for k, v in value.items()) + "}"

    @classmethod
    def command(cls, model: str, resume: str, bridge: dict | None) -> list[str]:
        cmd = [cls.bin(), "exec"] + (["resume", resume] if resume else []) + [
            "--json", "--skip-git-repo-check", "--sandbox", "read-only"]
        if model:
            cmd += ["-m", model]
        if bridge:
            cmd += ["-c", f"mcp_servers.hestia.command={cls._toml(bridge['command'])}",
                    "-c", f"mcp_servers.hestia.args={cls._toml(bridge['args'])}",
                    "-c", f"mcp_servers.hestia.env={cls._toml(bridge['env'])}"]
        return cmd + ["-"]

    @classmethod
    def run(cls, *, model: str, system: str, prompt: str, resume: str, bridge: dict | None) -> dict:
        # Codex has no system prompt flag: the contract goes first in a new session (the cache keeps it after).
        text = prompt if resume or not system else f"{system}\n\n{prompt}"
        proc = _subprocess(cls.command(model, resume, bridge), text, _timeout())
        session, answer, usage, error = resume, [], {}, ""
        for line in (proc.stdout or "").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type", "")
            if kind == "thread.started":
                session = str(ev.get("thread_id") or session)
            elif kind == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                answer.append(str(ev["item"].get("text") or ""))
            elif kind == "turn.completed":
                usage = ev.get("usage") or {}
            elif kind in ("turn.failed", "error"):
                error = str((ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict)
                            else ev.get("message") or ev)
        if proc.returncode != 0 or error or not answer:
            raise AgentError(f"codex rc={proc.returncode}: {(error or proc.stderr or '')[:300]}")
        inp = int(usage.get("input_tokens") or 0)
        return {"text": answer[-1].strip(), "session_id": session,
                "usage": {"input": inp, "cached": int(usage.get("cached_input_tokens") or 0),
                          "output": int(usage.get("output_tokens") or 0)}}


_ADAPTERS = {"claude": ClaudeCodeAgent, "codex": CodexAgent}
