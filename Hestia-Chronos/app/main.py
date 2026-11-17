"""Hestia-Chronos — FastAPI entry point.

Provides a provider-agnostic HTTP API for calendar CRUD.
All endpoints are intended to be called through Hub routing; they are not
exposed to the outside world directly.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from core import archive_client
from core.hub_client import register_on_hub
from schemas.events import (
    CreateEventRequest,
    CreateEventResponse,
    DeleteEventRequest,
    ListEventsRequest,
    ListEventsResponse,
    UpdateEventRequest,
)
from services import agenda as assistant_agenda
from services import agenda_parse
from services import agenda_weather
from services import coach as weekly_coach
from services import notification_worker, sync_worker
from services import presence as assistant_presence
from core import presence_settings
from hestia_common.i18n import month_name, t as tr, weekday_name  # fixed texts in the owner's language

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import (
        hub_health_url,
        wait_for_http_ready,
        wait_for_hub_services,
    )
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import (
        hub_health_url,
        wait_for_http_ready,
        wait_for_hub_services,
    )

from hestia_common.plugin_client import PluginClient, page, quick_action, widget
from hestia_common import recap as recap_contract
from hestia_common.display import action, display, item
from services import day_view

logger, log_buffer = setup_service_logging("hestia_chronos")

UI_DIST = os.getenv("CHRONOS_UI_DIST", "/ui/dist")   # outside /code: the compose dev mount of app/ must not hide it
ui = PluginClient("chronos", title="Assistant agenda", icon="repeat", color="amber", kind="core", dist=UI_DIST,
                  description="What the assistant does on its own and when: runs, errors, rules, routines, special events.",
                  version=os.getenv("CALENDAR_SERVICE_VERSION", "1.0.0"))
ui.webui(entry="chronos.js", api_prefix="/api/agenda/",
         pages=[page("agenda", "{assistant}'s agenda", element="chronos-agenda", icon="calendar", order=150,
                     help="The assistant's calendar: events, tasks, jobs and windows of every module, in day, week, month or list view. Create, move, skip or cancel; your changes win over the modules."),
                page("week", "Your week", element="chronos-week", icon="calendar", order=149,
                     help="The week plan: workouts, routines and the rest placed in your free time, around the calendar commitments. Drag to move; your moves win."),
                page("runs", "Runs", element="chronos-runs", icon="repeat", order=151, parent="agenda",
                     help="Every run of the assistant's agenda jobs: succeeded, failed or skipped, how long it took, and the rules registered by every module."),
                page("standard", "Standard tasks", element="chronos-standard", icon="undo", order=152,
                     parent="agenda",
                     help="The activities the modules put in the agenda on their own (e.g. the evening recap), with their state: if you deleted, paused or changed one, «Restore» puts it back as planned. Below, the templates to add."),
                page("routine", "Routine", element="chronos-routines", icon="repeat", order=153,
                     help="What the assistant does on its own, written in words: at a time or when an email arrives. First it checks whether there is something new; the result arrives as a notification or in the evening recap."),
                page("events", "Special events", element="chronos-special", icon="star", order=154,
                     help="Birthdays, anniversaries and important dates with a notice a few days before. Your birthday comes from the personal settings, people's dates from People.")],
         widgets=[widget("today-in-plan", "Today in the plan", element="chronos-today-widget", sizes=["s", "m"],
                         auto=True, open_page="week", icon="calendar",
                         help="What is on today in the week plan, with the time."),
                  widget("failed", "Failed jobs", element="chronos-failed-widget", sizes=["s", "m"], auto=True,
                         open_page="runs", icon="alert",
                         help="Agenda jobs failed in the last 24 hours, with «Retry».")],
         quick_actions=[quick_action("retry", "Retry job", "POST", "/api/agenda/items/{id}/run", icon="refresh",
                                     group="System", source="/api/agenda/runs/failed", order=150)])


class ModuleMaintenanceRequest(BaseModel):
    source: str = "oracle"
    task_id: str | None = None
    issue: str | None = None
    requested_action: str | None = "reconcile_calendar"
    environment: str = "dev"
    dry_run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModuleMaintenanceResponse(BaseModel):
    status: str
    service: str
    dry_run: bool
    task_id: str
    executed_at: datetime
    retriable: bool
    summary: str
    mutation_count: int
    details: dict[str, Any]

# ─────────────────────────────────────────────────────────────────────
#  App bootstrap
# ─────────────────────────────────────────────────────────────────────


app = FastAPI(title="Hestia Chronos", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(ui.router())   # GET /api/ui/manifest · GET /ui/webui/chronos.js
import life_api  # noqa: E402 — routines, special events, smart calendar, manual presence (brainstorm W2)
app.include_router(life_api.router)

# ── export / import (hestia_common.transfer): the user's own agenda decisions ────────────────────────────
from hestia_common.transfer import Transfer
from services.agenda_transfer import AgendaSection

transfer = Transfer("chronos", sections=[AgendaSection()])
app.include_router(transfer.router())

# ─────────────────────────────────────────────────────────────────────
#  MCP tools
# ─────────────────────────────────────────────────────────────────────

try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    _chronos_mcp_tools = [
        MCPTool(
            name="agenda",
            description="Show the events in the agenda (next 7 days by default; days = how many)",
            parameters={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days ahead to look (default 7)"},
                    "source": {"type": "string", "description": "Filter by source: google, outlook, hestia, ..."},
                    "kind": {"type": "string", "description": "Filter by kind: event, task, reminder"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "agenda", "params": kw},
            title="Agenda", method="GET", path="/api/calendar/agenda",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                ("Show the agenda events readably and in order: title, date/time, place (if any) and a short "
                 "description for each. Group by day. Friendly and brief.")
            ),
            telegram_visible=True, telegram_group="day",
                telegram={"section": "Agenda", "primary": 1, "label": "Agenda"}),
        MCPTool(
            name="agenda_today",
            description="Show today's events",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_today", "params": kw},
            title="Today's agenda", method="GET", path="/api/calendar/agenda/today",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Show today's events briefly. If there are none, say so clearly."
            ),
            telegram_visible=True, telegram_group="day",
                telegram={"section": "Agenda", "summary": True, "label": "Today"}),
        MCPTool(
            name="create_event",
            description=("Create a new event in the connected calendar (Google Calendar, Outlook). Use for: create an "
                         "event, add an appointment, set a reminder, plan a meeting."),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title or name of the event"},
                    "start_datetime": {"type": "string", "description": "Start date and time, ISO 8601 (YYYY-MM-DDTHH:MM:SS)"},
                    "end_datetime": {"type": "string", "description": "End date and time, ISO 8601"},
                    "description": {"type": "string", "description": "Description or extra notes of the event"},
                    "location": {"type": "string", "description": "Physical or virtual place of the event"},
                    "provider": {"type": "string", "description": "Calendar: google, outlook (empty = default)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (empty = main)"},
                },
                "required": ["title", "start_datetime"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "create_event", "params": kw},
            title="New event", method="POST", path="/api/calendar/events",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                ("Confirm the event was created, short and natural: title, start date/time; mention the link or "
                 "id if the provider returned one.")
            ),
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Calendar", "primary": 4}),
        MCPTool(
            name="calendar_list_events",
            description="List the events in a time range per calendar provider.",
            parameters={
                "type": "object",
                "properties": {
                    "start_datetime": {"type": "string", "description": "Start of the range, ISO 8601"},
                    "end_datetime": {"type": "string", "description": "End of the range, ISO 8601"},
                    "target_providers": {"type": "array", "items": {"type": "string"}, "description": "Target providers"},
                    "calendar_id": {"type": "string", "description": "Calendar ID"},
                    "max_results": {"type": "integer", "description": "Max results"},
                },
                "required": ["start_datetime", "end_datetime"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_list_events", "params": kw},
            title="Events in a period", method="POST", path="/api/calendar/events/list",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Calendar"}),
        MCPTool(
            name="calendar_update_event",
            description="Update fields of an existing calendar event.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                    "provider": {"type": "string", "description": "Calendar provider"},
                    "calendar_id": {"type": "string", "description": "Calendar ID"},
                    "updates": {"type": "object", "description": "Fields to update"},
                },
                "required": ["event_id", "provider"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_update_event", "params": kw},
            title="Edit event", method="PATCH", path="/api/calendar/events/$arg.event_id",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Calendar"}),
        MCPTool(
            name="calendar_delete_event",
            description="Delete an existing calendar event.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                    "provider": {"type": "string", "description": "Calendar provider"},
                    "calendar_id": {"type": "string", "description": "Calendar ID"},
                },
                "required": ["event_id", "provider"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_delete_event", "params": kw},
            title="Delete event", method="DELETE", path="/api/calendar/events/$arg.event_id",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Calendar"}),
        MCPTool(
            name="chronos_reconcile",
            description="Run reconciliation maintenance in the Chronos module",
            parameters={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "If true only simulates, without running the worker ticks"},
                    "requested_action": {"type": "string", "description": "Optional action: reconcile_calendar|sync|notify|full"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "chronos_reconcile", "params": kw},
            title="Reconcile calendar", method="POST", path="/api/module/maintenance/reconcile",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Summarise the Chronos reconciliation result: which ticks ran and whether it was a dry run.",
            telegram_visible=True, telegram_group="day",
                telegram={"section": "Advanced"}),
        MCPTool(
            name="agenda_assistant",
            description=(
                ("The assistant's own agenda (NOT the user's calendar): what the assistant and its modules "
                 "planned — windows (e.g. Claude Pro at night), periodic jobs, repair tasks, events.")
            ),
            parameters={"type": "object", "properties": {
                "days": {"type": "integer", "description": "days ahead (default 7)"},
                "owner": {"type": "string", "description": "module: hephaestus, scout, athena..."}}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant", "params": kw},
            title="Assistant agenda", method="GET", path="/api/agenda",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(("Chronological list grouped by day: time, title, module. Mark skipped occurrences. No JSON. Show "
                              "the id in brackets.")),
            telegram_visible=True, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_add",
            description="Add an event/task/window/job to the assistant's own agenda (on demand)",
            parameters={"type": "object", "properties": {
                "title": {"type": "string", "description": "title"},
                "type": {"type": "string", "description": "event | task | job | window"},
                "start_at": {"type": "string", "description": "ISO 8601 start"},
                "end_at": {"type": "string", "description": "ISO end (required for window)"},
                "recurrence": {"type": "string", "description": "RRULE if recurring, e.g. FREQ=WEEKLY;BYDAY=SA"},
                "description": {"type": "string", "description": "details"},
                "parent": {"type": "string", "description": "key of the linked item (cascading cancel)"}},
                "required": ["title", "start_at"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_add", "params": kw},
            title="Schedule for the assistant", method="POST", path="/api/agenda/items",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda", "label": "alt::Plan"}),
        MCPTool(
            name="agenda_assistant_move",
            description="Move/edit an item of the assistant's own agenda (new time, recurrence, pause)",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the item"},
                "start_at": {"type": "string", "description": "new ISO start"},
                "end_at": {"type": "string", "description": "new ISO end"},
                "recurrence": {"type": "string", "description": "new RRULE"},
                "status": {"type": "string", "description": "confirmed | paused"}},
                "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_move", "params": kw},
            title="Move an entry", method="PATCH", path="/api/agenda/items/{ref}",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_skip",
            description=("Skip (dismiss) the next occurrence of an item of the assistant's own agenda, without deleting "
                         "the rule"),
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the item"},
                "occurrence": {"type": "string", "description": "ISO occurrence (empty = next)"}},
                "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_skip", "params": kw},
            title="Skip once", method="POST", path="/api/agenda/items/{ref}/skip",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_restore",
            description="Restore a skipped occurrence of an item of the assistant's own agenda",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the item"},
                "occurrence": {"type": "string", "description": "skipped ISO occurrence"}},
                "required": ["ref", "occurrence"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_restore", "params": kw},
            title="Restore once", method="POST", path="/api/agenda/items/{ref}/unskip",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_standard",
            description=(("The assistant's standard activities (the modules' defaults, e.g. the evening recap) with their "
                          "state: active, changed, paused, deleted, failed; plus the templates to add more. Use it when "
                          "the user wants back something removed from the calendar.")),
            parameters={"type": "object", "properties": {
                "owner": {"type": "string", "description": "only the activities of this area (empty = all)"}}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_standard", "params": kw},
            title="Standard tasks", method="GET", path="/api/agenda/standard",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_standard_restore",
            description=(("Put a standard activity back as its module defines it (reactivates a deleted or paused "
                          "activity, undoes changes). 'key' from the agenda_standard list.")),
            parameters={"type": "object", "properties": {
                "key": {"type": "string", "description": "key of the standard activity"}},
                "required": ["key"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_standard_restore", "params": kw},
            title="Restore standard tasks", method="POST",
            path="/api/agenda/standard/{key}/restore",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_move_occurrence",
            description=(("Move ONLY one occurrence of a recurring item (an exception, like 'only this event'); reset=true "
                          "puts it back at the original time")),
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the item"},
                "occurrence": {"type": "string", "description": "original ISO occurrence"},
                "start_at": {"type": "string", "description": "new ISO start"},
                "end_at": {"type": "string", "description": "new ISO end"},
                "reset": {"type": "boolean", "description": "restore the original time"}},
                "required": ["ref", "occurrence"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_move_occurrence", "params": kw},
            title="Move once", method="POST", path="/api/agenda/items/{ref}/move",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_templates",
            description=(("Templates the modules offer to create items (e.g. Scout: periodic real estate search). Use it "
                          "before agenda_assistant_from_template")),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_templates", "params": kw},
            title="Agenda templates", method="GET", path="/api/agenda/templates",
            clients=["ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_from_template",
            description="Create an item of the assistant's own agenda from a module template (fields in values)",
            parameters={"type": "object", "properties": {
                "owner": {"type": "string", "description": "module of the template"},
                "template_id": {"type": "string", "description": "template id"},
                "values": {"type": "object", "description": "template fields"},
                "start_at": {"type": "string", "description": "ISO start"},
                "end_at": {"type": "string", "description": "ISO end (windows)"},
                "recurrence": {"type": "string", "description": "RRULE if recurring"}},
                "required": ["owner", "template_id", "start_at"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_from_template", "params": kw},
            title="Create from template", method="POST", path="/api/agenda/templates/{owner}/{template_id}/create",
            clients=["ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_link",
            description=("Link an item to a parent item: cancelling the parent cancels the child, a child's error marks "
                         "the parent"),
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the child item"},
                "parent": {"type": "string", "description": "parent key (empty = unlink)"}},
                "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_link", "params": kw},
            title="Link entries", method="POST", path="/api/agenda/items/{ref}/link",
            clients=["ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_cancel",
            description="Cancel an item of the assistant's own agenda for good",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the item"}}, "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_cancel", "params": kw},
            title="Undo an entry", method="DELETE", path="/api/agenda/items/{ref}",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="agenda_assistant_run",
            description="Run now the action of a job/task of the assistant's own agenda",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id or key of the item"}}, "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistant_run", "params": kw},
            title="alt::Run now", method="POST", path="/api/agenda/items/{ref}/run",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Assistant agenda"}),
        MCPTool(
            name="presence_status",
            description=(("The assistant's activity state: awake, waiting, nap, deep sleep, do not disturb (+ "
                          "busy/tired…), last interaction, work in progress and effects (what is allowed now). Use it when "
                          "the user asks how you are, what you are doing, how long since you last talked.")),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "presence_status", "params": kw},
            title="Assistant status", method="GET", path="/api/presence",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                ("Describe the assistant's state in 2-4 lines in the first person: label, since when, last "
                 "interaction (client and how long ago), work in progress (activities) and, if relevant, what is "
                 "put off (effects with defer/save). No JSON, no technical keys.")),
            telegram_visible=True, telegram_group="system",
                telegram={"section": "Assistant", "primary": 1, "label": "Status"}),
        MCPTool(
            name="presence_dnd_on",
            description=(("Turn on «Do not disturb»: only urgent notifications get through. minutes = duration (empty = default), until = until an ISO 8601 time.")),
            parameters={"type": "object", "properties": {
                "minutes": {"type": "integer", "description": "Duration in minutes (empty = default)"},
                "until": {"type": "string", "description": "Until when, ISO 8601"}}},
            handler=lambda **kw: {"status": "ok", "tool": "presence_dnd_on", "params": kw},
            title="Do not disturb", method="POST", path="/api/presence/dnd",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Confirm in one line that «Do not disturb» is on and until when (dnd_until, local time).",
            telegram_visible=True, telegram_group="system",
                telegram={"section": "Assistant", "primary": 2}),
        MCPTool(
            name="presence_dnd_off",
            description="Turn off «Do not disturb».",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "presence_dnd_off", "params": kw},
            title="Remove do not disturb", method="DELETE", path="/api/presence/dnd",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Confirm in one line that «Do not disturb» is off and say the new state (label).",
            telegram_visible=True, telegram_group="system",
                telegram={"section": "Assistant"}),
        # ── Weekly coach plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §6) ──
        MCPTool(
            name="coach_week",
            description=(("The user's week plan: workouts, routines and the rest placed in their free time, goals, what does not fit and why. Use it for «what do I have planned this week», «when do I train», «how is the plan».")),
            parameters={"type": "object", "properties": {
                "date": {"type": "string", "description": "a day of the wanted week YYYY-MM-DD (empty = this one)"}}},
            handler=lambda **kw: {"status": "ok", "tool": "coach_week", "params": kw},
            title="Weekly plan", method="GET", path="/api/agenda/coach/week",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(("Summarise the plan by day: time and what (short version if given). Then, if any, what does not "
                              "fit and why, and the goals. Brief, no JSON, no module names. Show the key in brackets only if "
                              "the user wants to move something.")),
            telegram_visible=True, telegram_group="day",
                telegram={"section": "Weekly plan", "primary": 6, "label": "Week plan"}),
        MCPTool(
            name="coach_replan",
            description=(("Redo the plan from the given day to the end of the week. busy = periods to keep free before "
                          "redoing it (e.g. a trip on Wednesday and Thursday).")),
            parameters={"type": "object", "properties": {
                "date": {"type": "string", "description": "first day YYYY-MM-DD (empty = today)"},
                "busy": {"type": "array", "description": "busy periods",
                         "items": {"type": "object", "properties": {
                             "start_at": {"type": "string", "description": "ISO 8601 start"},
                             "end_at": {"type": "string", "description": "ISO 8601 end"},
                             "title": {"type": "string", "description": "e.g. Trasferta"}}}}}},
            handler=lambda **kw: {"status": "ok", "tool": "coach_replan", "params": kw},
            title="Redo the plan", method="POST", path="/api/agenda/coach/replan",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Say in 2-3 lines what is in the plan of the next days now and what does not fit.",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Weekly plan"}),
        MCPTool(
            name="coach_move",
            description="Move an item of the week plan (key from coach_week) to another day/time.",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "key of the plan item"},
                "start_at": {"type": "string", "description": "new ISO 8601 start"},
                "end_at": {"type": "string", "description": "new ISO 8601 end (empty = same duration)"}},
                "required": ["ref", "start_at"]},
            handler=lambda **kw: {"status": "ok", "tool": "coach_move", "params": kw},
            title="Move in the plan", method="POST", path="/api/agenda/coach/items/{ref}/move",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Weekly plan"}),
        MCPTool(
            name="coach_skip",
            description="Skip an item of the week plan; the rest of the week is replanned.",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "key of the plan item"},
                "reason": {"type": "string", "description": "why (optional)"}}, "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "coach_skip", "params": kw},
            title="Skip in the plan", method="POST", path="/api/agenda/coach/items/{ref}/skip",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Weekly plan"}),
        MCPTool(
            name="coach_add_busy",
            description="Mark a period when the user is away or busy, so the plan keeps it free.",
            parameters={"type": "object", "properties": {
                "start_at": {"type": "string", "description": "ISO 8601 start"},
                "end_at": {"type": "string", "description": "ISO 8601 end"},
                "title": {"type": "string", "description": "e.g. Trasferta"}}, "required": ["start_at", "end_at"]},
            handler=lambda **kw: {"status": "ok", "tool": "coach_add_busy", "params": kw},
            title="Commitment for the plan", method="POST", path="/api/agenda/coach/busy",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Weekly plan"}),
        MCPTool(
            name="coach_review",
            description="How last week went against the plan: done, skipped, notes of each area.",
            parameters={"type": "object", "properties": {
                "date": {"type": "string", "description": "a day of the week AFTER the one to review"}}},
            handler=lambda **kw: {"status": "ok", "tool": "coach_review", "params": kw},
            title="How the week went", method="GET", path="/api/agenda/coach/review",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="2-4 lines: what went well, what was skipped. No JSON, no module names.",
            telegram_visible=False, telegram_group="day",
                telegram={"section": "Weekly plan"}),
    ]
    import life_api as _life_api
    _chronos_mcp_tools += _life_api.mcp_tools()     # routines, special events, smart calendar, manual presence
    app.include_router(create_mcp_router(_chronos_mcp_tools, service_name="chronos"))
    logger.info("event=mcp_router_mounted service=chronos")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=chronos reason=hestia_common_not_available")

# ─────────────────────────────────────────────────────────────────────


def _route_hecate(
    *,
    method: str,
    path: str,
    query: dict | None = None,
    body: dict | None = None,
    timeout_seconds: float = 20.0,
) -> tuple[int, dict]:
    import requests

    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    response = requests.post(
        f"{hub_api_url}/route/hecate/{path.lstrip('/')}",
        json={
            "method": method,
            "headers": {},
            "query": query or {},
            "body": body,
            "timeout_seconds": timeout_seconds,
        },
        timeout=max(5.0, timeout_seconds + 2.0),
    )
    response.raise_for_status()
    routed = response.json() if response.content else {}
    return int((routed or {}).get("status_code", 500)), (routed or {}).get("payload") or {}

# ─────────────────────────────────────────────────────────────────────
#  Lifecycle
# ─────────────────────────────────────────────────────────────────────


@app.on_event("startup")
def on_startup() -> None:
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api"
    ).rstrip("/")
    service_base_url = os.getenv(
        "CALENDAR_SERVICE_BASE_URL", "http://hestia_chronos:19007"
    )

    startup_wait_timeout = float(
        os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))
    wait_for_http_ready(
        hub_health_url(hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )
    wait_for_hub_services(
        hub_api_url,
        ["archive"],
        timeout_seconds=startup_wait_timeout,
        logger=logger,
    )

    register_on_hub(hub_api_url, service_base_url, extra_capabilities={**ui.capabilities(service_base_url), **recap_contract.capabilities(), **transfer.capabilities()})
    # Periodically re-register with Hub so a Hub restart doesn't lose this service.

    def _hub_keepalive():
        while True:
            time.sleep(60)
            try:
                register_on_hub(
                    hub_api_url,
                    service_base_url,
                    max_attempts=1,
                    quiet_success=True,
                    extra_capabilities={**ui.capabilities(service_base_url), **recap_contract.capabilities(), **transfer.capabilities()},
                )
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed [HUB] Keepalive registration failed: %s", error)
    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()

    # Start the proactive notification worker (background daemon thread).
    notification_worker.start()
    # Start the calendar sync worker (pulls events from Hecate into Archive).
    sync_worker.start()
    assistant_agenda.start_worker()
    # Assistant presence (SPEC assistant-presence): settings from Themis, state from Archive,
    # night window in the agenda, re-evaluated after every agenda tick.
    presence_settings.settings.on_change(lambda changed: assistant_presence.get_engine().evaluate("settings"))
    presence_settings.settings.on_change(_on_personal_change)
    presence_settings.settings.start()
    threading.Thread(target=_presence_boot, daemon=True, name="presence-boot").start()
    assistant_agenda.on_tick(lambda: assistant_presence.get_engine().evaluate("tick"))


def _life_boot() -> None:
    """Mail routines re-subscribe to Iris; the owner's birthday follows ``themis.personal.birth_date``."""
    from services import routines, smart_calendar, special
    routines.refresh_mail_subscriptions()
    routines.load_results()
    smart_calendar.load_kept()
    try:
        special.sync_birthday(presence_settings.settings.get(special.BIRTH_SETTING))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=special_birthday_sync_failed error=%s", exc)


