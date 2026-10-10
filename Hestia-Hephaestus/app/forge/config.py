"""Forge configuration from env — infrastructure only (paths, repo, git identity, commands).

Tunables (engine, modes, fallback order, turn/timeout limits, auto merge/rollback/push, verify
delay) are central settings (forge_settings → Themis), read at use time. Kept here and why:
- enabled: the deployment can host Forge (repo + worktrees + docker socket mounted) — compose/infra.
- repo/worktrees/state/settings paths: container volumes.
- base_branch, git author: git identity of the checkout.
- test_cmd / deploy_cmd: shell commands executed verbatim in the container; they depend on the
  image tooling and are a code-execution surface, so they are not editable from clients.
- notify_target: owner's chat address (routing identity), shared with remediation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


ENGINE_ALIASES = {"builtin": "local", "ollama": "local", "claude_code": "claude"}

# Engine → permission group. Cloud-billed engines share the "cloud" mode.
ENGINE_GROUP = {"local": "local", "cloud": "cloud", "claude": "cloud"}


def normalize_engine(name: str) -> str:
    name = str(name or "").strip().lower()
    return ENGINE_ALIASES.get(name, name)


@dataclass(frozen=True)
class ForgeConfig:
    enabled: bool
    repo_path: Path
    worktrees_path: Path
    state_file: Path
    base_branch: str
    settings_file: Path         # Claude Pro schedule + budget state (runtime)
    test_cmd: str
    deploy_cmd: str
    notify_target: str
    hub_api_url: str
    git_author_name: str
    git_author_email: str


def load_forge_config() -> ForgeConfig:
    data_dir = Path(os.getenv("HEPHAESTUS_DATA_DIR", "/code/data"))
    return ForgeConfig(
        enabled=_bool("HEPHAESTUS_FORGE_ENABLED", True),
        repo_path=Path(os.getenv("HEPHAESTUS_REPO_PATH", "/repo")),
        # Shared with Oracle at the same absolute path (Claude Code runs there).
        worktrees_path=Path(os.getenv("HEPHAESTUS_WORKTREES_PATH", "/forge/worktrees")),
        state_file=Path(os.getenv("HEPHAESTUS_FORGE_STATE_FILE", str(data_dir / "forge" / "tasks.json"))),
        base_branch=os.getenv("HEPHAESTUS_FORGE_BASE_BRANCH", "").strip(),
        settings_file=Path(os.getenv("HEPHAESTUS_FORGE_SETTINGS_FILE", str(data_dir / "forge" / "settings.json"))),
        test_cmd=os.getenv(
            "HEPHAESTUS_FORGE_TEST_CMD",
            "python -m pytest -q -p no:cacheprovider -m \"unit or api or format\" {test_paths}"),
        deploy_cmd=os.getenv("HEPHAESTUS_FORGE_DEPLOY_CMD", "").strip(),
        notify_target=os.getenv("HEPHAESTUS_NOTIFY_TARGET", "").strip(),
        hub_api_url=os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/"),
        git_author_name=os.getenv("HEPHAESTUS_FORGE_GIT_NAME", "Hestia Forge"),
        git_author_email=os.getenv("HEPHAESTUS_FORGE_GIT_EMAIL", "forge@hestia.local"),
    )
