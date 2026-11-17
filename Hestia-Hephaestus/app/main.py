from __future__ import annotations

import threading
import time
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from .api.hephaestus_router import create_hephaestus_router
from .core.remediation_service import RemediationService
from .core.service import HephaestusService
from .core.service_contract import ServiceDescriptor
from .core.service_runtime import load_runtime_config
from .core.webui_plugin import ui as webui_plugin
from .core.shared_imports import import_shared_symbol
from .forge.config import load_forge_config
from .forge.router import create_forge_router, create_repo_router
from .forge.service import Forge
from .forge import forge_settings
from .setup.router import create_setup_router
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

setup_service_logging = import_shared_symbol(
    "hestia_common.logging_utils",
    "setup_service_logging",
)

create_log_control_router = import_shared_symbol(
    "hestia_common.logging_utils",
    "create_log_control_router",
)

hub_health_url = import_shared_symbol(
    "hestia_common.startup_utils",
    "hub_health_url",
)

wait_for_http_ready = import_shared_symbol(
    "hestia_common.startup_utils",
    "wait_for_http_ready",
)

logger, log_buffer = setup_service_logging("hestia_hephaestus")
config = load_runtime_config()

service = HephaestusService(
    ServiceDescriptor(
        name=config.service_name,
        base_url=config.service_base_url,
        service_type=config.service_type,
        service_version=config.service_version,
        tags=config.service_tags,
        topology_tags=config.service_topology_tags,
    )
)

remediation_service = RemediationService(
    logger=logger,
    hub_api_url=config.hub_api_url,
    notify_target=config.hephaestus_notify_target,
    baseline_ref=config.hephaestus_baseline_ref,
    maintenance_paths=config.hephaestus_maintenance_paths,
)

forge = Forge(load_forge_config())
_update_agenda = import_shared_symbol("hestia_common.agenda_client", "AgendaClient")("hephaestus", config.hub_api_url)
_job_rule = import_shared_symbol("hestia_common.agenda_client", "job_rule")


def _escalate_to_forge(task: dict) -> str | None:
    """Runtime repair failed every attempt → code-fix task in Forge
    (Forge applies the user's permission mode: ask/auto/full_auto)."""
    if not forge.cfg.enabled:
        return None
    created = forge.submit(
        request=(f"Runtime remediation for service '{task.get('service')}' failed "
                 f"{task.get('attempts')} times (issue: {task.get('issue')}). "
                 "Find the root cause in the code, fix it, add a regression test."),
        services=[str(task.get("service") or "")] if task.get("service") else None,
        source="hephaestus.remediation", requested_by="hephaestus.remediation",
        context=str(task.get("execution_result") or "")[:3000])
    return created.get("id")


remediation_service.attach_agenda(forge.agenda, _escalate_to_forge)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    startup_wait_timeout = 0.0
    try:
        startup_wait_timeout = float(
            os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))
    except Exception:
        startup_wait_timeout = 0.0

    wait_for_http_ready(
        hub_health_url(config.hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )

    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info(
            "event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
            config.service_name,
            config.service_base_url,
        )
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s",
            error,
        )

    def _hub_keepalive() -> None:
        while True:
            time.sleep(60)
            try:
                service.register_to_hub(timeout_seconds=4)
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s",
                    error,
                )

    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()
    forge_settings.settings.start()
    _update_agenda.register_async([_job_rule(
        "hephaestus.update_check", tr("Look for Hestia updates"), service="hephaestus",
        path="/api/setup/update/daily", recurrence="FREQ=DAILY", start_at="2026-01-01T11:00:00",
        tz=os.getenv("TZ") or None, timeout_seconds=240,
        description="If there is a new version I ask you whether to install it (System → Updates).")])
    if forge.cfg.enabled:
        forge.start()
    yield


app = FastAPI(title="Hestia Hephaestus",
              version=config.service_version, lifespan=lifespan)
