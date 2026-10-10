"""Provider ``claude_cli`` — Claude through the user's subscription, via the official `claude` CLI.

Same login as Forge (``CLAUDE_CODE_OAUTH_TOKEN``), no extra cost, but one CLI start per call
(slower) and the subscription usage limits are shared with Forge.  Claude Code's own tools
are disabled and no MCP server is loaded: Oracle's agent loop stays in charge, and the
domain-filtered tools are described in the prompt and returned as ``<tool_call>{json}</tool_call>``
blocks (parsed here into native tool calls).  Anthropic API keys are never passed to the CLI.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

from agents.providers.base import LLMProvider, think_level, tool_result

logger = logging.getLogger("hestia_oracle.providers.claude_cli")

_TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

_TOOL_PROTOCOL = (
    "TOOLS. To call tools reply ONLY with one block per call:\n"
    '<tool_call>{"name": "<tool>", "params": {...}}</tool_call>\n'
    "No tool needed → answer the user normally, no blocks.\n"
)


class ClaudeCliProvider(LLMProvider):
    TYPE = "claude_cli"
    LABEL = "Claude (abbonamento)"
    CONFIG_FIELDS = (
        {"key": "bin", "type": "string", "label": "Comando claude", "default": "claude"},
        {"key": "authed", "type": "bool", "label": "Login abbonamento presente", "default": False},
        {"key": "env", "type": "object", "label": "Ambiente del processo", "default": None},
        {"key": "effort_by_mode", "type": "object", "label": "Ragionamento per modalità",
         "default": {"fast": "low", "normal": "medium", "deep": "high"}},
        {"key": "timeout_sec", "type": "int", "label": "Timeout (secondi)", "default": 300},
    )
    CAPABILITIES = frozenset({"chat", "tools", "thinking"})
    MODELS = ("haiku", "sonnet", "opus", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")

    def available(self) -> tuple[bool, str]:
        if not shutil.which(str(self.config.get("bin") or "claude")):
            return False, "claude CLI not installed (ORACLE_INSTALL_CLAUDE_CODE=1)"
        if not self.config.get("authed"):
            return False, "no subscription login (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`)"
        return True, "ok"

    def list_models(self) -> list[str]:
        return list(self.MODELS)

    def _run(self, model: str, system: str, prompt: str, thinking: Any) -> str:
        ok, detail = self.available()
        if not ok:
            raise RuntimeError(f"claude_cli provider unavailable: {detail}")
        effort = (self.config.get("effort_by_mode") or {}).get(think_level(thinking), "low")
        cmd = [str(self.config["bin"]), "-p", "--output-format", "json", "--model", model,
               "--effort", effort, "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
        if system:
            cmd += ["--system-prompt", system]
        t0 = time.perf_counter()
        # Empty working dir: no CLAUDE.md or project settings are picked up.
        with tempfile.TemporaryDirectory(prefix="oracle-claude-") as cwd:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", cwd=cwd, env=self.config.get("env"),
                                  timeout=int(self.config["timeout_sec"]))
        elapsed = int((time.perf_counter() - t0) * 1000)
        try:
            data = json.loads(proc.stdout or "{}")
        except ValueError:
            data = {}
        if proc.returncode != 0 or data.get("is_error") or "result" not in data:
            raise RuntimeError(f"claude CLI failed rc={proc.returncode}: "
                               f"{(data.get('result') or proc.stderr or proc.stdout or '')[:300]}")
        usage = data.get("usage") or {}
        logger.info("event=claude_cli_call model=%s effort=%s ms=%d input=%s output=%s cache_read=%s",
                    model, effort, elapsed, usage.get("input_tokens"), usage.get("output_tokens"),
                    usage.get("cache_read_input_tokens"))
        return str(data.get("result") or "").strip()

    def ask(self, model: str, system: str, prompt: str, thinking: Any = None) -> str:
        return self._run(model, system, prompt, thinking)

    def ask_with_tools(self, model: str, system: str, prompt: str, tools: list[dict],
                       thinking: Any = None) -> dict:
        specs = "\n".join(
            f"- {t.get('name')}: {str(t.get('description') or '').strip()}\n"
            f"  params: {json.dumps((t.get('parameters') or {}).get('properties') or {}, ensure_ascii=False)}"
            for t in tools if t.get("name"))
        text = self._run(model, system, f"{_TOOL_PROTOCOL}{specs}\n\n{prompt}", thinking)
        calls = []
        for block in _TOOL_CALL.findall(text):
            try:
                item = json.loads(block)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("name"):
                params = item.get("params") if isinstance(item.get("params"), dict) else {}
                calls.append({"name": str(item["name"]).strip(), "params": params})
        logger.info("event=claude_cli_tool_decision model=%s tool_calls=%s text_len=%d",
                    model, [c["name"] for c in calls], len(text))
        return tool_result(calls, "" if calls else text)
