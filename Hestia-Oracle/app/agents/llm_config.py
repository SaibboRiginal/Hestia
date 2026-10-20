"""LLM provider infrastructure config — the single place that reads provider env.

Binaries and logins are infrastructure; provider keys are env secrets ``ORACLE_KEY_<NAME>``
(read by ``core.services.llm_providers``, which also holds names/addresses from Themis).
Provider classes receive the dict built there and never call ``os.getenv`` themselves.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Never handed to a `claude`/`codex` subprocess: an Anthropic API key in its env would switch
# Claude Code from the subscription to paid API billing (and expose the key to it); provider keys
# (ORACLE_KEY_*) are Oracle's secrets, not the agent's.
ANTHROPIC_KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
PROVIDER_KEY_PREFIX = "ORACLE_KEY_"


def cli_env() -> dict[str, str]:
    """Environment for a CLI subprocess: Oracle's env minus every API key."""
    return {k: v for k, v in os.environ.items()
            if k not in ANTHROPIC_KEY_VARS and not k.startswith(PROVIDER_KEY_PREFIX)}


def load_llm_config() -> dict[str, dict[str, Any]]:
    """Per provider type: its infrastructure config (binaries, logins, env)."""
    creds = Path.home() / ".claude" / ".credentials.json"
    return {
        "claude_cli": {
            "bin": os.getenv("ORACLE_CLAUDE_BIN", "claude"),
            "authed": bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip()) or creds.exists(),
            "env": cli_env(),
        },
    }
