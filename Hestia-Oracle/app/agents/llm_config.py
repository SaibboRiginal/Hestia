"""LLM provider infrastructure config — the single place that reads provider env.

Endpoints, keys and binaries are infrastructure (central-settings SPEC v2.0): they stay in
env.  Model choice per use case is a Themis setting (``core.services.oracle_settings``).
Provider classes receive the dict built here and never call ``os.getenv`` themselves.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Never handed to a `claude` subprocess: an Anthropic API key in its env would switch
# Claude Code from the subscription to paid API billing (and expose the key to it).
ANTHROPIC_KEY_VARS = ("ANTHROPIC_API_KEY", "ORACLE_ANTHROPIC_API_KEY")


def cli_env() -> dict[str, str]:
    """Environment for a `claude` subprocess: Oracle's env minus Anthropic API keys."""
    return {k: v for k, v in os.environ.items() if k not in ANTHROPIC_KEY_VARS}


def load_llm_config() -> dict[str, dict[str, Any]]:
    """Per provider type: its infrastructure config (keys, binaries, env)."""
    creds = Path.home() / ".claude" / ".credentials.json"
    return {
        "anthropic": {
            "api_key": os.getenv("ORACLE_ANTHROPIC_API_KEY", "").strip(),
        },
        "claude_cli": {
            "bin": os.getenv("ORACLE_CLAUDE_BIN", "claude"),
            "authed": bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip()) or creds.exists(),
            "env": cli_env(),
        },
    }