def _on_personal_change(changed: dict) -> None:
    from services import special
    if special.BIRTH_SETTING in (changed or {}):
        try:
            special.sync_birthday(changed[special.BIRTH_SETTING])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=special_birthday_sync_failed error=%s", exc)


def _presence_boot() -> None:
    """Load signals/snapshot and register the night window (retry: never block startup)."""
    from hestia_common.agenda_client import daily_window
    engine, loaded, registered = assistant_presence.get_engine(), False, False
    for attempt in range(30):
        loaded = loaded or engine.load()
        if not registered:
            try:
                assistant_agenda.register_rules("chronos", [daily_window(
                    presence_settings.SLEEP_WINDOW, "{assistant}: night (deep sleep)", 1, 7,
                    description="At night the assistant goes into deep sleep: heavy jobs allowed, only urgent notifications. Move or skip to change the night."),
                    weekly_coach.week_job_rule(), *life_api.boot_rules()])
                registered = True
                _life_boot()
            except Exception as exc:
                logger.warning("[🔄] event=presence_window_register_failed attempt=%d error=%s", attempt + 1, exc)
        if loaded and registered:
            break
        time.sleep(min(60, 5 * (attempt + 1)))
    engine.evaluate("boot")


# ─────────────────────────────────────────────────────────────────────
#  Health
# ─────────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    # Calendar providers are informative: Hecate down must not make Chronos (agenda, presence) look down.
    try:
        status_code, status_payload = _route_hecate(
            method="GET",
            path="/api/gateway/providers",
            timeout_seconds=10,
        )
    except Exception:
        status_code, status_payload = 503, {}
    return {
        "status": "ok",
        "service": "hestia_chronos",
        "providers": status_payload if status_code < 400 else {},
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_chronos",
        "count": len(rows),
        "logs": rows,
    }

