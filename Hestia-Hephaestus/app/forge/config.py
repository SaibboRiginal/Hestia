"""Forge configuration — every knob is an env var (Rulebook 1.4)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class ForgeConfig:
    enabled: bool
    repo_path: Path
    worktrees_path: Path
    state_file: Path
    base_branch: str
    engine: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    max_turns: int
    engine_timeout_seconds: int
    test_cmd: str
    claude_bin: str
    claude_model: str
    aider_bin: str
    aider_model: str
    auto_merge: bool
    deploy_cmd: str
    verify_delay_seconds: int
    auto_rollback: bool
    push_branch: bool
    notify_target: str
    hub_api_url: str
    git_author_name: str
    git_author_email: str


def load_forge_config() -> ForgeConfig:
    data_dir = Path(os.getenv("HEPHAESTUS_DATA_DIR", "/code/data"))
    return ForgeConfig(
        enabled=_bool("HEPHAESTUS_FORGE_ENABLED", True),
        repo_path=Path(os.getenv("HEPHAESTUS_REPO_PATH", "/repo")),
        worktrees_path=Path(os.getenv("HEPHAESTUS_WORKTREES_PATH", str(data_dir / "forge" / "worktrees"))),
        state_file=Path(os.getenv("HEPHAESTUS_FORGE_STATE_FILE", str(data_dir / "forge" / "tasks.json"))),
        base_branch=os.getenv("HEPHAESTUS_FORGE_BASE_BRANCH", "").strip(),
        engine=os.getenv("HEPHAESTUS_FORGE_ENGINE", "auto").strip().lower() or "auto",
        llm_base_url=os.getenv("HEPHAESTUS_FORGE_LLM_BASE_URL", "http://host.docker.internal:11434/v1").rstrip("/"),
        llm_model=os.getenv("HEPHAESTUS_FORGE_LLM_MODEL", "qwen2.5-coder:14b"),
        llm_api_key=os.getenv("HEPHAESTUS_FORGE_LLM_API_KEY", "ollama"),
        max_turns=max(5, _int("HEPHAESTUS_FORGE_MAX_TURNS", 40)),
        engine_timeout_seconds=max(60, _int("HEPHAESTUS_FORGE_ENGINE_TIMEOUT_SECONDS", 1800)),
        test_cmd=os.getenv(
            "HEPHAESTUS_FORGE_TEST_CMD",
            "python -m pytest -q -p no:cacheprovider -m \"unit or api or format\" {test_paths}"),
        claude_bin=os.getenv("HEPHAESTUS_FORGE_CLAUDE_BIN", "claude"),
        claude_model=os.getenv("HEPHAESTUS_FORGE_CLAUDE_MODEL", "").strip(),
        aider_bin=os.getenv("HEPHAESTUS_FORGE_AIDER_BIN", "aider"),
        aider_model=os.getenv("HEPHAESTUS_FORGE_AIDER_MODEL", "ollama_chat/qwen2.5-coder:14b"),
        auto_merge=_bool("HEPHAESTUS_FORGE_AUTO_MERGE", False),
        deploy_cmd=os.getenv("HEPHAESTUS_FORGE_DEPLOY_CMD", "").strip(),
        verify_delay_seconds=max(0, _int("HEPHAESTUS_FORGE_VERIFY_DELAY_SECONDS", 20)),
        auto_rollback=_bool("HEPHAESTUS_FORGE_AUTO_ROLLBACK", True),
        push_branch=_bool("HEPHAESTUS_FORGE_PUSH_BRANCH", False),
        notify_target=os.getenv("HEPHAESTUS_NOTIFY_TARGET", "").strip(),
        hub_api_url=os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/"),
        git_author_name=os.getenv("HEPHAESTUS_FORGE_GIT_NAME", "Hestia Forge"),
        git_author_email=os.getenv("HEPHAESTUS_FORGE_GIT_EMAIL", "forge@hestia.local"),
    )
