"""Hephaestus settings declared to Themis (central settings) — one file for the module.

Forge: pause switch, default engine, permission modes, fallback order, turn/timeout limits, merge/rollback/push
switches, verify delay, scheduler check interval. Remediation: execution timeout, approval
switches, retry policy. All live: read with ``settings.get`` at use time (engine/modes also via
``Forge._apply_settings``). ``data/forge/settings.json`` keeps only the Claude Pro schedule/state.
Env keeps infrastructure only (repo/worktree/data paths, base branch, git identity, deploy and
test commands, notify target, Forge on/off of the deployment) — see config.py.
"""
from __future__ import annotations

from ..core.shared_imports import import_shared_symbol

SettingsClient = import_shared_symbol("hestia_common.settings_client", "SettingsClient")
setting = import_shared_symbol("hestia_common.settings_client", "setting")

PAUSED = "hephaestus.forge.paused"
DEDUP_DAYS = "hephaestus.forge.dedup_days"
ENGINE = "hephaestus.forge.engine"
MODE = {"local": "hephaestus.forge.mode.local", "cloud": "hephaestus.forge.mode.cloud"}
FALLBACK = "hephaestus.forge.fallback"
MAX_TURNS = "hephaestus.forge.max_turns"
LLM_TIMEOUT = "hephaestus.forge.llm_timeout"
ENGINE_TIMEOUT = "hephaestus.forge.engine_timeout"
AUTO_MERGE = "hephaestus.forge.auto_merge"
AUTO_ROLLBACK = "hephaestus.forge.auto_rollback"
PUSH_BRANCH = "hephaestus.forge.push_branch"
VERIFY_DELAY = "hephaestus.forge.verify_delay"
SCHEDULER_INTERVAL = "hephaestus.forge.scheduler_interval"
TEAM_MIN_SERVICES = "hephaestus.forge.team.min_services"

REMEDIATE_TIMEOUT = "hephaestus.remediate.timeout"
REMEDIATE_REQUIRE_APPROVAL = "hephaestus.remediate.require_approval"
REMEDIATE_AUTO_APPROVE_NON_PROD = "hephaestus.remediate.auto_approve_non_prod"
REPAIR_RETRY_MINUTES = "hephaestus.remediate.retry_minutes"
REPAIR_MAX_ATTEMPTS = "hephaestus.remediate.max_attempts"
UPDATE_CHANNEL = "hephaestus.update.channel"

_ENGINES = [("oracle", "Oracle (chain «Forge · sviluppo»)"), ("claude", "Claude Code")]
_MODES = [("ask", "Always ask"), ("auto", "Develops by itself, the merge asks"),
          ("full_auto", "Everything by itself if the tests pass")]
_FORGE = "Development (Forge)"
_REPAIR = "Repairs"
_UPDATE = "Updates"

