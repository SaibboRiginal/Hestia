from __future__ import annotations

from typing import Any

from .models import ConsentTier

try:
    from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase as llm_usecase
except ModuleNotFoundError:  # local runs without PYTHONPATH
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Hestia-Shared"))
    from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase as llm_usecase

# What Forge asks Oracle for: the built-in engine ``oracle`` walks this use case's chain
# (chosen by Marko in Oracle → Cervello → Modelli; a ``claude`` step there also sets Claude Code's model).
FORGE_USECASE = "forge.codice"
LLM_USECASES = [llm_usecase(FORGE_USECASE, "Forge · sviluppo", chain="codice",
                            help="The model that writes the code when Forge uses the Oracle engine."),
                llm_usecase("forge.revisione", "Forge · revisione automatica", chain="potente",
                            help="The independent reviewer that reads diff and tests before you approve."),
                llm_usecase("forge.piano", "Forge · divisione in pezzi", chain="potente",
                            help="Splits a big job into pieces and chooses for each one whether it is simple or hard."),
                llm_usecase("hephaestus.aggiornamenti", "What's new in an update", chain="veloce",
                            help="Rewrites in plain words what's new in a new version before asking whether to install it."),
                llm_usecase("hephaestus.setup", "First greeting of the setup", chain="veloce",
                            help="The message the assistant greets you with right after you chose the models in the setup.")]


def build_capabilities() -> dict[str, Any]:
    return {
        "runbook_first": True,
        "read_only_mvp": True,
        "self_healing_runbooks": True,
        "consent_tiers": [tier.value for tier in ConsentTier],
        "dry_run_default": True,
        "rollback_checkpoints": True,
        "production_execution_allowed": False,
        "module_tool_domains": ["system"],
        # Forge/remediation tools must reach Oracle for domain=system requests.
        "owns_tool_domains": ["system"],
        "endpoints": {
            "runbooks": "/api/hephaestus/runbooks",
            "diagnose": "/api/hephaestus/diagnose",
            "execute_preview": "/api/hephaestus/execute-preview",
            "status": "/api/hephaestus/status",
            "tasks": "/api/hephaestus/tasks",
            "remediate": "/api/hephaestus/remediate",
            "remediate_approve": "/api/hephaestus/remediate/{task_id}/approve",
            "remediate_rollback": "/api/hephaestus/remediate/{task_id}/rollback",
            "forge_status": "/api/hephaestus/forge/status",
            "forge_tasks": "/api/hephaestus/forge/tasks",
            "forge_approve": "/api/hephaestus/forge/tasks/{task_id}/approve",
        },
        "self_development": True,
        **llm_capabilities(LLM_USECASES),
        "downloads": {"endpoint": "/api/downloads"},   # the cloudflared image of «Fuori casa» (setup/tunnel.py)
    }
