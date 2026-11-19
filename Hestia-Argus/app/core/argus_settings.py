"""Argus settings declared to Themis (central settings).

Every tunable of the monitor (poll interval, log source, alert cooldown/batching,
auto-remediation, repair rechecks, Forge proposals, provider auth checks) lives here;
env keeps only secrets and infrastructure (Hub URL, base URL, port, docs path).
All values are read at use time (``settings.get``) → ``apply="live"``, except the
per-container log buffer size (deque allocated once per container).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:  # local run: shared package next to the module
    _shared_pkg = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.settings_client import SettingsClient, setting

POLL_INTERVAL = "argus.poll.interval"
LOG_SOURCE = "argus.logs.source"
HUB_LOG_LIMIT = "argus.logs.hub_limit"
SEEN_CACHE_SIZE = "argus.logs.seen_cache_size"
BUFFER_SIZE = "argus.logs.buffer_size"
BACKFILL_MINUTES = "argus.logs.backfill_minutes"
IGNORE_HEALTH_ACCESS = "argus.logs.ignore_health_access"
IGNORE_PATTERNS = "argus.logs.ignore_patterns"
ALERT_COOLDOWN = "argus.alerts.cooldown"
ALERT_BATCH_WINDOW = "argus.alerts.batch_window"
REMEDIATE_ENABLED = "argus.remediate.enabled"
REMEDIATE_DRY_RUN = "argus.remediate.dry_run"
REMEDIATE_ENVIRONMENT = "argus.remediate.environment"
REMEDIATE_TIMEOUT = "argus.remediate.timeout"
REPAIR_RECHECK = "argus.repair.recheck"
REPAIR_RECHECK_MAX = "argus.repair.recheck_max"
ORACLE_GRACE = "argus.oracle.grace"
REPAIR_RESTARTS = "argus.repair.max_restarts"
REPAIR_RESTART_AFTER = "argus.repair.restart_after"
AUTH_CHECK_ENABLED = "argus.auth_check.enabled"
AUTH_CHECK_EVERY = "argus.auth_check.every_cycles"
FORGE_ENABLED = "argus.forge.enabled"
FORGE_THRESHOLD = "argus.forge.threshold"
FORGE_WINDOW = "argus.forge.window"
FORGE_COOLDOWN = "argus.forge.cooldown"
PERF_EVERY = "argus.performance.every_cycles"
PERF_MEMORY_MB = "argus.performance.memory_mb"
PERF_CPU = "argus.performance.cpu_percent"
PERF_CPU_SAMPLES = "argus.performance.cpu_samples"
PERF_RESPONSE_MS = "argus.performance.response_ms"
STORAGE_DB_GB = "argus.storage.database_gb"
STORAGE_GROWTH_MB = "argus.storage.growth_mb_day"

_REMEDIATE_ON = {"key": REMEDIATE_ENABLED, "equals": True}
_AUTH_ON = {"key": AUTH_CHECK_ENABLED, "equals": True}
_FORGE_ON = {"key": FORGE_ENABLED, "equals": True}
_DOCKER = {"key": LOG_SOURCE, "equals": "docker"}

settings = SettingsClient("argus").follow_personal()      # owner language for fixed texts (i18n)
settings.declare([
    # ── Checks ──────────────────────────────────────────────────────────────
    setting(POLL_INTERVAL, "Check interval", "int", 60, group="Checks", min=10, max=3600, unit="s",
            order=0, help="Every how many seconds I check the modules' health and logs. Lower = faster notices."),
    setting(AUTH_CHECK_ENABLED, "Google/Outlook access check", "bool", True, group="Checks", order=1,
            help="Periodically checks that linked accounts work and tells you if they need to be signed in again."),
    setting(AUTH_CHECK_EVERY, "Access check frequency", "int", 5, group="Checks", min=1, max=1440,
            unit="cycles", order=2, depends_on=_AUTH_ON,
            help="Every how many check cycles I verify the accesses (5 cycles of 60 s = every 5 minutes)."),
    # ── Log ─────────────────────────────────────────────────────────────────
    setting(LOG_SOURCE, "Log source", "enum", "hub", group="Logs", advanced=True, order=10,
            options=[("hub", "Hub (recommended)"), ("docker", "Docker (direct reading of the containers)")],
            help="Where I read the module logs from. Docker needs access to the Docker socket."),
    setting(HUB_LOG_LIMIT, "Log lines per module", "int", 200, group="Logs", min=10, max=5000, advanced=True,
            order=11, help="How many log lines (warnings and errors) I read at most per module at each check."),
    setting(SEEN_CACHE_SIZE, "Memory of events already seen", "int", 5000, group="Logs", min=500, max=100000,
            advanced=True, order=12,
            help="How many log events I remember so as not to tell you twice about the same."),
    setting(IGNORE_HEALTH_ACCESS, "Ignore health checks in the logs", "bool", True, group="Logs", order=13,
            advanced=True, depends_on=_DOCKER,
            help="Discards the containers' /health access lines (only noise)."),
    setting(IGNORE_PATTERNS, "Texts to ignore in the logs", "list",
            ["OUTLOOK_CLIENT_ID and OUTLOOK_TENANT_ID must be set"], group="Logs", order=14, depends_on=_DOCKER,
            help="Log lines containing one of these texts do not create notices."),
    setting(BUFFER_SIZE, "Lines in memory per container", "int", 500, group="Logs", min=50, max=10000,
            advanced=True, apply="restart", order=15, depends_on=_DOCKER,
            help="How many log lines I keep in memory for each container."),
    setting(BACKFILL_MINUTES, "Past logs at startup", "int", 0, group="Logs", min=0, max=1440, unit="min",
            advanced=True, order=16, depends_on=_DOCKER,
            help="How many minutes of logs before startup I reread for each container (0 = none)."),
    # ── Alerts ──────────────────────────────────────────────────────────────
    setting(ALERT_COOLDOWN, "Pause between identical notices", "int", 60, group="Notices", min=1, max=10080, unit="min",
            order=20, help="After a notice about a module, for how long I don't repeat it."),
    setting(ALERT_BATCH_WINDOW, "Wait to group notices", "int", 20, group="Notices", min=0, max=3600,
            unit="s", order=21,
            help="I wait this long without new problems before sending you a single summary message."),
    # ── Automatic repair (safety: the assistant can only read) ───────
    setting(REMEDIATE_ENABLED, "Automatic repair", "bool", True, group="Repair", oracle="read",
            order=30, help="When a module stops I ask Hephaestus at once to repair it."),
    setting(REMEDIATE_DRY_RUN, "Simulation only", "bool", True, group="Repair", oracle="read", order=31,
            depends_on=_REMEDIATE_ON,
            help="Hephaestus prepares the repair but does not really run it."),
    setting(REMEDIATE_ENVIRONMENT, "Environment", "enum", "dev", group="Repair", oracle="read", order=32,
            options=[("dev", "Development"), ("staging", "alt::Test"), ("prod", "Production")], advanced=True,
            depends_on=_REMEDIATE_ON, help="Environment given to Hephaestus in repair requests."),
    setting(REMEDIATE_TIMEOUT, "Wait for a repair answer", "int", 15, group="Repair", min=1, max=300,
            unit="s", advanced=True, order=33, depends_on=_REMEDIATE_ON,
            help="How long I wait for Hephaestus when I ask it for a repair."),
    setting(REPAIR_RECHECK, "First recheck", "int", 10, group="Repair", min=1, max=1440, unit="min",
            order=34, help="After how long I check a stopped module again (then the time doubles at each attempt)."),
    setting(REPAIR_RECHECK_MAX, "Longest recheck", "int", 360, group="Repair", min=1, max=10080,
            unit="min", order=35, help="Longest time between two rechecks of a module that stays stopped."),
    setting(REPAIR_RESTARTS, "Automatic restarts", "int", 3, group="Repair", min=0, max=5, unit="times",
            order=37, depends_on=_REMEDIATE_ON,
            help="How many times I restart a stopped module by myself before giving up and telling you. 0 = never."),
    setting(REPAIR_RESTART_AFTER, "First restart after", "int", 120, group="Repair", min=30, max=3600,
            unit="s", order=38, depends_on=_REMEDIATE_ON,
            help="How long I wait for a stopped module before restarting it (a normal restart solves itself sooner); then the wait doubles at each attempt."),
    setting(ORACLE_GRACE, "Not available after", "int", 60, group="Repair", min=0, max=3600, unit="s",
            order=36, help="Seconds without Oracle before the «Not available» state and the notice: a shorter normal restart says nothing. Chat messages are queued anyway."),
    # ── Fix proposals to Forge (acts without the user → read only) ─
    setting(FORGE_ENABLED, "Fix proposals", "bool", True, group="Fix proposals",
            oracle="read", order=40,
            help="If the same error repeats, I ask Forge to fix the code (Forge respects the permissions you chose)."),
    setting(FORGE_THRESHOLD, "Repetitions before proposing", "int", 3, group="Fix proposals", min=1,
            max=100, order=41, depends_on=_FORGE_ON,
            help="How many times the same error must appear in the window before the proposal."),
    setting(FORGE_WINDOW, "Counting window", "int", 3600, group="Fix proposals", min=60,
            max=604800, unit="s", order=42, depends_on=_FORGE_ON, advanced=True,
            help="Period in which I count repetitions of the same error."),
    setting(FORGE_COOLDOWN, "Pause between identical proposals", "int", 86400, group="Fix proposals", min=60,
            max=2592000, unit="s", order=43, depends_on=_FORGE_ON, advanced=True,
            help="After a proposal for an error, for how long I don't repeat it."),
    # ── Performance (Cindy D16 + 25): thresholds of the performance alerts ──
    setting(PERF_EVERY, "Measurement frequency", "int", 5, group="Performance", min=1, max=1440, unit="cycles",
            order=50, help="Every how many check cycles I measure memory, processor and response times."),
    setting(PERF_MEMORY_MB, "Most memory per module", "int", 1500, group="Performance", min=50,
            max=65536, unit="MB", order=51, help="Above this memory used by a module I tell you."),
    setting(PERF_CPU, "Most processor per module", "int", 90, group="Performance", min=10, max=800,
            unit="%", order=52, help="Above this processor use (for several measurements in a row) I tell you."),
    setting(PERF_CPU_SAMPLES, "Measurements in a row above the limit", "int", 3, group="Performance", min=1, max=100,
            unit="measurements", order=53, advanced=True,
            help="How many consecutive measurements above the processor limit before the notice (a short peak does not count)."),
    setting(PERF_RESPONSE_MS, "Slow answer", "int", 3000, group="Performance", min=100, max=60000,
            unit="ms", order=54, help="If a module answers slower than this for several measurements in a row I tell you."),
    setting(STORAGE_DB_GB, "Largest data size", "int", 10, group="Performance", min=1, max=10000,
            unit="GB", order=55, help="When the saved data (database and files) exceed this size I tell you."),
    setting(STORAGE_GROWTH_MB, "Most growth per day", "int", 500, group="Performance", min=10,
            max=100000, unit="MB", order=56,
            help="If the saved data grow more than this in a day I tell you (usually an error that writes too much)."),
]).declare_log_level()


def get_int(key: str, minimum: int | None = None) -> int:
    """Effective int value (bad stored value → default), optionally floored."""
    try:
        value = int(settings.get(key))
    except (TypeError, ValueError):
        value = int(settings._defs[key]["default"])
    return max(minimum, value) if minimum is not None else value


def get_bool(key: str) -> bool:
    value = settings.get(key)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", ""}
    return bool(value)


def get_str(key: str) -> str:
    return str(settings.get(key) or settings._defs[key]["default"]).strip().lower()


def ignore_patterns() -> list[str]:
    raw = settings.get(IGNORE_PATTERNS) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(p).strip().lower() for p in raw if str(p).strip()]