settings = SettingsClient("hephaestus").follow_personal()
settings.declare([
    # Manual brake, user only: the assistant can read it but never propose a change.
    setting(PAUSED, "Development paused", "bool", False, group=_FORGE, order=-1, oracle="read",
            help="If on, no development task starts by itself (Athena, Argus, repairs, Claude windows): they stay proposed quietly until you press Start. Your direct requests start anyway."),
    setting(DEDUP_DAYS, "No double proposals for", "int", 7, group=_FORGE, min=0, max=90, unit="days",
            order=-1,
            help="If a module proposes a task equal or very similar to one of the last days (even rejected) I don't create another. 0 = check off. Your requests are not filtered."),
    setting(ENGINE, "Default development engine", "enum", "oracle", group=_FORGE,
            options=_ENGINES, order=0,
            help="Who writes the code when you ask for a change. Oracle uses the chain of the use «Forge · sviluppo» (Oracle → Models). If it is not available the next one is used."),
    # Safety switches: the assistant can read them but never propose a change.
    setting(MODE["local"], "Permissions · local engine", "enum", "auto", group=_FORGE,
            options=_MODES, order=1, oracle="read",
            help="How much autonomy Forge has when Forge's chain uses only local (free) models."),
    setting(MODE["cloud"], "Permissions · cloud and Claude", "enum", "ask", group=_FORGE,
            options=_MODES, order=2, oracle="read",
            help="How much autonomy Forge has when it uses paid or pay-per-use engines."),
    setting(FALLBACK, "Order of backup engines", "list", ["oracle", "claude"], group=_FORGE,
            order=3, advanced=True,
            help="If the default engine is not available I try these, in order (oracle, claude)."),
    setting(MAX_TURNS, "Most steps per task", "int", 40, group=_FORGE, min=5, max=300, order=4,
            help="How many actions (reads, changes, tests) the engine can do before stopping."),
    setting(LLM_TIMEOUT, "Longest wait for a model answer", "int", 600, group=_FORGE,
            min=60, max=3600, unit="s", order=5, advanced=True,
            help="Local/cloud engines: how long I wait for each model answer before giving an error."),
    setting(ENGINE_TIMEOUT, "Longest Claude Code run", "int", 1800, group=_FORGE,
            min=60, max=14400, unit="s", order=6, advanced=True,
            help="Longest time of a Claude Code session on a task."),
    setting(AUTO_MERGE, "Default automatic merge", "bool", False, group=_FORGE, order=7, oracle="read",
            help="If on, tasks with no indication merge by themselves when the tests pass (always within the permissions)."),
    setting(AUTO_ROLLBACK, "Undo an unhealthy deploy by itself", "bool", True, group=_FORGE, order=8,
            oracle="read",
            help="After the deploy, if a service does not answer healthy, Forge undoes the merge and restarts."),
    setting(PUSH_BRANCH, "Publish the branch on the remote", "bool", False, group=_FORGE, order=9,
            oracle="read", advanced=True,
            help="Git-pushes the task branch to the remote (origin) after the tests."),
    setting(VERIFY_DELAY, "Wait before the health check", "int", 20, group=_FORGE,
            min=0, max=600, unit="s", order=10, advanced=True,
            help="After restarting the services I wait this long before checking their health."),
    setting(SCHEDULER_INTERVAL, "Claude window check", "int", 300, group=_FORGE,
            min=30, max=3600, unit="s", order=11, advanced=True,
            help="How often I check whether a task waiting for the Claude Pro window can start."),
    setting(TEAM_MIN_SERVICES, "Split into pieces the work that touches at least", "int", 3, group=_FORGE,
            min=1, max=20, unit="modules", order=12,
            help="A big job is split into pieces done one after the other, each with the right engine (simple pieces with the local model, hard ones with Claude), then reviewed all together."),
    setting(REMEDIATE_TIMEOUT, "Longest wait for a repair", "float", 25.0, group=_REPAIR,
            min=5, max=600, unit="s", order=20, advanced=True,
            help="How long I wait for the service when I run a maintenance action."),
    setting(REMEDIATE_REQUIRE_APPROVAL, "Ask confirmation for repairs", "bool", True, group=_REPAIR,
            order=21, oracle="read",
            help="If on, every repair that changes something (not simulated) waits for your ok."),
    setting(REMEDIATE_AUTO_APPROVE_NON_PROD, "Auto-approval outside production", "bool", False,
            group=_REPAIR, order=22, oracle="read",
            help="Lets requests auto-approve themselves in non-production environments."),
    setting(REPAIR_RETRY_MINUTES, "Wait between attempts", "int", 15, group=_REPAIR,
            min=1, max=1440, unit="min", order=23,
            help="After a failed repair I retry after this time × number of attempts."),
    setting(REPAIR_MAX_ATTEMPTS, "Most attempts", "int", 3, group=_REPAIR, min=1, max=20, order=24,
            help="After the last failed attempt the problem goes to Forge as a code fix."),
    setting(UPDATE_CHANNEL, "Which updates", "enum", "stabile", group=_UPDATE, order=30, oracle="read",
            options=[("stabile", "Published versions (recommended)"), ("novita", "Each piece of news as soon as it's ready")],
            help="Published versions: tested and with notes. Every news: the latest code, sooner but less tested. I always ask you before installing."),
]).declare_log_level()


def get_int(key: str, minimum: int) -> int:
    try:
        return max(minimum, int(settings.get(key)))
    except (TypeError, ValueError):
        return max(minimum, int(settings._defs[key]["default"]))


def get_float(key: str, minimum: float) -> float:
    try:
        return max(minimum, float(settings.get(key)))
    except (TypeError, ValueError):
        return max(minimum, float(settings._defs[key]["default"]))


def get_bool(key: str) -> bool:
    value = settings.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def fallback() -> list[str]:
    """Engine fallback order (normalized, unknown names dropped by ``select_engine``)."""
    from .config import normalize_engine
    raw = settings.get(FALLBACK)
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    out: list[str] = []
    for item in items:
        name = normalize_engine(item)
        if name and name not in out:
            out.append(name)
    return out
