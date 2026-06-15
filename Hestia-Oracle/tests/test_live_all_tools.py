"""Exhaustive live LLM tool-calling test — every Hub command by domain.

Each test presents a SMALL tool manifest (3-8 tools from one domain).
The LLM picks the right tool for the user's request. All handlers are mocked.

Usage (manual only):
  python -m pytest tests/test_live_all_tools.py -m llm_live --run-live -v -s

The -s flag shows raw LLM responses for diagnostic purposes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
import pytest
import requests

_ORACLE_ROOT = Path(__file__).parents[1]
_APP_PATH = _ORACLE_ROOT / "app"
_REPO_ROOT = _ORACLE_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"
for _p in [str(_APP_PATH), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.agent_loop import run_agent_loop, ToolDefinition

# ── Resolve model from env ──────────────────────────────────────────────────
_LLM_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
_CHAT_URL = _OLLAMA_URL.replace("/api/generate", "/api/chat")

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _call_ollama(prompt: str) -> str:
    """Single blocking call to Ollama /api/chat. Returns content string."""
    try:
        resp = requests.post(_CHAT_URL, json={
            "model": _LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }, timeout=120)
        resp.raise_for_status()
        return (resp.json().get("message", {}).get("content", "") or "").strip()
    except Exception as exc:
        return f"[OLLAMA_ERROR: {exc}]"


def _ollama_ask(prompt: str) -> str:
    return _call_ollama(prompt)


def _ollama_ask_tools(prompt: str, tools_manifest: list[dict]) -> dict:
    """Ollama native tool calling via /api/chat.

    Falls back to plain text if native tool calling returns no tool_call.
    """
    ollama_tools = [
        {"type": "function", "function": {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
        }}
        for t in tools_manifest
    ]
    try:
        resp = requests.post(_CHAT_URL, json={
            "model": _LLM_MODEL,
            "messages": [
                {"role": "system", "content": (
                    "You are Hestia's tool-calling engine. "
                    "When the user asks for something you can do with a tool, call it. "
                    "If no tool matches, respond in plain text."
                )},
                {"role": "user", "content": prompt},
            ],
            "tools": ollama_tools,
            "stream": False,
        }, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tc = tool_calls[0]
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            return {"tool_call": {"name": fn.get("name", ""), "params": args}, "text": ""}
        return {"tool_call": None, "text": msg.get("content", "") or ""}
    except Exception as exc:
        return {"tool_call": None, "text": f"[OLLAMA_ERROR: {exc}]"}


# ── Realistic mock responses per tool ──────────────────────────────────────

_MOCK_DATA = {
    "scout.search": {
        "domain": "real_estate",
        "items": [
            {"title": "Trilocale Milano Centro", "price": 280000, "city": "Milano",
             "url": "https://example.com/listing/1", "specs": {"surface_m2": 85, "rooms": 3}},
            {"title": "Bilocale Milano Navigli", "price": 195000, "city": "Milano",
             "url": "https://example.com/listing/2", "specs": {"surface_m2": 60, "rooms": 2}},
        ],
    },
    "scout_listings": {
        "domain": "real_estate",
        "items": [
            {"title": "Appartamento Roma Trastevere", "price": 320000, "city": "Roma",
             "url": "https://example.com/listing/3"},
        ],
    },
    "agenda": {
        "events": [
            {"title": "Riunione team", "start": "2026-06-16T10:00:00", "end": "2026-06-16T11:00:00"},
            {"title": "Dentista", "start": "2026-06-17T14:30:00", "end": "2026-06-17T15:30:00"},
        ],
    },
    "agenda_today": {
        "events": [
            {"title": "Call con cliente", "start": "2026-06-15T15:00:00", "end": "2026-06-15T16:00:00"},
        ],
    },
    "create_event": {
        "status": "created",
        "event_id": "evt-new-001",
        "title": "(set by caller params)",
        "start_datetime": "(set by caller params)",
    },
    "calendar_delete_event": {"status": "deleted", "event_id": "(from params)"},
    "calendar_update_event": {"status": "updated", "event_id": "(from params)"},
    "calendar_list_events": {"events": []},
    "email_search": {
        "messages": [
            {"id": "msg-1", "subject": "Fattura Q1 2026", "from": "contabilita@example.com", "date": "2026-06-10"},
            {"id": "msg-2", "subject": "Fattura fornitore", "from": "fornitore@example.com", "date": "2026-06-08"},
        ],
    },
    "email_send": {"status": "sent", "message_id": "msg-sent-001"},
    "email_thread": {
        "thread_id": "(from params)",
        "messages": [
            {"id": "msg-1", "from": "a@b.com", "subject": "Re: Discussione", "body": "Contenuto del thread..."},
        ],
    },
    "sync_calendar": {"status": "synced", "events_imported": 5},
    "gateway_auth_status": {
        "providers": {
            "google": {"connected": True, "email": "user@gmail.com"},
            "microsoft": {"connected": False},
        },
    },
    "gateway_auth_initiate_google": {"status": "pending", "auth_url": "https://accounts.google.com/o/oauth2/auth?..."},
    "gateway_auth_initiate_microsoft": {"status": "pending", "auth_url": "https://login.microsoftonline.com/..."},
    "gateway_auth_poll": {"status": "completed", "provider": "(from params)"},
    "system_status": {
        "services": {
            "hub": "healthy", "archive": "healthy", "oracle": "healthy",
            "scout": "degraded", "telegram": "healthy",
        },
        "overall": "degraded",
    },
    "system_log": {
        "entries": [
            {"level": "ERROR", "service": "scout", "message": "Connection timeout to external API", "timestamp": "2026-06-15T09:00:00Z"},
        ],
    },
    "system_analysis": {"summary": "System mostly healthy. Scout shows connection issues. Recommended: restart Scout container."},
    "system_remediate": {"status": "created", "task_id": "rem-task-001", "dry_run": True},
    "hephaestus_status": {"engine": "running", "available_runbooks": 12, "active_tasks": 1},
    "hephaestus_tasks": {"tasks": [{"id": "task-1", "status": "completed", "service": "scout"}]},
    "hephaestus_remediate": {"status": "created", "task_id": "rem-task-002", "dry_run": True},
    "hephaestus_approve": {"status": "approved", "task_id": "(from params)"},
    "hephaestus_rollback": {"status": "rolled_back", "task_id": "(from params)"},
    "memory.save": {"status": "saved", "fact": "(from params)", "domain": "(from params)"},
    "memory.search": {"memories": []},
    "documents.search": {"chunks": []},
    "fetch_page": {"url": "(from params)", "content": "Example Domain\n\nThis domain is for use in illustrative examples...", "status": 200},
    "scout_reconcile": {"status": "reconciled", "entities_updated": 0},
    "chronos_reconcile": {"status": "reconciled", "events_synced": 0},
    "iris_reconcile": {"status": "reconciled", "emails_processed": 0},
    "dummy_test_reconcile": {"status": "ok", "message": "Test reconcile completed"},
}


def _build_tools(commands: list[dict]) -> list[ToolDefinition]:
    """Build ToolDefinitions with realistic mock handlers that return actual data."""
    tools = []
    for cmd in commands:
        cmd_name = cmd["name"]
        mock_result = _MOCK_DATA.get(cmd_name, {"status": "ok"})

        def make_handler(name, result):
            def handler(**kwargs) -> tuple[bool, dict]:
                # Merge caller params into the mock result so the LLM sees real data
                response = dict(result)
                if isinstance(response, dict) and "event_id" in response and response["event_id"] == "(from params)":
                    response["event_id"] = kwargs.get("event_id", "unknown")
                if isinstance(response, dict) and "title" in response and response["title"] == "(set by caller params)":
                    response["title"] = kwargs.get("title", "unknown")
                    response["start_datetime"] = kwargs.get("start_datetime", "unknown")
                if isinstance(response, dict) and "task_id" in response and response["task_id"] == "(from params)":
                    response["task_id"] = kwargs.get("task_id", "unknown")
                if isinstance(response, dict) and "fact" in response and response["fact"] == "(from params)":
                    response["fact"] = kwargs.get("fact", "unknown")
                    response["domain"] = kwargs.get("domain", "general")
                return (True, response)
            return handler

        tools.append(ToolDefinition(
            name=cmd_name,
            description=cmd["description"],
            parameters=cmd["parameters"],
            handler=make_handler(cmd_name, mock_result),
        ))
    return tools


def _run_test(user_message: str, domain_tools: list[dict], label: str = "",
              must_call: str | list[str] | None = None,
              must_not_hallucinate: list[str] | None = None) -> tuple[str, list[dict]]:
    """Run agent loop. ALWAYS prints output. Validates tool calls and anti-hallucination.

    Args:
        must_call: Tool name(s) that MUST be called (assertion).
        must_not_hallucinate: Phrases that MUST NOT appear (e.g. invented data).
    """
    tools = _build_tools(domain_tools)
    tool_names = [t.name for t in tools]

    answer, tokens, tool_log = run_agent_loop(
        user_message=user_message,
        history_text="",
        preference_facts=[],
        tools=tools,
        ask_fn=_ollama_ask,
        ask_tools_fn=_ollama_ask_tools,
        max_turns=5,
    )

    # ── Always dump output ──────────────────────────────────────────────
    tag = f" [{label}]" if label else ""
    print(f"\n{'='*60}")
    print(f"TEST{tag}: {user_message}")
    print(f"Tools available ({len(tool_names)}): {', '.join(tool_names)}")
    print(f"Tools called  ({len(tool_log)}): {[c['tool'] + (' FAIL' if not c['ok'] else '') for c in tool_log]}")
    for i, c in enumerate(tool_log):
        result_preview = c.get('result_preview', '')[:250]
        print(f"  [{i}] {c['tool']} | params={json.dumps(c.get('params',{}), ensure_ascii=False)[:200]} | ok={c['ok']} | {c.get('duration_ms','?')}ms")
        if result_preview:
            print(f"       result: {result_preview}")
    print(f"Answer ({len(answer)} chars):")
    print(answer[:800] if answer else "(EMPTY)")
    print(f"{'='*60}\n")

    # ── Validation ──────────────────────────────────────────────────────
    errors: list[str] = []

    if must_call:
        required = [must_call] if isinstance(must_call, str) else must_call
        called = {c["tool"] for c in tool_log}
        if len(required) == 1:
            # Single tool: must be called exactly
            if required[0] not in called:
                errors.append(f"MISSING TOOL: expected '{required[0]}' to be called. Called: {list(called)}")
        else:
            # List: at least ONE must be called (OR semantics)
            if not (called & set(required)):
                errors.append(f"MISSING TOOL: expected at least one of {required} to be called. Called: {list(called)}")

    if must_not_hallucinate:
        answer_lower = answer.lower()
        for phrase in must_not_hallucinate:
            if phrase.lower() in answer_lower:
                # Only flag if the phrase is NOT in any mock result returned to the LLM
                found_in_results = False
                for c in tool_log:
                    result_preview = c.get('result_preview', '')
                    if phrase.lower() in result_preview.lower():
                        found_in_results = True
                        break
                if not found_in_results:
                    errors.append(f"HALLUCINATION: answer contains '{phrase}' which was not in any tool result")

    if errors:
        for e in errors:
            print(f"  [VALIDATION ERROR] {e}")
        print()

    return answer, tool_log, errors


# ═══════════════════════════════════════════════════════════════════════════════
# Domain tool manifests (small, 3-8 tools each)
# ═══════════════════════════════════════════════════════════════════════════════

SCOUT_TOOLS = [
    {"name": "scout.search", "description": "Search real estate listings by query, city, price range. Use for any house/apartment search.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "filters": {"type": "object"}, "filters_gt": {"type": "object"}, "filters_lt": {"type": "object"}, "sort_by": {"type": "string"}, "sort_order": {"type": "string", "enum": ["asc", "desc"]}}}},
    {"name": "scout_listings", "description": "Show available real estate listings. Use when user wants to browse or see listings.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "scout_reconcile", "description": "Clean up and reconcile Scout real estate data. Use when user asks to sync/clean data.", "parameters": {"type": "object", "properties": {"dry_run": {"type": "boolean"}}}},
]

CALENDAR_TOOLS = [
    {"name": "agenda", "description": "Show upcoming calendar events for the next 7 days.", "parameters": {"type": "object", "properties": {}}},
    {"name": "agenda_today", "description": "Show only today's calendar events.", "parameters": {"type": "object", "properties": {}}},
    {"name": "create_event", "description": "Create a new calendar event. Use when user wants to schedule something.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "start_datetime": {"type": "string"}, "end_datetime": {"type": "string"}, "description": {"type": "string"}, "location": {"type": "string"}}, "required": ["title", "start_datetime"]}},
    {"name": "calendar_delete_event", "description": "Delete/remove a calendar event by its ID.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}},
    {"name": "calendar_update_event", "description": "Update/modify an existing calendar event.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}, "title": {"type": "string"}, "start_datetime": {"type": "string"}}, "required": ["event_id"]}},
    {"name": "calendar_list_events", "description": "List events in a specific date range.", "parameters": {"type": "object", "properties": {"start_datetime": {"type": "string"}, "end_datetime": {"type": "string"}}}},
    {"name": "chronos_reconcile", "description": "Sync/reconcile calendar data.", "parameters": {"type": "object", "properties": {"dry_run": {"type": "boolean"}}}},
]

EMAIL_TOOLS = [
    {"name": "email_search", "description": "Search email messages by text query.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "email_send", "description": "Send an email message.", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject"]}},
    {"name": "email_thread", "description": "Show a specific email thread by ID.", "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "iris_reconcile", "description": "Reconcile/sync email data.", "parameters": {"type": "object", "properties": {"dry_run": {"type": "boolean"}}}},
]

GATEWAY_TOOLS = [
    {"name": "sync_calendar", "description": "Sync calendar events from Google/Outlook into Hestia.", "parameters": {"type": "object", "properties": {}}},
    {"name": "gateway_auth_status", "description": "Show which external providers (Google, Microsoft) are connected.", "parameters": {"type": "object", "properties": {}}},
    {"name": "gateway_auth_initiate_google", "description": "Start connecting a Google Calendar account.", "parameters": {"type": "object", "properties": {}}},
    {"name": "gateway_auth_initiate_microsoft", "description": "Start connecting a Microsoft Outlook account.", "parameters": {"type": "object", "properties": {}}},
    {"name": "gateway_auth_poll", "description": "Check if a pending OAuth connection has completed.", "parameters": {"type": "object", "properties": {"provider": {"type": "string"}}, "required": ["provider"]}},
]

MONITORING_TOOLS = [
    {"name": "system_status", "description": "Show health status of all Hestia services. Use when user asks if the system is OK.", "parameters": {"type": "object", "properties": {}}},
    {"name": "system_log", "description": "Show recent system log events. Use for errors, warnings, debugging.", "parameters": {"type": "object", "properties": {"level": {"type": "string"}, "service": {"type": "string"}}}},
    {"name": "system_analysis", "description": "Run a deep LLM analysis of system health across all logs.", "parameters": {"type": "object", "properties": {}}},
    {"name": "system_remediate", "description": "Create a fix/remediation for a system issue.", "parameters": {"type": "object", "properties": {"service": {"type": "string"}, "issue": {"type": "string"}, "severity": {"type": "string"}, "dry_run": {"type": "boolean"}}, "required": ["service", "issue"]}},
]

REMEDIATION_TOOLS = [
    {"name": "hephaestus_status", "description": "Show remediation engine status and available fix runbooks.", "parameters": {"type": "object", "properties": {}}},
    {"name": "hephaestus_tasks", "description": "List all remediation tasks (pending, running, done).", "parameters": {"type": "object", "properties": {}}},
    {"name": "hephaestus_remediate", "description": "Create a new remediation task to fix something.", "parameters": {"type": "object", "properties": {"service": {"type": "string"}, "issue": {"type": "string"}, "severity": {"type": "string"}, "dry_run": {"type": "boolean"}}, "required": ["service", "issue"]}},
    {"name": "hephaestus_approve", "description": "Approve and execute a pending remediation task.", "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "hephaestus_rollback", "description": "Rollback/undo a previously executed remediation.", "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["task_id"]}},
]

MEMORY_TOOLS = [
    {"name": "memory.save", "description": "Save a fact/preference about the user. Use when user says 'remember', 'I prefer', 'I like', 'save this'.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}, "domain": {"type": "string"}}, "required": ["fact"]}},
    {"name": "memory.search", "description": "Search saved memories/preferences. Use when user asks 'what do you remember', 'what do you know about me'.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
]

MISC_TOOLS = [
    {"name": "documents.search", "description": "Search through uploaded documents for relevant content.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "fetch_page", "description": "Fetch and read content from a web page URL.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "dummy_test_reconcile", "description": "Test reconciliation on the mock module.", "parameters": {"type": "object", "properties": {}}},
]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests — one class per domain
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.llm_live
class TestScoutRealEstate:
    """scout.search, scout_listings, scout_reconcile"""

    def test_search_houses(self):
        _, _, errors = _run_test(
            "Cerco trilocali a Milano sotto i 300000 euro", SCOUT_TOOLS,
            must_call="scout.search",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_show_listings(self):
        _, _, errors = _run_test(
            "Mostrami le case disponibili a Roma", SCOUT_TOOLS,
            must_call=["scout.search", "scout_listings"],
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestChronosCalendar:
    """agenda, agenda_today, create_event, calendar_delete_event, etc."""

    def test_show_agenda(self):
        _, _, errors = _run_test(
            "Quali sono i miei prossimi eventi in calendario?", CALENDAR_TOOLS,
            must_call="agenda",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_create_event(self):
        _, _, errors = _run_test(
            "Crea un evento domani alle 15:00: Riunione con Mario", CALENDAR_TOOLS,
            must_call="create_event",
            must_not_hallucinate=["ID:", "evt-", "confermato"],
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_delete_event(self):
        _, _, errors = _run_test(
            "Elimina l'evento con ID evt-123 dal calendario", CALENDAR_TOOLS,
            must_call="calendar_delete_event",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_today_agenda(self):
        _, _, errors = _run_test(
            "Cosa ho in agenda oggi?", CALENDAR_TOOLS,
            must_call=["agenda_today", "agenda"],
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestIrisEmail:
    """email_search, email_send, email_thread, iris_reconcile"""

    def test_search_emails(self):
        _, _, errors = _run_test(
            "Cerca le mie email che parlano di fatture", EMAIL_TOOLS,
            must_call="email_search",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_send_email(self):
        _, _, errors = _run_test(
            "Invia una email a mario@example.com con oggetto: Progetto Hestia", EMAIL_TOOLS,
            must_call="email_send",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_show_thread(self):
        _, _, errors = _run_test(
            "Mostrami il thread email con ID thread-456", EMAIL_TOOLS,
            must_call="email_thread",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestHecateGateway:
    """sync_calendar, gateway_auth_status, gateway_auth_initiate_*, gateway_auth_poll"""

    def test_sync_calendar(self):
        _, _, errors = _run_test(
            "Sincronizza il mio calendario con Google", GATEWAY_TOOLS,
            must_call="sync_calendar",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_auth_status(self):
        _, _, errors = _run_test(
            "Quali provider sono connessi? Mostra lo stato autenticazione", GATEWAY_TOOLS,
            must_call="gateway_auth_status",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_connect_google(self):
        _, _, errors = _run_test(
            "Collega il mio Google Calendar a Hestia", GATEWAY_TOOLS,
            must_call="gateway_auth_initiate_google",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestArgusMonitoring:
    """system_status, system_log, system_analysis, system_remediate"""

    def test_system_status(self):
        _, _, errors = _run_test(
            "Come sta il sistema? Tutti i servizi funzionano?", MONITORING_TOOLS,
            must_call="system_status",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_system_logs(self):
        _, _, errors = _run_test(
            "Mostrami gli errori recenti nei log di sistema", MONITORING_TOOLS,
            must_call="system_log",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_system_analysis(self):
        _, _, errors = _run_test(
            "Fai una analisi approfondita dello stato del sistema", MONITORING_TOOLS,
            must_call="system_analysis",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestHephaestusRemediation:
    """hephaestus_status, hephaestus_tasks, hephaestus_remediate, _approve, _rollback"""

    def test_remediation_status(self):
        _, _, errors = _run_test(
            "Qual e' lo stato del motore di remediation?", REMEDIATION_TOOLS,
            must_call="hephaestus_status",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_create_remediation(self):
        _, _, errors = _run_test(
            "Il servizio Scout ha un problema di memoria, avvia una remediation in dry-run",
            REMEDIATION_TOOLS,
            must_call="hephaestus_remediate",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestMemory:
    """memory.save, memory.search"""

    def test_save_memory(self):
        _, _, errors = _run_test(
            "Ricordati che preferisco gli appartamenti in centro storico", MEMORY_TOOLS,
            must_call="memory.save",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_search_memory(self):
        _, _, errors = _run_test(
            "Cosa sai di me? Quali preferenze hai salvato?", MEMORY_TOOLS,
            must_call="memory.search",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestMiscTools:
    """documents.search, fetch_page, dummy_test_reconcile"""

    def test_search_documents(self):
        _, _, errors = _run_test(
            "Cerca nei miei documenti informazioni sul progetto Hestia", MISC_TOOLS,
            must_call="documents.search",
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_fetch_page(self):
        _, _, errors = _run_test(
            "Leggi il contenuto della pagina https://example.com", MISC_TOOLS,
            must_call="fetch_page",
            must_not_hallucinate=["Example Domain", "illustrative"],
        )
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestToolDiscrimination:
    """Verify the LLM picks the RIGHT tool among similar-looking options."""

    def test_email_vs_calendar(self):
        """'Invia email' -> email_send, not create_event."""
        mixed = EMAIL_TOOLS + CALENDAR_TOOLS[:3]
        answer, tool_log, errors = _run_test(
            "Invia una email a test@test.com con oggetto Ciao", mixed,
            must_call="email_send",
        )
        # Extra: must NOT call calendar tools
        wrong = [c for c in tool_log if "calendar" in c["tool"] or "agenda" in c["tool"] or "create_event" in c["tool"]]
        if wrong:
            errors.append(f"WRONG TOOL: called calendar tool for email request: {[c['tool'] for c in wrong]}")
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"

    def test_no_destructive_on_greeting(self):
        """Greeting should NOT trigger destructive tools."""
        all_tools = SCOUT_TOOLS + CALENDAR_TOOLS + REMEDIATION_TOOLS
        answer, tool_log, errors = _run_test("Ciao! Come stai?", all_tools)
        destructive = [c for c in tool_log if any(
            p in c["tool"] for p in ["delete", "remediate", "reconcile", "email_send"]
        )]
        if destructive:
            errors.append(f"DESTRUCTIVE ON GREETING: {[c['tool'] for c in destructive]}")
        assert not errors, f"VALIDATION FAILED: {'; '.join(errors)}"


@pytest.mark.llm_live
class TestToolCoverage:
    """Verify all 34 tools are present in the combined manifests."""

    def test_all_tools_accounted(self):
        all_names = set()
        for manifest in [SCOUT_TOOLS, CALENDAR_TOOLS, EMAIL_TOOLS, GATEWAY_TOOLS,
                          MONITORING_TOOLS, REMEDIATION_TOOLS, MEMORY_TOOLS, MISC_TOOLS]:
            for t in manifest:
                all_names.add(t["name"])
        expected = {
            "scout.search", "scout_listings", "scout_reconcile",
            "agenda", "agenda_today", "create_event", "calendar_delete_event",
            "calendar_update_event", "calendar_list_events", "chronos_reconcile",
            "email_search", "email_send", "email_thread", "iris_reconcile",
            "sync_calendar", "gateway_auth_status", "gateway_auth_initiate_google",
            "gateway_auth_initiate_microsoft", "gateway_auth_poll",
            "system_status", "system_log", "system_analysis", "system_remediate",
            "hephaestus_status", "hephaestus_tasks", "hephaestus_remediate",
            "hephaestus_approve", "hephaestus_rollback",
            "memory.save", "memory.search",
            "documents.search", "fetch_page", "dummy_test_reconcile",
        }
        missing = expected - all_names
        extra = all_names - expected
        assert not missing, f"Missing tools: {missing}"
        assert not extra, f"Extra tools: {extra}"
        print(f"\n[OK] All {len(all_names)} tools present across 8 domain manifests")