app.include_router(create_hephaestus_router(remediation_service, forge))
app.include_router(create_forge_router(forge))
app.include_router(forge_settings.settings.router())
app.include_router(create_repo_router(forge))
app.include_router(webui_plugin.router())   # GET /api/ui/manifest · GET /ui/webui/<file>
setup_router, setup_service = create_setup_router(   # guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click)
    forge.cfg.repo_path, Path(os.getenv("HEPHAESTUS_DATA_DIR", "/code/data")), config.hub_api_url,
    channel=lambda: str(forge_settings.settings.get(forge_settings.UPDATE_CHANNEL) or "stabile"),
    unhealthy=forge.unhealthy)
app.include_router(setup_router)
from .setup import tunnel as _tunnel  # noqa: E402
if _tunnel.downloads() is not None:
    app.include_router(_tunnel.downloads().router())   # /api/downloads (the cloudflared image, page Download)

# ─────────────────────────────────────────────────────────────────────
#  MCP tools
# ─────────────────────────────────────────────────────────────────────

try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    _hephaestus_mcp_tools = [
        # ── Macchine: central and satellites (docs/work/2026-10-30-setup-un-click §4.0) ──
        MCPTool(
            name="macchine_elenco", description=("The assistant's machines: this one and the satellites, on or off, with the modules running on "
                                                 "them."),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok"}, title="Machines", method="GET", path="/api/setup/machines",
            clients=["telegram", "ui"], response_mode="oracle_natural", telegram_visible=True,
            telegram_group="sistema", telegram={"section": "Machines", "label": "List"}),
        MCPTool(
            name="macchine_codice", description="A link code (10 minutes) to add a satellite: it is typed into the other machine's installation.",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok"}, title="Link a machine", method="POST",
            path="/api/setup/machines/pair", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Machines", "label": "alt::Link"}),
        MCPTool(
            name="macchine_scollega", description="Unlink a satellite (by id from the list): its modules leave.",
            parameters={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            handler=lambda **kw: {"status": "ok"}, title="Unlink a machine", method="POST",
            path="/api/setup/machines/revoke", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Machines", "label": "Unlink"}),
        MCPTool(
            name="macchine_cervello", description=(("Run the local models on a satellite's graphics card (address from the list); empty address = "
                                                    "back on this machine.")),
            parameters={"type": "object", "properties": {"address": {"type": "string"}, "name": {"type": "string"}}},
            handler=lambda **kw: {"status": "ok"}, title="Models on another machine", method="POST",
            path="/api/setup/machines/brain", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Machines", "label": "Brain"}),
        MCPTool(
            name="fuori_casa_stato", description="Can the assistant be reached from outside home? At which address.",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok"}, title="From outside home", method="GET", path="/api/setup/tunnel",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Machines", "label": "From outside home"}),
        MCPTool(
            name="fuori_casa_attiva", description=(("Turns on (on=true) or off (on=false) the address to use the assistant away from home; only when "
                                                    "the user asks explicitly.")),
            parameters={"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"]},
            handler=lambda **kw: {"status": "ok"}, title="Turn on or off from outside home", method="POST",
            path="/api/setup/tunnel", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Machines", "label": "Away from home on/off"}),
        MCPTool(
            name="aggiornamenti_stato", description="Installed version, whether a new one exists and what it brings.",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok"}, title="Updates", method="POST", path="/api/setup/update/check",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Updates", "primary": True}),
        MCPTool(
            name="aggiornamenti_installa", description=(("Install the new version (rolls back by itself if something does not answer); only when the user "
                                                         "asks explicitly.")),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok"}, title="Install the update", method="POST",
            path="/api/setup/update/apply", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Updates", "label": "Install"}),
        MCPTool(
            name="aggiornamenti_indietro", description="Go back to the version before the last update.",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok"}, title="Back to the previous version", method="POST",
            path="/api/setup/update/back", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema", telegram={"section": "Updates", "label": "Back"}),
        MCPTool(
            name="hephaestus_status",
            description="Show the state of the remediation engine",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "hephaestus_status", "params": kw},
            title="Repair status", method="GET", path="/api/hephaestus/status",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Repairs"}),
        MCPTool(
            name="hephaestus_tasks",
            description="List recent remediation tasks",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "hephaestus_tasks", "params": kw},
            title="Repairs", method="GET", path="/api/hephaestus/tasks",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Repairs"}),
        MCPTool(
            name="hephaestus_remediate",
            description="Create a policy-gated remediation task",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Request origin (argus/oracle/user)"},
                    "service": {"type": "string", "description": "Target service"},
                    "issue": {"type": "string", "description": "Incident detected"},
                    "severity": {"type": "string", "description": "warning|error|critical"},
                    "requested_action": {"type": "string", "description": "Requested action"},
                    "environment": {"type": "string", "description": "dev|staging|prod"},
                    "dry_run": {"type": "boolean", "description": "Dry-run execution"},
                    "auto_approve": {"type": "boolean", "description": "Policy-gated auto-approval"},
                },
                "required": ["service", "issue"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "hephaestus_remediate", "params": kw},
            title="Start repair", method="POST", path="/api/hephaestus/remediate",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Repairs"}),
        MCPTool(
            name="hephaestus_approve",
            description="Approve and run a pending remediation task",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task remediation ID"},
                    "approved_by": {"type": "string", "description": "Approving actor"},
                    "note": {"type": "string", "description": "Approval note"},
                },
                "required": ["task_id"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "hephaestus_approve", "params": kw},
            title="Approve repair", method="POST", path="/api/hephaestus/remediate/$task_id/approve",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Repairs"}),
        MCPTool(
            name="hephaestus_rollback",
            description=(("Undo a repair: if it had not started (or failed) it stops it; if it changed data the module "
                          "restores it; otherwise it answers there is nothing to restore.")),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task remediation ID"},
                    "requested_by": {"type": "string", "description": "Rollback actor"},
                    "reason": {"type": "string", "description": "Rollback reason"},
                },
                "required": ["task_id"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "hephaestus_rollback", "params": kw},
            title="Undo repair", method="POST", path="/api/hephaestus/remediate/$task_id/rollback",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Repairs"}),
        MCPTool(
            name="forge_develop",
            description=(
                ("The assistant develops itself: creates/changes/fixes its own code. Use when the user asks to "
                 "add a function, fix a bug, improve a service or a prompt. Works on an isolated branch, then "
                 "asks for approval.")
            ),
            parameters={
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "What to develop, in detail, in the user's words"},
                    "services": {"type": "array", "items": {"type": "string"}, "description": "Services involved if known (e.g. hecate, oracle)"},
                    "engine": {"type": "string", "description": "Only if the user asks: local | cloud | claude. Empty = default"},
                    "workdoc": {"type": "string", "description": "To CONTINUE a previous work: folder name docs/work/<...> (from the previous task)"},
                    "agenda_parent": {"type": "string", "description": "Key of the agenda item this development serves (cancelling it cancels the task)"},
                },
                "required": ["request"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "forge_develop", "params": kw},
            title="Develop {assistant}", method="POST", path="/api/hephaestus/forge/tasks",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            response_prompt="Confirm in 1-2 lines: task created (short id), engine, you will tell when ready.",
            telegram_visible=True, telegram_group="sviluppo",
                telegram={"section": "Jobs", "primary": 1}),
        MCPTool(
            name="forge_tasks",
            description="List the self-development (Forge) tasks and their state",
            parameters={"type": "object", "properties": {
                "state": {"type": "string", "description": "State filter: proposed, running, awaiting_review, deployed..."},
                "limit": {"type": "integer", "description": "Max tasks (default 50)"}}},
            handler=lambda **kw: {"status": "ok", "tool": "forge_tasks", "params": kw},
            title="Development jobs", method="GET", path="/api/hephaestus/forge/tasks/brief",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            response_prompt="Show ALL the rows of tasks, one per task: id, state, request. No JSON.",
            telegram_visible=True, telegram_group="sviluppo",
                telegram={"section": "Jobs", "primary": 2, "label": "Jobs"}),
        MCPTool(
            name="forge_status",
            description="State of the Forge engine: repo, engines available (Claude Code, Ollama), queue",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "forge_status", "params": kw},
            title="Development status", method="GET", path="/api/hephaestus/forge/status",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sviluppo",
                telegram={"section": "Jobs", "summary": True}),
        # Task detail, notes and "I fixed it on this branch" — also open to external AIs (MCP access, SPEC
        # docs/work/2026-10-18-moduli-core-e-mcp-esterno §B4). Approve/merge/rollback never leave the house.
        MCPTool(
            name="forge_task",
            description=("Detail of a development task: request, state, engine, error, tests, dossier (workdoc), branch, "
                         "notes, state history"),
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id (the first 6 characters are enough)"}},
                "required": ["task_id"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_task", "params": kw},
            title="Job detail", method="GET", path="/api/hephaestus/forge/tasks/$task_id/overview",
            clients=["ui", "external"], response_mode="oracle_natural", telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs"}),
        MCPTool(
            name="forge_task_diff",
            description="Full diff (git) produced by a development task",
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id"}}, "required": ["task_id"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_task_diff", "params": kw},
            title="Differences of a job", method="GET", path="/api/hephaestus/forge/tasks/$task_id/diff",
            clients=["ui", "external"], response_mode="raw_json", telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs", "label": "Differences"}),
        MCPTool(
            name="forge_dossier",
            description="SPEC, PROGRESS and CHANGELOG of a work dossier (docs/work/<name>), e.g. a task's workdoc",
            parameters={"type": "object", "properties": {
                "name": {"type": "string", "description": "Folder name in docs/work (the task's workdoc field)"}},
                "required": ["name"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_dossier", "params": kw},
            title="Work dossier", method="GET", path="/api/hephaestus/repo/dossiers/$name",
            clients=["ui", "external"], response_mode="raw_json", telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs", "label": "Dossier"}),
        MCPTool(
            name="forge_task_note",
            description=("Add an analysis or a hint to a development task (the owner sees it; the engine uses it when the "
                         "task starts or is retried)"),
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id"},
                "text": {"type": "string", "description": "Analysis, cause found, files to change, how to verify"}},
                "required": ["task_id", "text"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_task_note", "params": kw},
            title="Note on a job", method="POST", path="/api/hephaestus/forge/tasks/$task_id/notes",
            clients=["ui", "external"], response_mode="oracle_natural", telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs", "label": "Add note"}),
        MCPTool(
            name="forge_submit_branch",
            description=(
                ("Hand in a fix already made on a repo branch (origin): Forge fetches the branch, runs its tests "
                 "and asks the owner's approval as always; after the ok it merges, restarts, checks health and "
                 "rolls back by itself if something goes wrong. Task in state proposed, scheduled, failed, "
                 "no_changes or awaiting_review.")
            ),
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id (create it first with forge_develop if it does not exist)"},
                "branch": {"type": "string", "description": "Name of the branch on origin with the fix"},
                "summary": {"type": "string", "description": "What the branch changes and why"}},
                "required": ["task_id", "branch"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_submit_branch", "params": kw},
            title="Deliver a branch", method="POST",
            path="/api/hephaestus/forge/tasks/$task_id/submit-branch",
            clients=["ui", "external"], response_mode="oracle_natural", telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Advanced"}),
        # Manual brake: a direct user command (Telegram button / "metti in pausa lo sviluppo").
        MCPTool(
            name="forge_pause",
            description=(
                ("Pause or resume automatic development (Forge). While paused no task starts by itself: they stay "
                 "proposed until the user starts them. Use ONLY when the user asks ('pausa sviluppo', 'riprendi "
                 "sviluppo').")
            ),
            parameters={"type": "object", "properties": {
                "paused": {"type": "boolean", "description": "true = pause, false = resume"}},
                "required": ["paused"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_pause", "params": kw},
            title="Pause development", method="POST", path="/api/hephaestus/forge/pause",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="1 line: development paused or resumed; if resumed, held tasks still have to be started by hand.",
            telegram_visible=True, telegram_group="sviluppo",
                telegram={"section": "Development settings"}),
        # Default engine and permission modes are central settings (Themis): the assistant
        # proposes a change with settings_propose, the user confirms; no direct tool here.
        MCPTool(
            name="forge_set_claude_schedule",
            description=(
                ("Set when the assistant may use Claude Pro on its own: day/hour of the weekly reset, final hours "
                 "before the reset, night window, max tasks per night.")
            ),
            parameters={"type": "object", "properties": {
                "reset_day": {"type": "string", "description": "reset day: mon..sun"},
                "reset_time": {"type": "string", "description": "reset time HH:MM"},
                "window_hours": {"type": "integer", "description": "hours before the reset when Claude may be used at night (default 48)"},
                "night": {"type": "string", "description": "night window HH:MM-HH:MM (default 00:00-07:00)"},
                "night_max_tasks": {"type": "integer", "description": "max tasks per night (default 3)"},
                "final_hours": {"type": "integer", "description": "last hours when everything may be used (default 6)"}}},
            handler=lambda **kw: {"status": "ok", "tool": "forge_set_claude_schedule", "params": kw},
            title="Claude window", method="POST", path="/api/hephaestus/forge/settings/claude-schedule",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="2 lines: next reset, current window (phase/reason).",
            telegram_visible=True, telegram_group="sviluppo",
                telegram={"section": "Development settings"}),
        MCPTool(
            name="forge_settings",
            description="Show the development settings: default engine, fallback, permission mode local/cloud",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "forge_settings", "params": kw},
            title="Development settings", method="GET", path="/api/hephaestus/forge/settings",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sviluppo",
                telegram={"section": "Development settings"}),
        MCPTool(
            name="forge_approve",
            description=(
                ("Approve a Forge task: if 'proposed' it starts it, if 'awaiting_review' it applies the change "
                 "(merge/deploy). Use when the user says 'approva sviluppo <id>'.")
            ),
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id (the first 6 characters are enough)"},
                "now": {"type": "boolean", "description": "true only if the user says 'subito'/'ora' (skips Claude's night window)"},
                "engine": {"type": "string", "description": "Only if the user chooses who develops it: local | cloud | claude"}},
                "required": ["task_id"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_approve", "params": kw},
            title="Approve development", method="POST", path="/api/hephaestus/forge/tasks/$task_id/approve",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs", "primary": 3, "label": "Approve"}),
        MCPTool(
            name="forge_reject",
            description="Drop a proposed or in-review Forge task ('rifiuta <id>')",
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id"},
                "reason": {"type": "string", "description": "Reason"}}, "required": ["task_id"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_reject", "params": kw},
            title="Reject development", method="POST", path="/api/hephaestus/forge/tasks/$task_id/reject",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs", "label": "Reject"}),
        MCPTool(
            name="forge_rollback",
            description="Undo (git revert) a Forge change already applied ('rollback sviluppo <id>')",
            parameters={"type": "object", "properties": {
                "task_id": {"type": "string", "description": "Task id"},
                "reason": {"type": "string", "description": "Reason"}}, "required": ["task_id"]},
            handler=lambda **kw: {"status": "ok", "tool": "forge_rollback", "params": kw},
            title="Undo a release", method="POST", path="/api/hephaestus/forge/tasks/$task_id/rollback",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="sviluppo",
                telegram={"section": "Jobs"}),
    ]
    app.include_router(create_mcp_router(_hephaestus_mcp_tools, service_name="hephaestus"))
    logger.info("event=mcp_router_mounted service=hephaestus")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=hephaestus reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_hephaestus"))

@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": config.service_name,
        "version": config.service_version,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None) -> dict[str, Any]:
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_hephaestus",
        "count": len(rows),
        "logs": rows,
    }
