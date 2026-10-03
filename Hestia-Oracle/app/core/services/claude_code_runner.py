"""Claude Code runner — the "code" use case on a Claude Pro/Max subscription.

Oracle is the single owner of LLM access, including Claude Code: it holds the
subscription token (``CLAUDE_CODE_OAUTH_TOKEN`` from ``claude setup-token``)
and runs ``claude -p`` headless inside a Forge task worktree.  Hephaestus only
orchestrates (branch, tests, merge, rollback) and calls ``POST /api/llm/code``.

Scope guard: the subscription covers Claude Code for development work, so this
runner is used only for code tasks in a worktree under
``ORACLE_CODE_WORKDIR_ROOT`` — never for general chat.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("hestia_oracle.claude_code")

# Read/write + run tests + inspect git. No commit/push (Forge commits), no network
# tools, no docker: the merge/deploy decision stays with Forge and the user.
_ALLOWED_TOOLS = ("Read,Edit,Write,Glob,Grep,TodoWrite,"
                  "Bash(python -m pytest:*),Bash(pytest:*),Bash(python -m py_compile:*),"
                  "Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git show:*),"
                  "Bash(ls:*),Bash(mkdir:*)")


class ClaudeCodeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _bin() -> str:
    return os.getenv("ORACLE_CLAUDE_BIN", "claude")


def _workdir_root() -> Path:
    return Path(os.getenv("ORACLE_CODE_WORKDIR_ROOT", "/forge/worktrees")).resolve()


def status() -> dict[str, Any]:
    if not shutil.which(_bin()):
        return {"available": False,
                "detail": "Claude Code not installed in Oracle (build with --build-arg INSTALL_CLAUDE_CODE=1)"}
    creds = Path(os.path.expanduser("~/.claude/.credentials.json"))
    if not (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY") or creds.exists()):
        return {"available": False,
                "detail": "no auth: set CLAUDE_CODE_OAUTH_TOKEN in Oracle .env (run `claude setup-token`)"}
    if not _workdir_root().is_dir():
        return {"available": False, "detail": f"worktree root {_workdir_root()} not mounted"}
    return {"available": True, "detail": "ok", "model": os.getenv("ORACLE_CLAUDE_MODEL", "") or "default"}


def run(workdir: str, prompt: str, append_system_prompt: str = "",
        max_turns: int = 40, timeout_seconds: int = 1800) -> dict[str, Any]:
    st = status()
    if not st["available"]:
        raise ClaudeCodeError(st["detail"], 503)
    root = _workdir_root()
    target = Path(workdir).resolve()
    if target == root or root not in target.parents or not target.is_dir():
        raise ClaudeCodeError(f"workdir must be an existing task folder under {root}", 400)
    if not str(prompt or "").strip():
        raise ClaudeCodeError("prompt required", 400)

    cmd = [_bin(), "-p", prompt,
           "--output-format", "json",
           "--max-turns", str(max(1, int(max_turns))),
           "--permission-mode", "acceptEdits",
           "--allowedTools", _ALLOWED_TOOLS]
    if append_system_prompt:
        cmd += ["--append-system-prompt", append_system_prompt]
    model = os.getenv("ORACLE_CLAUDE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]

    logger.info("event=claude_code_run_start workdir=%s max_turns=%s", target, max_turns)
    try:
        proc = subprocess.run(cmd, cwd=str(target), capture_output=True, text=True,
                              timeout=max(60, int(timeout_seconds)))
    except subprocess.TimeoutExpired:
        raise ClaudeCodeError("claude timed out", 504)
    raw = (proc.stdout or "").strip()
    try:
        data = json.loads(raw.splitlines()[-1]) if raw else {}
    except (ValueError, IndexError):
        data = {}
    ok = not bool(data.get("is_error")) and proc.returncode == 0
    result = {
        "ok": ok,
        "summary": str(data.get("result") or proc.stderr or raw)[:3000],
        "turns": int(data.get("num_turns") or 0),
        "cost_usd": data.get("total_cost_usd"),
        "subtype": data.get("subtype"),
        "log_tail": (proc.stderr or "")[-2000:],
    }
    logger.info("event=claude_code_run_done ok=%s turns=%s", ok, result["turns"])
    return result