app.include_router(create_log_control_router("hestia_chronos"))

def _recap_with_life(day, nxt) -> dict:
    """Agenda facts + routine results kept for the recap + today's special moments."""
    from services import routines, special
    facts = day_view.recap(day, nxt)
    for r in routines.recap_lines(datetime(day.year, day.month, day.day, tzinfo=timezone.utc)):
        facts["done"].append({"text": f"{r['title']}: {r['text'][:400]}"})
    try:
        for s in special.list_special(nxt):
            if s["in_days"] == 0:
                facts["next"].insert(0, {"text": f"{s['title']}", "tone": "success"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=recap_special_failed error=%s", exc)
    return facts


# Daily recap piece (docs/work/2026-10-20-recap-giornaliero): the user's events, assistant tasks, failed jobs.
app.include_router(recap_contract.recap_router(
    "chronos", lambda day, nxt: recap_contract.piece("chronos", tr("Agenda"), icon="calendar", emoji="📅", order=10,
                                                     **_recap_with_life(day, nxt))))
app.include_router(presence_settings.settings.router())

# ─────────────────────────────────────────────────────────────────────
#  Calendar endpoints
# ─────────────────────────────────────────────────────────────────────


@app.post("/api/calendar/events", response_model=CreateEventResponse)
def create_event(req: CreateEventRequest) -> CreateEventResponse:
    body = req.model_dump(mode="json")
    status_code, payload = _route_hecate(
        method="POST",
        path="/api/gateway/calendar/events",
        body=body,
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return CreateEventResponse.model_validate(payload)


@app.post("/api/calendar/events/list", response_model=ListEventsResponse)
def list_events(req: ListEventsRequest) -> ListEventsResponse:
    provider = req.target_providers[0] if req.target_providers else None
    query = {
        "start_datetime": req.start_datetime.isoformat(),
        "end_datetime": req.end_datetime.isoformat(),
        "provider": provider,
        "calendar_id": req.calendar_id,
        "max_results": req.max_results,
    }
    status_code, payload = _route_hecate(
        method="GET",
        path="/api/gateway/calendar/events",
        query=query,
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return ListEventsResponse.model_validate(payload)


@app.delete("/api/calendar/events/{event_id}")
def delete_event(event_id: str, req: DeleteEventRequest) -> JSONResponse:
    status_code, payload = _route_hecate(
        method="DELETE",
        path=f"/api/gateway/calendar/events/{event_id}",
        query={"provider": req.provider, "calendar_id": req.calendar_id},
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return JSONResponse(payload)


@app.patch("/api/calendar/events/{event_id}")
def update_event(event_id: str, req: UpdateEventRequest) -> JSONResponse:
    status_code, payload = _route_hecate(
        method="PUT",
        path=f"/api/gateway/calendar/events/{event_id}",
        body=req.model_dump(mode="json"),
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return JSONResponse(payload)


@app.get("/api/calendar/providers")
def list_providers() -> dict:
    status_code, payload = _route_hecate(
        method="GET",
        path="/api/gateway/providers",
        timeout_seconds=10,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return payload


@app.post("/api/calendar/providers/{provider}/refresh")
def refresh_provider(provider: str) -> dict:
    status_code, payload = _route_hecate(
        method="POST",
        path=f"/api/gateway/auth/refresh/{provider}",
        body={},
        timeout_seconds=15,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return payload


@app.get("/api/calendar/agenda")
def get_agenda(
    days: int = Query(
        7, ge=1, le=90, description="How many days ahead to look"),
    source: str | None = Query(
        None, description="Filter by source: google, outlook, hestia, …"),
    kind: str | None = Query(
        None, description="Filter by kind: event, task, reminder"),
) -> dict:
    """Return upcoming calendar items from Archive for the requested window.

    This endpoint is used by Telegram commands (``/agenda``, ``/agenda_today``)
    and by Oracle when the user asks about their schedule.
    """
    # Window starts at local midnight: "today's agenda" used to start at "now",
    # hiding events already started today and all-day events (stored 00:00).
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(assistant_agenda._TZ_DEFAULT)
    now = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    to_time = now + timedelta(days=days)
    items = archive_client.list_items(
        from_time=now.isoformat(),
        to_time=to_time.isoformat(),
        source=source,
        kind=kind,
        limit=200,
    )
    if not source:
        # The assistant's own agenda (source=hestia) is not part of the user's calendar.
        items = [i for i in items if i.get("source") != assistant_agenda.SOURCE]
    return {
        "from": now.isoformat(),
        "to": to_time.isoformat(),
        "days": days,
        "count": len(items),
        "items": items,
        "display": agenda_display(items, days, now),
    }


@app.get("/api/calendar/agenda/today")
def get_agenda_today() -> dict:
    """Today's items only (MCP ``agenda_today``)."""
    return get_agenda(days=1, source=None, kind=None)




def agenda_display(items: list[dict], days: int, start: datetime) -> dict:
    """Telegram card of the agenda (hestia_common.display): one line per item, grouped by day when days > 1."""
    tz = start.tzinfo
    rows, last_day = [], None
    for it in items[:30]:
        try:
            at = datetime.fromisoformat(str(it.get("start_at")).replace("Z", "+00:00")).astimezone(tz)
        except (TypeError, ValueError):
            continue
        day = at.date()
        when = tr("all day") if it.get("all_day") else at.strftime("%H:%M")
        if days > 1 and day != last_day:
            rows.append(item(f"{weekday_name(day.weekday())[:3]} {day.day} {month_name(day.month)[:3]}".capitalize(), [when, it.get("title")]))
            last_day = day
        else:
            rows.append(item(it.get("title") or tr("Event"), [when, it.get("location")]))
    title = tr("Today's agenda") if days == 1 else tr("Agenda · next {0} days", days)
    return display(title, items=rows, lines=[] if rows else [tr("Nothing in the agenda.")],
                   footer=tr("and {0} more", len(items) - 30) if len(items) > 30 else "",
                   actions=[action(tr("New event"), "create_event", style="primary"),
                            action(tr("Next days") if days == 1 else tr("Today only"), "agenda" if days == 1 else "agenda_today")])


# ─────────────────────────────────────────────────────────────────────
#  Assistant agenda (Hestia's own calendar, source=hestia)
# ─────────────────────────────────────────────────────────────────────


class CalendarSyncRequest(BaseModel):
    trigger: str = "api"


@app.post("/api/calendar/sync")
def calendar_sync(req: CalendarSyncRequest | None = None) -> dict:
    """Run a calendar sync now in background (agenda job ``chronos.calendar_sync``)."""
    trigger = (req or CalendarSyncRequest()).trigger
    threading.Thread(target=sync_worker.run_sync, args=(trigger,), daemon=True,
                     name="chronos-sync-run").start()
    return {"status": "started", "trigger": trigger, "agenda_job": sync_worker.AGENDA_JOB_KEY}


class AgendaAction(BaseModel):
    service: str
    path: str
    method: str = "POST"
    body: dict | None = None
    query: dict | None = None
    timeout_seconds: float = 30


class AgendaItemCreate(BaseModel):
    title: str
    type: str = Field("event", description="event | task | job | window")
    owner: str = "user"
    start_at: str
    end_at: str | None = None
    recurrence: str | None = Field(None, description="RRULE, e.g. FREQ=DAILY;BYHOUR=3")
    description: str | None = None
    action: AgendaAction | None = None
    key: str | None = None
    params: dict = Field(default_factory=dict)
    tz: str | None = None
    created_by: str = "user"
    parent: str | None = Field(None, description="key of the linked parent item (cascade cancel / error)")


class AgendaItemChange(BaseModel):
    title: str | None = None
    description: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    recurrence: str | None = None
    status: str | None = Field(None, description="confirmed | paused | cancelled")
    action: AgendaAction | None = None
    params: dict | None = None
    by: str = "user"


class AgendaRegister(BaseModel):
    owner: str
    rules: list[dict]


class AgendaSkip(BaseModel):
    occurrence: str | None = None
    by: str = "user"


def _agenda_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except assistant_agenda.AgendaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/agenda")
def agenda_view(days: int = Query(7, ge=1, le=400), owner: str | None = None, type: str | None = None,
                past_hours: int = Query(0, ge=0, le=24 * 400),
                start: str | None = Query(None, description="ISO start (overrides days/past_hours)"),
                end: str | None = Query(None, description="ISO end (with start)"),
                include_done: bool = Query(False, description="also completed/cancelled items")) -> dict:
    """Assistant agenda occurrences (windows, jobs, tasks, events).

    Range: ``start``/``end`` (ISO, used by the WebUI calendar) or now-``past_hours`` → now+``days``.
    """
    now = datetime.now(timezone.utc)
    if start:
        try:
            lo = datetime.fromisoformat(start.replace("Z", "+00:00"))
            hi = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else lo + timedelta(days=days)
        except ValueError:
            raise HTTPException(status_code=400, detail="start/end must be ISO datetimes")
        if lo.tzinfo is None:
            lo = lo.replace(tzinfo=timezone.utc)
        if hi.tzinfo is None:
            hi = hi.replace(tzinfo=timezone.utc)
        if hi <= lo or (hi - lo).days > 400:
            raise HTTPException(status_code=400, detail="end must be after start, range <= 400 days")
    else:
        lo, hi = now - timedelta(hours=past_hours), now + timedelta(days=days)
    rows = assistant_agenda.agenda(lo, hi, owner=owner, type_=type, include_done=include_done)
    return {"from": lo.isoformat(), "to": hi.isoformat(), "days": days,
            "count": len(rows), "occurrences": rows}


@app.get("/api/agenda/occurrences")
def agenda_occurrences(days: int = Query(7, ge=1, le=400), owner: str | None = None, type: str | None = None,
                       past_hours: int = Query(0, ge=0, le=24 * 400),
                       start: str | None = Query(None, description="ISO start (overrides days/past_hours)"),
                       end: str | None = Query(None, description="ISO end (with start)"),
                       include_done: bool = Query(False, description="also completed/cancelled items")) -> dict:
    """Same as ``GET /api/agenda`` under the plugin's ``api_prefix`` (``/api/agenda/``): the calendar page
    (WebUI plugin «Agenda di Hestia») reads its occurrences here."""
    return agenda_view(days=days, owner=owner, type=type, past_hours=past_hours, start=start, end=end,
                       include_done=include_done)


@app.post("/api/agenda/weather")
def agenda_weather_view(body: dict) -> dict:
    """Weather for the calendar page: Home per day, located occurrences (``located: [{key, place, at}]``) and
    Marko's own located calendar events, next 14 days only (``services/agenda_weather.py``)."""
    b = body or {}
    located = b.get("located") if isinstance(b.get("located"), list) else []
    return agenda_weather.build(_route_hecate, str(b.get("start") or ""), str(b.get("end") or ""), located)


@app.get("/api/agenda/items")
def agenda_items(owner: str | None = None, type: str | None = None, include_cancelled: bool = False) -> dict:
    items = assistant_agenda.list_items(owner=owner, type_=type, include_cancelled=include_cancelled)
    return {"count": len(items), "items": items}


@app.post("/api/agenda/items")
def agenda_create(req: AgendaItemCreate) -> dict:
    data = req.model_dump()
    item = _agenda_guard(
        assistant_agenda.create, title=data["title"], type_=data["type"], owner=data["owner"],
        start_at=data["start_at"], end_at=data["end_at"], recurrence=data["recurrence"],
        description=data["description"], action=data["action"], key=data["key"],
        params=data["params"], tz=data["tz"], created_by=data["created_by"], parent=data["parent"])
    return {"status": "ok", "item": item}


@app.post("/api/agenda/register")
def agenda_register(req: AgendaRegister) -> dict:
    """Modules declare their default rules (idempotent; user edits are preserved)."""
    items = _agenda_guard(assistant_agenda.register_rules, req.owner, req.rules)
    return {"status": "ok", "count": len(items), "items": items}


class AgendaRetire(BaseModel):
    owner: str
    keys: list[str]


@app.post("/api/agenda/retire")
def agenda_retire(req: AgendaRetire) -> dict:
    """A module cancels default rules it no longer declares (only rules it created; user items stay)."""
    keys = _agenda_guard(assistant_agenda.retire_rules, req.owner, req.keys)
    return {"status": "ok", "retired": keys}


@app.get("/api/agenda/standard")
def agenda_standard(owner: str | None = None) -> dict:
    """Standard activities of every module (deleted, paused, changed or active) + templates (recap dossier §3.9)."""
    return _agenda_guard(assistant_agenda.standard, owner)


@app.post("/api/agenda/standard/{key}/restore")
def agenda_standard_restore(key: str, by: str = "user") -> dict:
    """Bring a standard activity back exactly as its module declares it."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.restore, key, by)}


@app.patch("/api/agenda/items/{ref}")
def agenda_update(ref: str, req: AgendaItemChange) -> dict:
    changes = req.model_dump(exclude={"by"}, exclude_none=True)
    if changes.get("status") == "cancelled":
        changes.pop("status")
        if changes:
            _agenda_guard(assistant_agenda.update, ref, changes, req.by)
        return {"status": "ok", "item": _agenda_guard(assistant_agenda.cancel, ref, req.by)}  # cascade
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.update, ref, changes, req.by)}


@app.delete("/api/agenda/items/{ref}")
def agenda_cancel(ref: str, by: str = "user") -> dict:
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.cancel, ref, by)}


@app.post("/api/agenda/items/{ref}/skip")
def agenda_skip(ref: str, req: AgendaSkip | None = None) -> dict:
    r = req or AgendaSkip()
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.skip, ref, r.occurrence, r.by)}


@app.post("/api/agenda/items/{ref}/unskip")
def agenda_unskip(ref: str, req: AgendaSkip) -> dict:
    if not req.occurrence:
        raise HTTPException(status_code=400, detail="occurrence required")
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.unskip, ref, req.occurrence, req.by)}


class AgendaMove(BaseModel):
    occurrence: str
    start_at: str | None = None
    end_at: str | None = None
    reset: bool = False
    by: str = "user"


@app.post("/api/agenda/items/{ref}/move")
def agenda_move(ref: str, req: AgendaMove) -> dict:
    """Move one occurrence only (exception); ``reset`` restores it. One-off items move entirely."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.move_occurrence, ref, req.occurrence,
                                                  req.start_at, req.end_at, req.reset, req.by)}


class AgendaLink(BaseModel):
    parent: str | None = Field(None, description="parent key; empty clears the link")
    by: str = "user"


class AgendaFail(BaseModel):
    detail: str = ""
    by: str = "module"


@app.get("/api/agenda/items/{ref}/links")
def agenda_links(ref: str) -> dict:
    item = _agenda_guard(assistant_agenda.get, ref)
    parent = None
    if item.get("parent"):
        try:
            parent = assistant_agenda.get(item["parent"])
        except assistant_agenda.AgendaError:
            parent = None
    return {"status": "ok", "key": item["key"], "parent": parent,
            "children": assistant_agenda.children(item["key"])}


@app.post("/api/agenda/items/{ref}/link")
def agenda_link(ref: str, req: AgendaLink) -> dict:
    """Link an item to a parent: cancelling the parent cancels it; its failure marks the parent."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.link, ref, req.parent, req.by)}


@app.post("/api/agenda/items/{ref}/fail")
def agenda_fail(ref: str, req: AgendaFail) -> dict:
    """A module reports that the work behind the item failed (propagates to the parent)."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.fail, ref, req.detail, req.by)}


@app.post("/api/agenda/items/{ref}/run")
def agenda_run(ref: str) -> dict:
    return {"status": "ok", **_agenda_guard(assistant_agenda.run_now, ref)}


def _since(value: str | None, hours: float | None) -> datetime | None:
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="since must be an ISO datetime")
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None


@app.get("/api/agenda/runs")
def agenda_runs(owner: str | None = None, status: str | None = Query(None, description="ok | failed | skipped"),
                since: str | None = Query(None, description="ISO; or use hours"),
                hours: float | None = Query(None, ge=0, le=24 * 400), limit: int = Query(100, ge=1, le=500)) -> dict:
    """Job/task runs of the assistant agenda (newest first) + summary + rules registered per owner
    (WebUI plugin page «Runs»)."""
    return _agenda_guard(assistant_agenda.runs, owner=owner, status=status, since=_since(since, hours), limit=limit)


@app.get("/api/agenda/runs/failed")
def agenda_runs_failed(hours: float = Query(24, ge=1, le=24 * 30)) -> list[dict]:
    """Chips of the quick action «Retry job»: jobs whose last run failed (id = item key)."""
    return assistant_agenda.failed_jobs(since=_since(None, hours))


_LOG_SERVICE_RE = __import__("re").compile(r"^[a-z0-9_-]{2,40}$")


@app.get("/api/agenda/logs")
def agenda_logs(service: str, at: str, minutes: int = Query(5, ge=1, le=120), level: str | None = None,
                contains: str | None = None) -> dict:
    """«Module log» of the calendar page: the service's own ``/api/logs`` (in-memory buffer, recent hours) read
    through Hub and cut to ``at ± minutes``. Under the plugin's api_prefix so the page needs nothing else."""
    import requests

    if not _LOG_SERVICE_RE.match(service or ""):
        raise HTTPException(status_code=400, detail="invalid service")
    try:
        center = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="at must be an ISO datetime")
    if center.tzinfo is None:
        center = center.replace(tzinfo=timezone.utc)
    lo, hi = center - timedelta(minutes=minutes), center + timedelta(minutes=minutes)
    query = {"limit": "2000", **({"level": level} if level else {}), **({"contains": contains} if contains else {})}
    hub_api_url = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    try:
        resp = requests.post(f"{hub_api_url}/route/{service}/api/logs",
                             json={"method": "GET", "headers": {}, "query": query, "body": None, "timeout_seconds": 15},
                             timeout=20)
        routed = resp.json() if resp.content else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=agenda_logs_failed service=%s error=%s", service, exc)
        raise HTTPException(status_code=502, detail=tr("{0} not reachable", service))
    status = int((routed or {}).get("status_code", 502))
    if status >= 400:
        raise HTTPException(status_code=502 if status >= 500 else status, detail=tr("{0}: logs not available", service))
    rows, oldest = [], None
    for row in ((routed.get("payload") or {}).get("logs") or []):
        try:
            ts = datetime.fromisoformat(str(row.get("ts")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        oldest = oldest or row.get("ts")
        if lo <= ts <= hi:
            rows.append(row)
    return {"service": service, "from": lo.isoformat(), "to": hi.isoformat(), "count": len(rows), "oldest": oldest,
            "logs": rows}


class AgendaTemplates(BaseModel):
    owner: str
    templates: list[dict] = []


class AgendaFromTemplate(BaseModel):
    values: dict = {}
    start_at: str
    end_at: str | None = None
    recurrence: str | None = None
    type: str | None = None
    description: str | None = None


@app.post("/api/agenda/templates")
def agenda_templates_register(req: AgendaTemplates) -> dict:
    """Modules declare what the user can create for them (calendar wizard). Replaces the owner's set."""
    return {"status": "ok", "count": assistant_agenda.register_templates(req.owner, req.templates)}


@app.get("/api/agenda/templates")
def agenda_templates() -> dict:
    rows = assistant_agenda.list_templates()
    return {"count": len(rows), "templates": rows}


@app.post("/api/agenda/templates/{owner}/{template_id}/create")
def agenda_from_template(owner: str, template_id: str, req: AgendaFromTemplate) -> dict:
    item = _agenda_guard(assistant_agenda.create_from_template, owner, template_id, values=req.values,
                         start_at=req.start_at, end_at=req.end_at, recurrence=req.recurrence,
                         type_=req.type, description=req.description)
    return {"status": "ok", "item": item}


class AgendaParse(BaseModel):
    text: str
    tz: str | None = None


@app.post("/api/agenda/parse")
def agenda_parse_text(req: AgendaParse) -> dict:
    """Natural-language quick add: draft fields for the editor (nothing is created)."""
    try:
        return {"status": "ok", "draft": agenda_parse.parse(req.text, tz_name=req.tz)}
    except agenda_parse.ParseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/agenda/ics")
def agenda_ics(days: int = Query(60, ge=1, le=400), past_days: int = Query(7, ge=0, le=90),
               owner: str | None = None,
               types: str = Query("event,task,window", description="comma list; add job for periodic jobs")) -> Response:
    """Read-only iCalendar feed of the assistant agenda (expanded occurrences, skips/moves applied)."""
    now = datetime.now(timezone.utc)
    wanted = {t.strip() for t in types.split(",") if t.strip()}
    rows = [o for o in assistant_agenda.agenda(now - timedelta(days=past_days), now + timedelta(days=days), owner=owner)
            if o.get("type") in wanted][:3000]
    return Response(agenda_parse.to_ics(rows), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="hestia-agenda.ics"'})


@app.get("/api/agenda/windows/{key}")
def agenda_window(key: str) -> dict:
    """Modules ask: is my window open now? (closed if missing/cancelled/skipped)."""
    return {"status": "ok", **assistant_agenda.window_status(key)}


# ─────────────────────────────────────────────────────────────────────
#  Weekly coach plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo)
#  Under the plugin's api_prefix (/api/agenda/) so the «Your week» page needs nothing else.
# ─────────────────────────────────────────────────────────────────────


class CoachReport(BaseModel):
    module: str
    event: str = Field(..., description="done | skipped | changed")
    need_id: str = ""
    at: str | None = None
    reason: str = ""


class CoachReplan(BaseModel):
    date: str | None = Field(None, description="first day to plan (default today)")
    busy: list[dict] = Field(default_factory=list, description="[{start_at, end_at, title}] to leave free first")


class CoachMove(BaseModel):
    ref: str | None = None
    start_at: str
    end_at: str | None = None


class CoachSkip(BaseModel):
    ref: str | None = None
    reason: str = ""


class CoachBusy(BaseModel):
    start_at: str
    end_at: str
    title: str = ""


def _coach_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except weekly_coach.CoachError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except assistant_agenda.AgendaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _coach_day(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be ISO (YYYY-MM-DD)")


@app.get("/api/agenda/coach/week")
def coach_week(date: str | None = None) -> dict:
    """The week's plan (the week containing ``date``, default today)."""
    return _coach_guard(weekly_coach.view, _coach_day(date))


@app.get("/api/agenda/coach/today")
def coach_today(date: str | None = None) -> dict:
    """Today's plan items (widget «Today in the plan», daily recap)."""
    day = _coach_day(date)
    return {"date": (day or weekly_coach.now().date()).isoformat(),
            "items": _coach_guard(weekly_coach.today_items, day)}


@app.post("/api/agenda/coach/replan")
def coach_replan(req: CoachReplan | None = None) -> dict:
    """Re-plan from ``date`` to the end of its week (chat «redo the plan», page button)."""
    req = req or CoachReplan()
    for b in req.busy:
        _coach_guard(weekly_coach.add_busy, b.get("start_at"), b.get("end_at"), b.get("title") or "")
    return _coach_guard(weekly_coach.replan, _coach_day(req.date), reason="chat")


@app.post("/api/agenda/coach/week/run")
def coach_week_run() -> dict:
    """Agenda job ``chronos.coach_week``: plan the coming week and deliver the message."""
    return _coach_guard(weekly_coach.run_week)


@app.post("/api/agenda/coach/report")
def coach_report(req: CoachReport) -> dict:
    """A coach module reports done / skipped / changed (``hestia_common.coach.CoachClient``)."""
    return _coach_guard(weekly_coach.report, req.module, req.event, req.need_id, req.at, req.reason)


@app.post("/api/agenda/coach/items/{ref}/move")
def coach_move(ref: str, req: CoachMove) -> dict:
    """Move a plan item (drag on the page, chat): it becomes the user's and stays there."""
    return _coach_guard(weekly_coach.move, ref, req.start_at, req.end_at)


@app.post("/api/agenda/coach/items/{ref}/skip")
def coach_skip(ref: str, req: CoachSkip | None = None) -> dict:
    return _coach_guard(weekly_coach.skip, ref, (req or CoachSkip()).reason)


@app.post("/api/agenda/coach/busy")
def coach_busy_add(req: CoachBusy) -> dict:
    """A period the plan leaves free («I'm away on Wednesday»)."""
    return _coach_guard(weekly_coach.add_busy, req.start_at, req.end_at, req.title)


@app.delete("/api/agenda/coach/busy/{ref}")
def coach_busy_remove(ref: str) -> dict:
    return _coach_guard(weekly_coach.remove_busy, ref)


@app.get("/api/agenda/coach/review")
def coach_review(date: str | None = None) -> dict:
    """How the week before ``date``'s week went, from every coach (their own data)."""
    start, _end = weekly_coach.week_of(_coach_day(date) or weekly_coach.now().date())
    from datetime import timedelta as _td
    return {"start": (start - _td(days=7)).isoformat(), "end": start.isoformat(),
            "modules": weekly_coach.reviews(start - _td(days=7), start)}


# ─────────────────────────────────────────────────────────────────────
#  Assistant presence (SPEC docs/work/2026-10-10-assistant-presence)
# ─────────────────────────────────────────────────────────────────────


class PresencePing(BaseModel):
    client: str = "unknown"
    kind: str = "chat"          # chat | command | ui


class PresenceActivity(BaseModel):
    key: str
    label: str = ""
    load: str = "light"         # light | heavy
    resource: str = ""          # gpu | claude_quota | cpu …
    kind: str = "work"          # work | maintenance
    module: str = ""
    ttl_seconds: float = 3600


class PresenceSignalIn(BaseModel):
    value: Any = True
    meta: dict | None = None
    ttl_seconds: float | None = None


class PresenceDnd(BaseModel):
    minutes: float | None = None
    until: str | None = None


class PresenceStates(BaseModel):
    owner: str
    states: dict[str, dict] = Field(default_factory=dict)


def _presence_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/presence")
def presence_view() -> dict:
    """Current state: base + overlays, label, effects, last interaction, activities."""
    return assistant_presence.get_engine().view()


@app.post("/api/presence/ping")
def presence_ping(req: PresencePing | None = None) -> dict:
    req = req or PresencePing()
    return assistant_presence.get_engine().ping(req.client, req.kind)


@app.post("/api/presence/activity")
def presence_activity_start(req: PresenceActivity) -> dict:
    return _presence_guard(assistant_presence.get_engine().activity_start, req.key, label=req.label,
                           load=req.load, resource=req.resource, kind=req.kind, module=req.module,
                           ttl=req.ttl_seconds)


@app.delete("/api/presence/activity/{key}")
def presence_activity_stop(key: str) -> dict:
    return assistant_presence.get_engine().activity_stop(key)


@app.put("/api/presence/signals/{key}")
def presence_signal_set(key: str, req: PresenceSignalIn) -> dict:
    """Generic fact (e.g. ``resource.claude_quota_left``, ``health.degraded_services``)."""
    return _presence_guard(assistant_presence.get_engine().set_signal, key, req.value, meta=req.meta,
                           ttl=req.ttl_seconds)


@app.delete("/api/presence/signals/{key}")
def presence_signal_clear(key: str) -> dict:
    return assistant_presence.get_engine().clear_signal(key)


@app.post("/api/presence/dnd")
def presence_dnd_on(req: PresenceDnd | None = None) -> dict:
    req = req or PresenceDnd()
    return assistant_presence.get_engine().set_dnd(minutes=req.minutes, until=req.until)


@app.delete("/api/presence/dnd")
def presence_dnd_off() -> dict:
    return assistant_presence.get_engine().clear_dnd()


@app.get("/api/presence/states")
def presence_states() -> dict:
    """Effective definitions (built-in + modules + the user's setting); edits go through Themis."""
    return {"setting": presence_settings.STATES, "core": list(presence_settings.CORE_STATES),
            "effects": presence_settings.EFFECT_ORDER, "states": assistant_presence.get_engine().states()}


@app.post("/api/presence/states/register")
def presence_states_register(req: PresenceStates) -> dict:
    """A module declares its own states (in memory, re-asserted by the module)."""
    count = assistant_presence.get_engine().declare_states(req.owner, req.states)
    return {"status": "ok", "owner": req.owner, "count": count}


@app.get("/api/presence/history")
def presence_history(limit: int = Query(50, ge=1, le=500)) -> dict:
    rows = assistant_presence.get_engine().history(limit)
    return {"count": len(rows), "items": rows}


@app.post("/api/module/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def module_maintenance_reconcile(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    task_id = str(req.task_id or uuid4())
    action = str(req.requested_action or "reconcile_calendar").strip().lower()

    if req.dry_run:
        return ModuleMaintenanceResponse(
            status="ok",
            service="chronos",
            dry_run=True,
            task_id=task_id,
            executed_at=datetime.now(timezone.utc),
            retriable=True,
            summary="Chronos maintenance dry-run accepted: no worker ticks executed.",
            mutation_count=0,
            details={
                "requested_action": action,
                "note": "Set dry_run=false to execute maintenance tick(s).",
            },
        )

    tick_results: dict[str, str] = {}
    mutation_count = 0

    if action in {"reconcile_calendar", "sync", "sync_tick", "full"}:
        try:
            result = sync_worker.run_sync("maintenance")
            tick_results["sync"] = result["status"] if result["status"] != "error" else f"error:{result.get('error')}"
            mutation_count += 1
        except Exception as error:
            tick_results["sync"] = f"error:{error}"

    if action in {"reconcile_calendar", "notify", "notify_tick", "full"}:
        try:
            notification_worker._tick()  # pylint: disable=protected-access
            tick_results["notify"] = "ok"
            mutation_count += 1
        except Exception as error:
            tick_results["notify"] = f"error:{error}"

    if not tick_results:
        tick_results["noop"] = "unsupported_requested_action"

    return ModuleMaintenanceResponse(
        status="ok",
        service="chronos",
        dry_run=False,
        task_id=task_id,
        executed_at=datetime.now(timezone.utc),
        retriable=True,
        summary="Chronos maintenance reconcile executed.",
        mutation_count=mutation_count,
        details={
            "requested_action": action,
            "ticks": tick_results,
        },
    )


@app.post("/api/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def maintenance_reconcile_alias(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    return module_maintenance_reconcile(req)


# ─────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("CALENDAR_PORT", "19007"))
    uvicorn.run("main:app", host="0.0.0.0", port=port,
                # WORKDIR=/code, flat imports
                reload=False, log_level=os.getenv("LOG_LEVEL", "INFO").lower())
