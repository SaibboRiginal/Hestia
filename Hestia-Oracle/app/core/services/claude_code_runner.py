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
import tempfile
import threading
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


def transcript_path(workdir: Path) -> Path:
    """Live transcript of a run: ``<root>/.transcripts/<task folder>.jsonl``.

    Outside the worktree (Forge commits the worktree with ``git add -A``) but on
    the same shared mount, so Hephaestus can show it while the run is going."""
    return _workdir_root() / ".transcripts" / f"{workdir.name}.jsonl"


_MAX_LINE = 200_000   # one stream-json line (a huge tool output) is clipped, never dropped


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

    # stream-json (+ --verbose, required by -p) = every message, thinking block,
    # tool call and tool result as one JSON line; the last line is the result.
    cmd = [_bin(), "-p", prompt,
           "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max(1, int(max_turns))),
           "--permission-mode", "acceptEdits",
           "--allowedTools", _ALLOWED_TOOLS]
    if append_system_prompt:
        cmd += ["--append-system-prompt", append_system_prompt]
    model = os.getenv("ORACLE_CLAUDE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]

    tpath = transcript_path(target)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    logger.info("event=claude_code_run_start workdir=%s max_turns=%s transcript=%s", target, max_turns, tpath)
    data: dict[str, Any] = {}
    killed = threading.Event()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err, \
            tpath.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=str(target), stdout=subprocess.PIPE, stderr=err,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        def _kill() -> None:
            killed.set()
            proc.kill()
        timer = threading.Timer(max(60, int(timeout_seconds)), _kill)
        timer.start()
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                out.write((line if len(line) <= _MAX_LINE else _clip_line(line)) + "\n")
                out.flush()
                if '"result"' in line[:60]:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = {}
                    if event.get("type") == "result":
                        data = event
            proc.wait()
        finally:
            timer.cancel()
        err.seek(0)
        stderr = err.read()
    if killed.is_set():
        logger.warning("[🔄] event=claude_code_run_timeout workdir=%s", target)
        raise ClaudeCodeError("claude timed out", 504)
    ok = not bool(data.get("is_error")) and proc.returncode == 0 and bool(data)
    result = {
        "ok": ok,
        "summary": str(data.get("result") or stderr or "no result line from claude")[:3000],
        "turns": int(data.get("num_turns") or 0),
        "cost_usd": data.get("total_cost_usd"),
        "subtype": data.get("subtype"),
        "log_tail": (stderr or "")[-2000:],
        "transcript_path": str(tpath),
    }
    logger.info("event=claude_code_run_done ok=%s turns=%s", ok, result["turns"])
    return result


def _clip_line(line: str) -> str:
    """Keep the event parseable: clip long strings inside it instead of the raw line."""
    try:
        event = json.loads(line)
    except ValueError:
        return json.dumps({"type": "clipped", "text": line[:_MAX_LINE]})

    def clip(value: Any) -> Any:
        if isinstance(value, str):
            return value if len(value) <= 20_000 else value[:20_000] + f"\n...[cut {len(value) - 20_000} chars]"
        if isinstance(value, list):
            return [clip(v) for v in value]
        if isinstance(value, dict):
            return {k: clip(v) for k, v in value.items()}
        return value
    return json.dumps(clip(event), ensure_ascii=False)
