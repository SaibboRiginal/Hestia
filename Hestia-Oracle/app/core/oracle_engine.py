"""OracleEngine — thin orchestrator for the Hestia Oracle service.

This module's only responsibility is to wire together the specialised
services and orchestrate the two main user-facing flows:

  1. chat()             — conversational + domain-query loop (NDJSON stream)
  2. analyze_document() — file analysis + background RAG archiving (NDJSON stream)

All business logic lives in the imported service/document modules.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone
from importlib import import_module
from pathlib import Path
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python without zoneinfo support
    ZoneInfo = None

from core.services.agent_factory import AgentFactory, conversation_style_contract
from core.services.hub_client import HubClient
from core.services import llm_stats
from core.services import activity_log
from core.services.chat_classifier import ChatClassifier, QUICK_CHAT_CONFIDENCE_THRESHOLD
from core.services import stream_emitter
from core.services import user_questions
from core.services import chat_sessions
from core.services import prompt_config
from core.services.context_builder import ContextBuilder
from core.services.memory_intent import (
    has_deprecate_intent,
    has_notification_intent,
    has_preference_intent,
    has_write_intent,
)
from core.services.memory_service import MemoryService
from core.services.user_control_service import UserControlService
from core.services.module_registry import ModuleToolRegistry
from core.services.retrieval_service import RetrievalService
from core.document.archiver import DocumentArchiver
from core.document.rag import DocumentRAG
from core.document.analyser import DocumentAnalyser
from core.agent_loop import run_agent_loop, ToolDefinition
from hestia_common.mcp_client import MCPClient, as_command
from hestia_common import origin as origin_mod
from hestia_common import ui_blocks
from core.services import conversation_goal
from core.services import loop_guard


def _resolve_task_lifecycle_store() -> type:
    try:
        module = import_module("hestia_common.task_lifecycle")
    except ModuleNotFoundError:
        _workspace_root = Path(__file__).resolve().parents[3]
        _shared_pkg = _workspace_root / "Hestia-Shared"
        if str(_shared_pkg) not in sys.path:
            sys.path.insert(0, str(_shared_pkg))
        module = import_module("hestia_common.task_lifecycle")
    return getattr(module, "TaskLifecycleStore")


TaskLifecycleStore = _resolve_task_lifecycle_store()

logger = logging.getLogger(f"hestia_oracle.{__name__}")
_STARTUP_TS = time.time()

# A quick answer (no tools) that says it did or will do something: «ho registrato», «riduco gli impegni».
_CLAIMED_ACTION = re.compile(
    r"(?<!non )\b(?:ho|abbiamo)\s+(?:gi[àa]\s+)?(?:registrat|salvat|annotat|segnat|impostat|creat|aggiunt|rimoss|cancellat|"
    r"eliminat|spostat|ridott|programmat|memorizzat|attivat|disattivat)\w*"
    r"|\b(?:registro|annoto|riduco|sposto|cancello|elimino|imposto|programmo|memorizzo)\s+(?:la|il|lo|gli|le|i|per|"
    r"tutt|ogni)\b", re.IGNORECASE)

# Tools every turn keeps whatever its domain: reminders, routines and asking the user back.
_ALWAYS_TOOLS = frozenset({"agenda_assistente_aggiungi", "routine_create", "ask_user", "module_manual"})

def _turn_tool_domains(available_domains: list[str], intent) -> list[str]:
    """Domains whose tools the agent gets this turn: the classified ones (+ ``_ALWAYS_TOOLS``) when the classifier
    is sure, else every domain. Every tool of every module is ~250 tools / 30k tokens per call, more than a local
    model's whole context (bench 2026-10-30)."""
    every = [d for d in available_domains if d != "general"]
    turn = [d for d in (intent.valid_domains or []) if d in every]
    return turn if turn and intent.confidence >= QUICK_CHAT_CONFIDENCE_THRESHOLD else every


_NUMERIC_SHORTHAND_PATTERN = re.compile(
    r"^\s*([0-9]+(?:[\.,][0-9]+)?)\s*([kKmM])\s*$")


def _parse_numeric_like(value: Any) -> int | float | None:
    """Parse ints/floats and shorthand numeric strings (e.g. 150k, 1.2m)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None

    # Remove common separators/symbols while keeping decimal point support.
    normalized = text.replace("€", "").replace("$", "").replace(" ", "")

    short = _NUMERIC_SHORTHAND_PATTERN.match(normalized)
    if short:
        base = float(short.group(1).replace(",", "."))
        unit = short.group(2).lower()
        multiplier = 1000 if unit == "k" else 1000000
        return base * multiplier

    # Heuristic for separators:
    # - If both ',' and '.' exist, treat ',' as thousands separators.
    # - If only ',' exists, treat as decimal separator.
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")

    try:
        return float(normalized)
    except Exception:
        return None


def _build_alert_payload_context(payload: Any) -> str:
    """Build compact, high-signal context notes for proactive alert formatting."""
    if not isinstance(payload, dict):
        return ""

    properties = payload.get("properties") if isinstance(
        payload.get("properties"), list) else []
    records = properties if properties else [payload]

    cities: list[str] = []
    prices: list[float] = []
    surfaces: list[float] = []

    for item in records:
        if not isinstance(item, dict):
            continue

        city = str(item.get("city") or item.get("locality") or "").strip()
        if not city:
            address = str(item.get("address") or "").strip()
            if address:
                city = address.split(",")[-1].strip()
        if city:
            cities.append(city)

        price_val = _parse_numeric_like(item.get("price"))
        if price_val is not None:
            prices.append(float(price_val))

        specs = item.get("specs") if isinstance(
            item.get("specs"), dict) else {}
        surface_val = _parse_numeric_like(
            item.get("surface_m2") or item.get("m2") or item.get("surface") or specs.get(
                "surface_m2") or specs.get("m2") or specs.get("surface")
        )
        if surface_val is not None:
            surfaces.append(float(surface_val))

    lines: list[str] = []
    lines.append(f"Totale elementi nel payload: {len(records)}")

    if cities:
        unique_cities = list(dict.fromkeys(cities))
        preview = ", ".join(unique_cities[:4])
        suffix = "" if len(unique_cities) <= 4 else ", ..."
        lines.append(f"Aree principali: {preview}{suffix}")

    if prices:
        lines.append(
            f"Range prezzi stimato: {int(min(prices))} - {int(max(prices))}")

    if surfaces:
        lines.append(
            f"Range superfici stimato (m2): {int(min(surfaces))} - {int(max(surfaces))}")

    if isinstance(payload.get("count"), int):
        lines.append(
            f"Conteggio dichiarato dal sorgente: {int(payload.get('count'))}")

    return "\n".join(lines).strip()


@dataclass
class SessionIntent:
    """Structured result of the CLASSIFY phase."""
    mode: str
    explicit_domain: str | None
    confidence: float
    valid_domains: list = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    filters_gt: dict = field(default_factory=dict)
    filters_lt: dict = field(default_factory=dict)
    sort_by: str | None = None
    sort_order: str | None = None
    action_intent: bool = False


def external_agent_system_prompt(preference_facts: list[str], client_instructions: str | None) -> str:
    """System prompt of the external agent (§D): Oracle's persona and style contract first (fixed prefix → the
    provider's prompt cache works), then the tool rule, preferences and this turn's instructions."""
    parts = [prompt_config.analyst_persona_default(), conversation_style_contract(),
             "Strumenti: usa SOLO gli strumenti MCP «hestia» per leggere o cambiare i dati di Hestia; se nessuno "
             "serve rispondi e basta. Le azioni importanti chiedono conferma all'utente: se lo strumento lo dice, "
             "riferiscilo."]
    if preference_facts:
        parts.append("PREFERENZE DELL'UTENTE:\n" + "\n".join(f"- {f}" for f in preference_facts[:10]))
    if client_instructions:
        parts.append(str(client_instructions).strip())
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _approval_ttl() -> int:
    from core.services import oracle_settings as _os
    return _os.get_int(_os.APPROVAL_TTL, 30)


def _error_payload_fails(outcome: tuple[bool, Any]) -> tuple[bool, Any]:
    """A module answering 200 with ``{"error": …}`` (e.g. «niente da spostare») did not do it: not ok, so the
    chat never shows «Fatto» nor lists it under «Ho fatto» (bench with a real model, 2026-10-30)."""
    ok, payload = outcome
    if ok and isinstance(payload, dict) and payload.get("error") and not payload.get("ok") \
            and not payload.get("saved"):
        return False, payload
    return ok, payload


class OracleEngine:
    """Top-level orchestrator — instantiate once per process."""

    def __init__(self) -> None:
        self._hub_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self._archive_url = os.getenv(
            "ARCHIVE_API_URL", "http://hestia_archive:19002/api")

        # ── LLM agents ────────────────────────────────────────────────────────
        # Chains are read live at every call: model settings changed from any client apply at once.
        self._agents = AgentFactory.create()
        from core.services import llm_migration, oracle_settings
        oracle_settings.settings.on_change(lambda changed: llm_migration.run(oracle_settings.settings))

        # ── Infrastructure services ───────────────────────────────────────────
        self._hub = HubClient(self._hub_url)
        # Tools of every module: only through Hestia's one MCP server (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2).
        self._mcp = MCPClient(self._hub_url, client="oracle")

        # Small TTL cache for quasi-static discovery endpoints (TTL: oracle.cache.schemas_ttl, live).
        self._domains_cache_value: list[str] = ["general"]
        self._domains_cache_ts: float = 0.0
        self._schemas_cache_value: dict = {}
        self._schemas_cache_ts: float = 0.0

        # Limits from settings oracle.context.* (read at use time).
        self._context_builder = ContextBuilder()

        module_tool_urls = [
            u.strip()
            for u in os.getenv("MODULE_TOOLS_URLS", "").split(",")
            if u.strip()
        ]
        if single := os.getenv("MODULE_TOOLS_URL", "").strip():
            module_tool_urls.append(single)

        self._module_registry = ModuleToolRegistry(
            module_tool_urls=module_tool_urls,
            ttl_seconds=None,  # setting oracle.cache.tool_registry_ttl (live)
            hub_api_url=self._hub_url,
        )

        self._retrieval_service = RetrievalService(
            archive_url=self._archive_url,
            hub_api_url=self._hub_url,
            module_registry=self._module_registry,
            embedder=self._embed,
        )

        # ── Preference domain classifier (embedding-based, no LLM) ──────────
        from core.services.preference_domains import PreferenceDomainClassifier
        _pref_classifier = PreferenceDomainClassifier(embed_fn=self._embed)

        self._memory_service = MemoryService(
            archive_url=self._archive_url,
            hub_api_url=self._hub_url,
            scribe_agent=self._agents.generic,
            context_builder=self._context_builder,
            pref_domain_classifier=_pref_classifier,
        )

        from core.services.mood_capture import MoodCapture
        self._mood_capture = MoodCapture(self._hub, self._memory_service._ask)

        self._control_service = UserControlService(
            hub_client=self._hub,
            scribe_agent=self._agents.generic,
        )

        self._classifier = ChatClassifier(
            router_agent=self._agents.generic,
        )

        # ── Document pipeline ─────────────────────────────────────────────────
        self._archiver = DocumentArchiver(
            hub_client=self._hub,
            embed_fn=self._embed,
            analyst=self._agents.documents,
        )

        self._doc_rag = DocumentRAG(
            hub_client=self._hub,
            embed_fn=self._embed,
        )

        self._doc_analyser = DocumentAnalyser(
            hub_client=self._hub,
            archiver=self._archiver,
            analyst=self._agents.documents,
            style_contract_fn=conversation_style_contract,
        )

        # ── Cross-client question store ────────────────────────────────────────
        # In-process dict: question_id → {session_id, question, answer, resolved}
        # Future: persist to Archive for multi-process / restart resilience.
        self._pending_questions: dict[str, dict] = {}
        self._questions_lock = threading.Lock()
        # session → client (webui, telegram…) of its last chat turn: tool calls carry it to the modules
        # (X-Hestia-Client), so e.g. a Themis proposal made in a chat is confirmed in that same chat.
        self._session_clients: dict[str, str] = {}
        # session → origin of its current turn (hestia_common.origin): tool calls carry it to the modules.
        self._session_origins: dict[str, dict] = {}

        # ── Phase 2: query-source execution policy matrix ─────────────────────
        # Timeouts per request source: settings oracle.timeouts.* (oracle_settings.timeout, live).
        from core.services import oracle_settings as _os
        self._task_store = TaskLifecycleStore(max_tasks=_os.get_int(_os.TASKS_MAX, 50))
        _os.settings.on_change(
            lambda changed: setattr(self._task_store, "_max_tasks", _os.get_int(_os.TASKS_MAX, 50))
            if _os.TASKS_MAX in changed else None)

        # User's local time = container TZ (infrastructure, same for every module).
        self._oracle_timezone = str(os.getenv("TZ", "Europe/Rome")).strip() or "Europe/Rome"

        # ── High-impact action approval gate (settings oracle.approval.*, read at use time) ──
        self._pending_action_approvals: dict[str, dict[str, Any]] = {}
        self._approval_lock = threading.Lock()

        # ── Athena advisory hints (Hub-routed ingest; TTL/max: oracle.hints.*) ──
        self._athena_hints: list[dict[str, Any]] = []
        self._athena_hints_lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def list_background_tasks(
        self,
        limit: int = 100,
        task_type: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._task_store.list_tasks(
            limit=limit,
            task_type=task_type,
            lifecycle_state=lifecycle_state,
        )

    def get_background_task(self, task_id: str) -> dict[str, Any] | None:
        return self._task_store.get_task(task_id)

    def ingest_athena_hint(
        self,
        hint_payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist an advisory Athena hint in the in-memory hint buffer."""
        from core.services import oracle_settings as _os
        if not _os.get_bool(_os.HINTS_ENABLED):
            return {
                "status": "disabled",
                "stored": False,
                "reason": f"{_os.HINTS_ENABLED}=false",
            }

        now = time.time()
        ttl_seconds = int(hint_payload.get("ttl_seconds")
                          or _os.get_int(_os.HINTS_TTL, 30))
        ttl_seconds = max(30, ttl_seconds)

        hint_id = str(hint_payload.get("hint_id") or uuid.uuid4().hex)
        session_id = str(hint_payload.get("session_id") or "").strip() or None

        raw_domains = hint_payload.get("domains")
        domains: list[str] = []
        if isinstance(raw_domains, list):
            domains = [str(item).strip().lower()
                       for item in raw_domains if str(item).strip()]
        domain_single = str(hint_payload.get("domain") or "").strip().lower()
        if domain_single and domain_single not in domains:
            domains.append(domain_single)
        if not domains:
            domains = ["general"]

        row = {
            "hint_id": hint_id,
            "source": str(hint_payload.get("source") or "athena"),
            "hint_type": str(hint_payload.get("hint_type") or "focus_brief"),
            "session_id": session_id,
            "domains": domains,
            "priority": str(hint_payload.get("priority") or "normal"),
            "summary": str(hint_payload.get("summary") or "").strip(),
            "brief": hint_payload.get("brief") if isinstance(hint_payload.get("brief"), dict) else {},
            "gate": hint_payload.get("gate") if isinstance(hint_payload.get("gate"), dict) else {},
            "retrospective": hint_payload.get("retrospective") if isinstance(hint_payload.get("retrospective"), dict) else {},
            "trace_id": str(trace_id or hint_payload.get("trace_id") or "").strip() or None,
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "metadata": hint_payload.get("metadata") if isinstance(hint_payload.get("metadata"), dict) else {},
        }

        with self._athena_hints_lock:
            self._cleanup_expired_athena_hints_locked(now=now)
            self._athena_hints = [h for h in self._athena_hints if str(
                h.get("hint_id")) != hint_id]
            self._athena_hints.append(row)
            hints_max = _os.get_int(_os.HINTS_MAX, 1)
            if len(self._athena_hints) > hints_max:
                self._athena_hints = self._athena_hints[-hints_max:]

        logger.info(
            "event=athena_hint_ingested hint_id=%s trace_id=%s session_id=%s domains=%s priority=%s",
            hint_id,
            str(row.get("trace_id") or ""),
            str(session_id or ""),
            ",".join(domains),
            str(row.get("priority") or "normal"),
        )
        return {
            "status": "ok",
            "stored": True,
            "hint": row,
        }

    def list_athena_hints(
        self,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._athena_hints_lock:
            self._cleanup_expired_athena_hints_locked()
            rows = list(self._athena_hints)

        normalized_session = str(session_id or "").strip()
        if normalized_session:
            rows = [
                row for row in rows
                if not row.get("session_id") or str(row.get("session_id")) == normalized_session
            ]

        rows.sort(key=lambda item: float(
            item.get("created_at") or 0.0), reverse=True)
        return rows[: max(1, min(int(limit), 200))]

    def respond_high_impact_action_approval(
        self,
        approval_token: str,
        approve: bool,
        actor: str | None = None,
        client_instructions: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a pending high-impact action approval token."""
        token = str(approval_token or "").strip()
        if not token:
            return {
                "status": "invalid",
                "approved": bool(approve),
                "error": "approval_token missing",
            }

        self._cleanup_expired_action_approvals()
        with self._approval_lock:
            pending = self._pending_action_approvals.pop(token, None)

        with self._questions_lock:
            self._pending_questions.pop(token, None)

        if not pending:
            return {
                "status": "not_found",
                "approved": bool(approve),
                "error": "approval token not found or expired",
            }

        if not approve:
            logger.info(
                "event=high_impact_approval_rejected token=%s command=%s actor=%s",
                token,
                pending.get("action_name"),
                str(actor or "system"),
            )
            return {
                "status": "canceled",
                "approved": False,
                "approval_token": token,
                "command": pending.get("action_name"),
                "title": pending.get("title"),
            }

        resolved_client_instructions = str(client_instructions or "").strip() or str(
            pending.get("client_instructions") or "").strip() or None
        result = self._execute_selected_action(
            matched=pending.get("matched") or {},
            action_name=str(pending.get("action_name") or ""),
            param_sets=pending.get("param_sets") if isinstance(
                pending.get("param_sets"), list) else [],
            session_id=str(pending.get("session_id") or ""),
            notify_target=str(pending.get("notify_target")
                              or "").strip() or None,
            trace_id=str(pending.get("trace_id") or "").strip() or None,
            client_instructions=resolved_client_instructions,
        )
        status = "approved_executed" if bool(
            result.get("executed")) else "approved_failed"
        logger.info(
            "event=high_impact_approval_resolved token=%s command=%s actor=%s status=%s",
            token,
            pending.get("action_name"),
            str(actor or "system"),
            status,
        )
        return {
            "status": status,
            "approved": True,
            "approval_token": token,
            "result": result,
        }

    def ask_question(
        self,
        session_id: str,
        question_id: str,
        header: str,
        prompt: str,
        kind: str = "free_text",
        options: list | None = None,
        timeout_sec: int | None = None,
        required: bool = True,
        actions: dict | None = None,
        resume: bool = False,
        allow_other: bool = False,
    ) -> str:
        """Register a pending question and return the NDJSON question frame to emit.
        ``actions`` = ``{answer value: {service, method, path, body}}``: the chosen one is routed through Hub
        when the user answers (``<client>`` in the body → the answering client).
        ``resume`` = asked by the model (tool ask_user): the answer becomes the next chat turn and the question is
        also kept in Archive (v3 A)."""
        from core.services import oracle_settings as _os
        entry = {
            "question_id": question_id,
            "session_id": session_id,
            "header": header,
            "prompt": prompt,
            "kind": kind,
            "options": options or [],
            "allow_other": bool(allow_other),
            "answer": None,
            "resolved": False,
            "actions": actions or {},
            "resume": bool(resume),
            "asked_at": datetime.now(datetime_timezone.utc).isoformat(),
        }
        if resume:
            entry["expires_at"] = user_questions.expires_at(_os.get_int(_os.ASK_TIMEOUT, 1))
            timeout_sec = timeout_sec or _os.get_int(_os.ASK_TIMEOUT, 1) * 3600
        with self._questions_lock:
            self._pending_questions[question_id] = entry
        if resume:
            user_questions.save(self._hub, entry)
        self._append_interaction_ledger(
            event_type="question_asked",
            session_id=session_id,
            actor="assistant",
            domain="general",
            reference_id=question_id,
            payload={
                "header": header,
                "prompt": prompt,
                "kind": kind,
                "options": options or [],
                "required": required,
                "timeout_sec": timeout_sec,
            },
        )
        return stream_emitter.emit_question(
            question_id=question_id,
            header=header,
            prompt="" if resume else prompt,  # ask_user: the question itself is the turn's answer text
            kind=kind,
            options=options,
            timeout_sec=timeout_sec,
            required=required,
            allow_other=allow_other,
        )

    def _trace_headers(self, session_id: str, trace_id: str | None = None) -> dict:
        headers = {"X-Session-Id": session_id}
        if trace_id:
            headers["X-Trace-Id"] = str(trace_id)
        client = self._session_clients.get(session_id)
        if client:
            headers["X-Hestia-Client"] = client
        return headers

    def _policy_timeout(self, source: str, fallback: int = 10) -> int:
        """Return configured timeout seconds for a given execution source."""
        from core.services import oracle_settings
        try:
            return max(1, int(oracle_settings.timeout(source, fallback)))
        except Exception:
            return max(1, int(fallback))

    def _cleanup_expired_athena_hints_locked(self, now: float | None = None) -> None:
        ts = time.time() if now is None else float(now)
        self._athena_hints = [
            row for row in self._athena_hints
            if float(row.get("expires_at") or 0.0) > ts
        ]

    def _select_relevant_athena_hints(
        self,
        session_id: str,
        valid_domains: list[str],
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        from core.services import oracle_settings as _os
        if not _os.get_bool(_os.HINTS_ENABLED):
            return []

        normalized_session = str(session_id or "").strip()
        domain_set = {str(item).strip().lower()
                      for item in (valid_domains or []) if str(item).strip()}
        if not domain_set:
            domain_set = {"general"}

        with self._athena_hints_lock:
            self._cleanup_expired_athena_hints_locked()
            rows = list(self._athena_hints)

        candidates: list[dict[str, Any]] = []
        for row in rows:
            row_session = str(row.get("session_id") or "").strip()
            if row_session and normalized_session and row_session != normalized_session:
                continue

            row_domains = {
                str(item).strip().lower()
                for item in (row.get("domains") or [])
                if str(item).strip()
            }
            if row_domains and "general" not in row_domains and not (row_domains & domain_set):
                continue

            candidates.append(row)

        candidates.sort(key=lambda item: float(
            item.get("created_at") or 0.0), reverse=True)
        return candidates[: max(1, min(int(limit), 10))]

    @staticmethod
    def _format_athena_hints_for_prompt(hints: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            summary = str(hint.get("summary") or "").strip()
            if not summary:
                continue

            priority = str(hint.get("priority") or "normal").strip().lower()
            domains = ", ".join(hint.get("domains") or ["general"])
            gate = hint.get("gate") if isinstance(
                hint.get("gate"), dict) else {}
            score = gate.get("score")
            threshold = gate.get("threshold")

            line = f"- [{priority}] {summary}"
            meta_parts: list[str] = []
            if domains:
                meta_parts.append(f"domains={domains}")
            if score is not None:
                meta_parts.append(f"score={score}")
            if threshold is not None:
                meta_parts.append(f"threshold={threshold}")
            if meta_parts:
                line += f" ({', '.join(meta_parts)})"

            lines.append(line)

        return "\n".join(lines).strip()

    def answer_question(self, question_id: str, answer: str) -> bool:
        """Record the user's answer to a pending question. Returns True if found."""
        with self._questions_lock:
            entry = self._pending_questions.get(question_id)
        if not entry and question_id.startswith("ask_"):
            # Asked before an Oracle restart: the pending question is in Archive.
            entry = user_questions.load(self._hub, question_id)
            if entry and not entry.get("resolved"):
                with self._questions_lock:
                    self._pending_questions[question_id] = entry
        with self._questions_lock:
            entry = self._pending_questions.get(question_id)
            if not entry or entry.get("resolved"):
                return False
            if entry.get("resume") and user_questions.expired(entry):
                logger.info("event=user_question_expired question_id=%s", question_id)
                return False
            entry["answer"] = answer
            entry["resolved"] = True
        if entry.get("resume"):
            user_questions.save(self._hub, entry, deleted=True)
        self._append_interaction_ledger(
            event_type="question_answered",
            session_id=str(entry.get("session_id") or ""),
            actor="user",
            domain="general",
            reference_id=question_id,
            payload={"answer": answer},
        )
        return True

    def run_question_action(self, question_id: str, answer: str, client: str = "") -> dict | None:
        """Route the action bound to the chosen answer (module-made confirm cards, e.g. Themis proposals).
        None when the question has no actions (a plain question the agent reads back)."""
        with self._questions_lock:
            entry = self._pending_questions.get(question_id) or {}
            action = (entry.get("actions") or {}).get(str(answer or "").strip())
            session_id = str(entry.get("session_id") or "")
        if not action:
            return None
        who = client or self._session_clients.get(session_id) or "user"
        body = json.loads(json.dumps(action.get("body") or {}).replace('"<client>"', json.dumps(who)))
        try:
            ok, result = self._hub.route_to_service(
                service=str(action.get("service") or ""), path=str(action.get("path") or "").lstrip("/"),
                method=str(action.get("method") or "POST").upper(), body=body or None, query={},
                timeout=self._policy_timeout("action_service_route"), headers=self._trace_headers(session_id))
        except Exception as exc:
            ok, result = False, str(exc)
        logger.info("event=question_action_routed question_id=%s answer=%s service=%s ok=%s",
                    question_id, answer, action.get("service"), ok)
        if not ok:
            logger.warning("[🔄] event=question_action_failed question_id=%s result=%s", question_id, str(result)[:200])
        return {"ok": bool(ok), "result": result if isinstance(result, (dict, list)) else str(result)[:300]}

    def question_resume_message(self, question_id: str, answer: str) -> str | None:
        """For a question the model asked (ask_user): the next chat message that carries the answer."""
        with self._questions_lock:
            entry = dict(self._pending_questions.get(question_id) or {})
        if not entry.get("resume"):
            return None
        return user_questions.resume_message(entry, answer)

    def open_questions(self, session_id: str) -> list[dict]:
        """Questions the model asked in this session still waiting for an answer (clients redraw them)."""
        rows = user_questions.open_for_session(self._hub, session_id)
        return [{"question_id": r.get("question_id"), "header": r.get("header"), "prompt": r.get("prompt"),
                 "kind": r.get("kind"), "options": r.get("options") or [], "allow_other": bool(r.get("allow_other")),
                 "required": True, "asked_at": r.get("asked_at")} for r in rows]

    def get_question_answer(self, question_id: str) -> Optional[str]:
        """Return the recorded answer for question_id, or None if unresolved."""
        with self._questions_lock:
            entry = self._pending_questions.get(question_id)
            if entry and entry.get("resolved"):
                return entry.get("answer")
        return None

    def _append_interaction_ledger(
        self,
        *,
        event_type: str,
        session_id: str,
        actor: str,
        domain: str,
        reference_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Best-effort interaction ledger write via Hub-routed Archive."""
        try:
            self._hub.append_interaction_ledger(
                event_type=event_type,
                session_id=session_id,
                actor=actor,
                domain=domain,
                source_service="oracle",
                reference_id=reference_id,
                payload=payload or {},
            )
        except Exception as exc:
            logger.trace(
                "event=interaction_ledger_append_failed_non Interaction ledger append failed (non-fatal): %s", exc)

    def chat(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        force_notification_compiler: bool = False,
        client_instructions: str | None = None,
        save_history: bool = True,
        mode: str = "auto",
        model: str = "generic",
        client: str = "",
        origin: dict | None = None,
    ):
        """Main conversational loop. Yields NDJSON lines.

        *origin* (``hestia_common.origin.parse``) = who started the turn, decided by the system: ``utente`` acts
        with the usual confirmation gate, ``routine`` only inside its instruction, ``autonomo`` only reads,
        proposes and notifies (Cindy 6).

        Modes (control PROCESS, same model for all; main.py resolves "" from oracle.chat.mode):
          quick    → single ask(), no classify, no tools. <2s latency.
          auto     → classify → agent loop if domain_query. Default.
          thinking → always agent loop (no quick-chat shortcut), model reasoning on.
          cot      → always agent loop, deep reasoning, higher max_turns, step-by-step plan.

        Model (controls which BRAIN — the chain of the slot's use case, settings oracle.usecases / oracle.chains):
          generic   → daily driver
          reasoning → deep thinking (loaded on demand)
          code      → code generation
        """
        t0 = time.perf_counter()
        trace_id = uuid.uuid4().hex[:12]
        usage_before = llm_stats.session_usage(session_id)

        def _record_turn(route: str, domains: list[str] | None = None, tool_log: list | None = None) -> None:
            # Inside view (WebUI page Cervello, GET /api/ui/activity): one row per finished turn.
            activity_log.record_turn(
                session_id=session_id, client=client, mode=mode, route=route, model=agent.model_name,
                provider=agent.provider, domains=domains, tool_log=tool_log,
                total_ms=int((time.perf_counter() - t0) * 1000), message=user_message,
                usage_before=usage_before, usage_after=llm_stats.session_usage(session_id), trace_id=trace_id)

        if client and session_id:
            self._session_clients[session_id] = str(client)[:40]
        # The HTTP endpoint always passes the parsed origin (fail closed there); a direct in-process call is trusted.
        origin = dict(origin or origin_mod.parse({origin_mod.HEADER: "utente"}, client))
        if session_id:
            self._session_origins[session_id] = origin
        # Conversation goal (Cindy 23): «obiettivo: …» fixes it, «ferma l'obiettivo» stops it.
        _goal_text = conversation_goal.parse_prefix(user_message) if origin["level"] == "utente" else ""
        if _goal_text:
            conversation_goal.set_goal(self._hub, session_id, _goal_text)
            if mode == "quick":
                mode = "thinking"
        elif origin["level"] == "utente" and conversation_goal.is_stop(user_message):
            conversation_goal.end(self._hub, session_id, "fermato")
        logger.trace("event=chat_entry trace_id=%s session_id=%s mode=%s model=%s msg=%s",
                     trace_id, session_id, mode, model,
                     json.dumps(user_message[:120], ensure_ascii=False))
        logger.info(
            "event=chat_turn_start trace_id=%s session_id=%s msg_len=%s save_history=%s force_notification_compiler=%s",
            trace_id,
            session_id,
            len(user_message or ""),
            bool(save_history),
            bool(force_notification_compiler),
        )
        logger.trace(
            "event=chat_user_message trace_id=%s session_id=%s message=%s",
            trace_id,
            session_id,
            json.dumps(user_message, ensure_ascii=False),
        )

        # ── Resolve agent by use case ──────────────────────────────────────────
        agent = self._resolve_agent(model)
        # Brain mode (dossier 2026-10-19-oracle-a-blocchi §D): esterna = an agent CLI runs the loop below.
        from core.services import external_agent, llm_chains
        chat_use_case = llm_chains.SLOTS.get(model, llm_chains.GENERAL)
        external = external_agent.mode_for(chat_use_case) == "esterna"
        logger.trace("event=chat_agent_resolved trace_id=%s agent_type=%s model=%s provider=%s thinking=%s",
                     trace_id, type(agent).__name__, agent.model_name, agent.provider, agent.thinking)
        logger.info(
            "event=chat_model_selected trace_id=%s session_id=%s mode=%s model=%s provider=%s thinking=%s",
            trace_id,
            session_id,
            mode,
            agent.model_name,
            agent.provider,
            agent.thinking,
        )

        # ── Phase 1: INIT ─────────────────────────────────────────────────────
        yield stream_emitter.emit_status("📂 Recupero cronologia e routing...")
        t_init = time.perf_counter()
        history_text, available_domains, schemas = self._phase_init(
            session_id,
            trace_id=trace_id,
        )

        # ── MODE: quick (in esterna the agent answers every turn) ─────────────
        if mode == "quick" and not external:
            yield stream_emitter.emit_status("💬 Risposta rapida...")
            temporal_context = self._current_datetime_context()
            answer = self._quick_answer(
                user_message, history_text, client_instructions,
                extra_context=None, current_datetime_context=temporal_context,
            )
            logger.trace(
                "event=chat_quick_answer trace_id=%s session_id=%s answer=%s",
                trace_id,
                session_id,
                json.dumps(answer, ensure_ascii=False),
            )
            if save_history:
                self._save_history(session_id, user_message, answer, trace_id=trace_id)
            yield stream_emitter.emit_final(answer, "general")
            _record_turn("quick")
            logger.info(
                "event=chat_done_summary session_id=%s total_ms=%s mode=quick model=%s provider=%s thinking=%s tools=0 answer_len=%s trace_id=%s",
                session_id,
                int((time.perf_counter() - t0) * 1000),
                agent.model_name,
                agent.provider,
                agent.thinking,
                len(answer or ""),
                trace_id,
            )
            _mem_waiter = self._phase_background_memory(
                user_message, session_id, notify_target,
                force_notification_compiler, trace_id=trace_id,
            )

            yield from self._memory_notice_frames(_mem_waiter)
            return
        logger.trace(
            "event=chat_phase_timing_ms Chat phase timing | session=%s phase=init ms=%s domains=%s",
            session_id,
            int((time.perf_counter() - t_init) * 1000),
            len(available_domains or []),
        )

        # ── Phase 2: CLASSIFY (single call: mode + domain + action_intent) ────
        temporal_context = self._current_datetime_context()
        t_classify = time.perf_counter()
        intent = self._phase_classify(
            user_message,
            history_text,
            available_domains,
            schemas,
            current_datetime_context=temporal_context,
        )
        logger.info(
            "event=chat_classify_result trace_id=%s session_id=%s mode=%s domain=%s conf=%.2f valid_domains=%s action_intent=%s",
            trace_id,
            session_id,
            intent.mode,
            intent.explicit_domain,
            intent.confidence,
            intent.valid_domains,
            intent.action_intent,
        )
        if intent.confidence < 0.3:
            logger.warning(
                "event=chat_classify_low_confidence trace_id=%s session_id=%s mode=%s domain=%s conf=%.2f available_domains=%s msg_preview=%s",
                trace_id,
                session_id,
                intent.mode,
                intent.explicit_domain,
                intent.confidence,
                available_domains,
                (user_message or "")[:120],
            )

        # ── Structural invariant: system domain → domain_query ──────────────
        # "system" domain means operational queries that need live tool data.
        # If the classifier returned domain=system but mode=quick_chat, that
        # is an internal contradiction — correct it.
        if (
            intent.mode == "quick_chat"
            and (
                intent.explicit_domain == "system"
                or "system" in intent.valid_domains
            )
        ):
            logger.info(
                "event=chat_classify_override_system route=%s domain=%s "
                "conf=%.2f — forcing domain_query (system domain requires tools)",
                intent.mode,
                intent.explicit_domain,
                intent.confidence,
            )
            intent.mode = "domain_query"
            if not intent.explicit_domain:
                intent.explicit_domain = "system"
            if "system" not in intent.valid_domains:
                intent.valid_domains = ["system"] + [
                    d for d in intent.valid_domains if d != "system"
                ]

        # ── Phase 3: QUICK CHAT shortcut ──────────────────────────────────────
        # Pensata / CoT were chosen by the user: always reason with the agent loop.
        if (intent.mode == "quick_chat" and intent.confidence >= QUICK_CHAT_CONFIDENCE_THRESHOLD
                and mode not in ("thinking", "cot") and not external):
            yield stream_emitter.emit_status("💬 Conversazione rapida...")
            extra_context = ""
            if self._doc_rag.message_is_about_docs(user_message):
                extra_context = self._doc_rag.list_user_docs_brief(
                    chat_id=notify_target, session_id=session_id)
            answer = self._quick_answer(
                user_message,
                history_text,
                client_instructions,
                extra_context or None,
                current_datetime_context=temporal_context,
            )
            if save_history:
                self._save_history(session_id, user_message,
                                   answer, trace_id=trace_id)

            sync_signals, sync_attempted = self._sync_memory_if_needed(
                user_message=user_message,
                session_id=session_id,
                notify_target=notify_target,
                force_notification_compiler=force_notification_compiler,
            )
            if sync_attempted:
                for signal in (sync_signals or []):
                    yield stream_emitter.emit_signal(
                        event=str(signal.get("event") or "memory.updated"),
                        message=str(signal.get("message")
                                    or "Aggiornamento memoria completato."),
                        data=signal.get("data") if isinstance(
                            signal.get("data"), dict) else {},
                    )

            quick_total_ms = int((time.perf_counter() - t0) * 1000)
            logger.trace(
                "event=chat_quick_chat_answer trace_id=%s session_id=%s answer=%s",
                trace_id,
                session_id,
                json.dumps(answer, ensure_ascii=False),
            )
            logger.info(
                "event=chat_done_summary session_id=%s total_ms=%s mode=quick_chat model=%s provider=%s thinking=%s tools=0 answer_len=%s trace_id=%s",
                session_id,
                quick_total_ms,
                agent.model_name,
                agent.provider,
                agent.thinking,
                len(answer or ""),
                trace_id,
            )
            yield stream_emitter.emit_final(answer, "general")
            _record_turn("quick_chat", ["general"])
            _mem_waiter = self._phase_background_memory(
                user_message, session_id, notify_target,
                force_notification_compiler,
                skip_memory_extract=sync_attempted,
                trace_id=trace_id,
            )

            yield from self._memory_notice_frames(_mem_waiter)
            return

        # ── Phase 4: AGENT LOOP (unified — all tools, all commands) ───────────
        yield stream_emitter.emit_status(
            f"🧠 Analisi domini: {', '.join(intent.valid_domains)}..."
        )

        # Load preferences for agent loop context
        all_prefs = self._load_preferences(intent.valid_domains)
        preference_facts = [str(p.get("fact", "")).strip()
                            for p in all_prefs if p.get("fact")]

        # ── Skill discovery (once per session, embedding-based) ────────────
        # Hermes Agent pattern: progressive disclosure — embed user message,
        # search Archive for matching skills, inject top matches into prompt.
        _primary_domain = intent.valid_domains[0] if intent.valid_domains else "general"
        _matched_skills = self._discover_skills(
            user_message, _primary_domain, session_id)
        _skill_hint_block = ""
        if _matched_skills:
            _skill_lines: list[str] = []
            for sk in _matched_skills:
                _sn = sk.get("skill_name", sk.get("name", "unknown"))
                _sd = sk.get("description", "")
                _ss = sk.get("_similarity", 0)
                _seq = sk.get("tool_sequence", [])
                _seq_str = " → ".join(
                    s.get("tool", str(s)) for s in _seq
                ) if isinstance(_seq, list) else str(_seq)
                _skill_lines.append(
                    f"• {_sn} (match={_ss:.0%}): {_sd}\n"
                    f"  Tool sequence: {_seq_str}"
                )
            _skill_hint_block = (
                "SKILL MATCHES — these workflows were successful in similar past sessions. "
                "You can execute the tool sequence directly instead of reasoning from scratch:\n"
                + "\n".join(_skill_lines)
            )
            logger.info(
                "event=skills_injected session_id=%s count=%d domain=%s",
                session_id, len(_matched_skills), _primary_domain,
            )

        # Select Athena hints
        athena_hints = self._select_relevant_athena_hints(
            session_id=session_id,
            valid_domains=intent.valid_domains,
            limit=3,
        )
        athena_hint_prompt_block = self._format_athena_hints_for_prompt(
            athena_hints)

        # Planner behaviour contract (A/B variant gating)
        planner_contract, planner_variant, _ = prompt_config.prompt_with_variant(
            "planner_behavior_contract",
            surface="planner_behavior",
            seed=session_id,
        )

        build_domains = _turn_tool_domains(available_domains, intent)
        if not build_domains:
            logger.warning(
                "event=chat_no_domain_tools_available session_id=%s available_domains=%s",
                session_id, available_domains,
            )
        domain_tools = self._build_domain_tools(
            intent,
            session_id,
            notify_target,
            trace_id=trace_id,
            fallback_domains=build_domains,
        )
        logger.info(
            "event=chat_tools_built trace_id=%s session_id=%s tools=%s domains=%s available=%s action_intent=%s",
            trace_id,
            session_id,
            len(domain_tools),
            build_domains,
            available_domains,
            intent.action_intent,
        )

        domain_tools += self._turn_tools(session_id, origin)
        self._apply_origin_gate(domain_tools, origin)

        # Assemble agent loop client instructions
        agent_loop_client_instructions_parts: list[str] = []
        _origin_line = origin_mod.prompt_line(origin)
        if _origin_line:
            agent_loop_client_instructions_parts.append(_origin_line)
        _module_index = self._module_registry.index_text()
        if _module_index:
            agent_loop_client_instructions_parts.append(
                "MODULI (quando usarli; module_manual(modulo) per il manuale):\n" + _module_index)
        _goal = conversation_goal.active(self._hub, session_id)
        if _goal:
            agent_loop_client_instructions_parts.append(f"OBIETTIVO della conversazione: {_goal['text']}")
        if self._wants_ui_blocks(client):
            agent_loop_client_instructions_parts.append(ui_blocks.PROMPT)
        if planner_contract:
            agent_loop_client_instructions_parts.append(planner_contract)
        action_tool_policy = prompt_config.prompt("agent_action_tool_policy").strip()
        if intent.action_intent and action_tool_policy:
            agent_loop_client_instructions_parts.append(action_tool_policy)
        if athena_hint_prompt_block:
            agent_loop_client_instructions_parts.append(
                f"ATHENA_ADVISORY_HINTS:\n{athena_hint_prompt_block}")
        if _skill_hint_block:
            agent_loop_client_instructions_parts.append(_skill_hint_block)
        if temporal_context:
            agent_loop_client_instructions_parts.append(
                f"CURRENT_DATETIME_CONTEXT:\n{temporal_context}")
        if "system" in intent.valid_domains:
            agent_loop_client_instructions_parts.append(
                "SYSTEM: domanda su stato/salute di Hestia o richiesta di "
                "svilupparla. CHIAMA i tool system prima di rispondere. "
                "Mai rispondere da history o a memoria."
            )
        if mode == "cot":
            agent_loop_client_instructions_parts.append(
                "MODALITÀ CoT: scomponi la richiesta in passi, verifica ogni passo "
                "(strumenti se servono), poi rispondi. In fondo alla risposta: "
                "«Passi:» con 2-5 righe brevi del ragionamento seguito."
            )
        if client_instructions and str(client_instructions).strip():
            agent_loop_client_instructions_parts.append(
                str(client_instructions).strip())
        agent_loop_client_instructions = "\n\n".join(
            agent_loop_client_instructions_parts) or None

        # ── Collect thinking events emitted during the agent loop ─────────────
        thinking_ndjson_lines: list[str] = []

        def _on_thinking(ndjson_line: str) -> None:
            thinking_ndjson_lines.append(ndjson_line)

        # Streaming callback for the final answer turn
        def _stream_final(prompt: str) -> Iterator[str]:
            for tok in self._agents.generic.ask_stream(prompt):
                yield tok

        yield stream_emitter.emit_status("🔄 Ciclo agente in corso...")
        t_agent_loop = time.perf_counter()

        # Resolve max turns: higher when action_intent is True (complex tasks)
        from core.services import oracle_settings as _os
        _default_max_turns = _os.get_int(_os.MAX_TURNS, 1)
        resolved_max_turns = _default_max_turns
        # auto / thinking: reasoning on · cot: deep reasoning + more turns
        # quick mode: never reaches here (caught above)
        _is_thinking_mode = mode in ("thinking", "cot", "auto")
        if mode == "cot":
            resolved_max_turns = max(resolved_max_turns, 50)
            yield stream_emitter.emit_status("🧠 Modalità CoT — ragionamento passo passo...")
        elif mode == "thinking":
            yield stream_emitter.emit_status("🧠 Modalità pensata — ragiono prima di rispondere...")

        # Mode controls the think level; model (resolved above) controls the brain.
        # Any mode × any model combination works — mode and model are independent.
        # Level: auto/thinking → True, cot → "deep" (Ollama: both = think on; Claude: medium/high effort).
        _think_level = "deep" if mode == "cot" else _is_thinking_mode
        _ask_tools_bound = lambda p, tm: self._ask_analyst_with_tools(
            p, tm, agent_override=agent, thinking=_think_level)

        # ── OpenClaw pattern: auto-compaction callback ─────────────────────
        # Called by agent_loop when token threshold exceeded.  Returns
        # compacted history text (or None if compaction was skipped).
        _session_id = session_id
        def _auto_compact() -> str | None:
            result = self.compact_context(_session_id)
            if "error" in result:
                return None
            # Reload compacted history from Archive
            try:
                history_data = self._hub.get(
                    f"/chat/history/{_session_id}?limit={self._context_builder.history_fetch_limit}",
                    timeout=self._policy_timeout("foreground_chat"),
                    headers=self._trace_headers(_session_id, trace_id),
                )
                return self._context_builder.compact_history(history_data, _session_id)
            except Exception:
                return None

        answer = None
        _prior_actions: list[dict] = []
        if external:
            yield stream_emitter.emit_status("🤖 Agente esterno al lavoro...")
            try:
                answer, tool_log = external_agent.run_turn(
                    session_id=session_id, user_message=user_message,
                    system_prompt=external_agent_system_prompt(preference_facts, agent_loop_client_instructions),
                    primer=history_text, tools=domain_tools, use_case=chat_use_case)
                tokens = [answer]
            except external_agent.AgentError as exc:
                # Writes the agent already did must not run twice (Cindy 2): the internal loop continues from them.
                _prior_actions = [e for e in (getattr(exc, "log", None) or []) if e.get("ok")]
                if external_agent.brain()["fallback"] != "interna":
                    answer, tokens, tool_log = ("⚠️ L'agente esterno non ha risposto. Riprova tra poco.",
                                                ["⚠️ L'agente esterno non ha risposto. Riprova tra poco."], [])
                else:
                    logger.warning("[🔄] event=chat_external_agent_failed session_id=%s fallback=interna error=%s",
                                   session_id, str(exc)[:200])
                    yield stream_emitter.emit_status("🔄 Agente esterno non disponibile: rispondo io...")
        if answer is None:
            external_agent.note_internal_turn(session_id)
            answer, tokens, tool_log = run_agent_loop(
                user_message=user_message,
                history_text=history_text,
                preference_facts=preference_facts,
                tools=domain_tools,
                ask_fn=lambda p: self._ask_analyst(p, thinking=_think_level),
                ask_tools_fn=_ask_tools_bound,
                stream_fn=_stream_final,
                client_instructions=agent_loop_client_instructions,
                conversation_style=conversation_style_contract(),
                max_turns=resolved_max_turns,
                on_thinking=_on_thinking,
                action_intent=intent.action_intent,
                compact_fn=_auto_compact,
                guard_checker=loop_guard.llm_checker,
                prior_actions=_prior_actions,
            )
            tool_log = list(_prior_actions) + list(tool_log)

        # ── Conversation goal rounds (Cindy 23): after the owner's message is answered ────────────
        if origin["level"] == "utente" and not any(e.get("ask") for e in tool_log):
            _goal_answer, _goal_log, _goal_frames = self._goal_rounds(
                session_id=session_id, history_text=history_text, preference_facts=preference_facts,
                tools=domain_tools, ask_tools=_ask_tools_bound, think_level=_think_level,
                instructions=agent_loop_client_instructions)
            thinking_ndjson_lines.extend(_goal_frames)
            if _goal_answer:
                answer = f"{answer}\n\n{_goal_answer}".strip()
                tokens = [answer]
            tool_log = list(tool_log) + list(_goal_log)
        agent_loop_ms = int((time.perf_counter() - t_agent_loop) * 1000)
        logger.info(
            "event=chat_agent_loop_done trace_id=%s session_id=%s turns=%s tools_called=%s tools_available=%s tokens=%s answer_len=%s agent_loop_ms=%s model=%s provider=%s thinking=%s max_turns=%s domains=%s",
            trace_id,
            session_id,
            len(tool_log) + (1 if answer else 0),  # turns ≈ tool calls + final answer
            len(tool_log),
            len(domain_tools),
            len(tokens),
            len(answer or ""),
            agent_loop_ms,
            agent.model_name,
            agent.provider,
            agent.thinking,
            resolved_max_turns,
            build_domains,
        )
        logger.trace(
            "event=chat_answer trace_id=%s session_id=%s answer=%s",
            trace_id,
            session_id,
            json.dumps(answer, ensure_ascii=False),
        )

        # Emit thinking events BEFORE the answer (shows tool activity)
        for ndjson_line in thinking_ndjson_lines:
            yield ndjson_line

        # Emit token frames from the final streaming turn
        for token in tokens:
            yield stream_emitter.emit_token(token)

        # ── Phase 5: PERSIST ──────────────────────────────────────────────────
        if save_history:
            self._save_history(session_id, user_message,
                               answer, trace_id=trace_id)

        # What this turn already did: the memory extractor never saves it again (bench 2026-10-30: a routine
        # «pesarmi ogni lunedì» also became a memory; one memory.save turn ended with three rows).
        _turn_memory = {
            "memory_by_tool": any(e.get("ok") and e.get("tool") in ("memory.save", "memory.forget")
                                  for e in tool_log),
            "done_actions": [str(e.get("title") or e.get("tool")) for e in tool_log
                             if e.get("ok") and e.get("writes") and not e.get("unchanged")],
        }
        # Memory sync (synchronous only for explicit mutation intent)
        sync_signals, sync_attempted = self._sync_memory_if_needed(
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            force_notification_compiler=force_notification_compiler,
            **_turn_memory,
        )
        if sync_attempted:
            for signal in (sync_signals or []):
                yield stream_emitter.emit_signal(
                    event=str(signal.get("event") or "memory.updated"),
                    message=str(signal.get("message")
                                or "Aggiornamento memoria completato."),
                    data=signal.get("data") if isinstance(
                        signal.get("data"), dict) else {},
                )

        # Emit final answer
        yield stream_emitter.emit_final(
            answer,
            intent.valid_domains[0] if intent.valid_domains else "general",
            origin=origin if origin.get("level") != "utente" or origin.get("kind") == "esterno" else None,
        )
        # «Cosa ho cambiato» with Annulla per item (Cindy 13): clients draw it under the answer.
        _changes = stream_emitter.changes_from_log(tool_log)
        if _changes:
            yield stream_emitter.emit_changes(_changes, session_id=session_id)

        # Tool trace (reasoning detail; clients fold it into the reasoning block)
        if tool_log:
            yield stream_emitter.emit_tool_summary(tool_log)
            # Standard notices for real effects: one per mutating tool call.
            for entry in tool_log:
                if not entry.get("writes") or entry.get("unchanged"):
                    continue
                tname = str(entry.get("tool") or "")
                kind = "memory.saved" if tname == "memory.save" else "memory.removed" if tname == "memory.forget" else (
                    "action.done" if entry.get("ok") else "action.failed")
                # Agenda / Forge effects get their own kind so clients refresh calendar / Sviluppo.
                if entry.get("ok") and entry.get("confirm"):
                    kind = "action.needs_approval"   # a proposal (Themis): nothing is done until the user confirms
                elif entry.get("ok") and "agenda_assistente" in tname:
                    kind = "agenda.planned"
                elif entry.get("ok") and "forge_develop" in tname:
                    kind = "forge.task"
                detail = str(entry.get("title") or entry.get("tool") or "")
                if not entry.get("ok"):
                    detail = f"{detail}: {str(entry.get('result_preview') or '')[:160]}"
                yield stream_emitter.emit_notice(kind, detail=detail, data={"tool": entry.get("tool")})
            # Module-made confirmations (e.g. Themis proposal from this chat): a question card here, the
            # answer routes the module's own action (client plugins SPEC §4.6) — no Hermes round trip.
            for entry in tool_log:
                card = entry.get("confirm")
                if isinstance(card, dict) and card.get("question_id"):
                    yield self.ask_question(
                        session_id, str(card["question_id"]), str(card.get("header") or "Confermi?"),
                        str(card.get("prompt") or ""), kind="confirm", options=card.get("options") or None,
                        actions=card.get("actions") if isinstance(card.get("actions"), dict) else None)
            # The model asked the user (tool ask_user): the turn stopped on it, the answer is the next turn.
            for entry in tool_log:
                ask = entry.get("ask")
                if isinstance(ask, dict) and ask.get("question_id"):
                    yield self.ask_question(
                        session_id, str(ask["question_id"]), str(ask.get("header") or "Rispondi"),
                        str(ask.get("prompt") or ""),
                        kind=str(ask.get("kind") or "confirm"), options=ask.get("options") or None,
                        resume=True, allow_other=bool(ask.get("allow_other")))
                    break

        total_ms = int((time.perf_counter() - t0) * 1000)
        _record_turn("agent", list(intent.valid_domains or []), tool_log)
        logger.info(
            "event=chat_done_summary session_id=%s total_ms=%s mode=%s model=%s provider=%s thinking=%s tools=%s answer_len=%s tokens=%s trace_id=%s",
            session_id,
            total_ms,
            mode,
            agent.model_name,
            agent.provider,
            agent.thinking,
            len(tool_log),
            len(answer or ""),
            len(tokens),
            trace_id,
        )

        # ── Write session summary for Athena skill creation ─────────────────
        # Only for domain_query paths where tools were called (Hermes Agent
        # pattern: skills created from complex multi-step sessions).
        if tool_log and len(tool_log) >= 2:
            # Background: embedding + Archive write must not hold the stream open
            # (and must not be lost if the client disconnects after "final").
            threading.Thread(
                target=self._write_session_summary,
                kwargs={
                    "session_id": session_id,
                    "user_message": user_message,
                    "tool_log": list(tool_log),
                    "domain": intent.valid_domains[0] if intent.valid_domains else "general",
                    "success": True,
                    "turn_count": len(tool_log),
                    "total_ms": total_ms,
                },
                daemon=True,
                name="session-summary",
            ).start()

        # Background memory extraction (always async, never blocks the user)
        _mem_waiter = self._phase_background_memory(
            user_message,
            session_id,
            notify_target,
            force_notification_compiler,
            skip_memory_extract=sync_attempted,
            trace_id=trace_id,
            **_turn_memory,
        )

        yield from self._memory_notice_frames(_mem_waiter)

    def analyze_document(
        self,
        file_bytes: bytes,
        mime_type: str,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        client_instructions: str | None = None,
        filename: str | None = None,
    ):
        """Analyse an uploaded file and yield NDJSON lines."""
        yield from self._doc_analyser.analyse(
            file_bytes=file_bytes,
            mime_type=mime_type,
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            client_instructions=client_instructions,
            filename=filename,
            analyst_model_name=self._agents.generic_model_name,
        )

    def format_payload(
        self,
        command: str,
        payload: object,
        response_prompt: str | None = None,
        client_instructions: str | None = None,
        thinking: bool = False,
        max_length: int | None = None,
        locale: str = "it",
        variant_seed: str | None = None,
    ) -> str:
        """Ask the analyst to format a structured service payload as human text."""
        t0 = time.perf_counter()
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        is_alert = str(command or "").startswith("alert:")
        is_multi_alert = bool(isinstance(payload, dict)
                              and payload.get("multiple_alerts"))

        html_format_rule = prompt_config.prompt("formatter_html_rule")
        alert_context_block = prompt_config.optional_section(
            "ALERT PAYLOAD SUMMARY",
            _build_alert_payload_context(payload),
        )

        if is_alert:
            template_key = "formatter_multi_alert_template" if is_multi_alert else "formatter_alert_template"
            base_prompt, alert_variant, resolved_template_key = prompt_config.prompt_with_variant(
                template_key,
                surface="alert_formatter",
                seed=variant_seed,
                html_format_rule=html_format_rule,
                command=command,
                payload_text=payload_text,
                alert_context_block=alert_context_block,
            )
            logger.info(
                "event=prompt_variant_selected surface=alert_formatter variant=%s template_key=%s command=%s",
                alert_variant,
                resolved_template_key,
                command,
            )
        else:
            base_prompt = prompt_config.prompt(
                "formatter_generic_template",
                html_format_rule=html_format_rule,
                command=command,
                payload_text=payload_text,
            )

        static_sections = [
            base_prompt,
            conversation_style_contract(),
        ]
        dynamic_sections: list[str] = []
        if locale and str(locale).strip():
            dynamic_sections.append(
                f"LINGUA: Rispondi SEMPRE in lingua '{str(locale).strip()}'. Traduci qualsiasi testo del payload nella lingua richiesta."
            )
        if response_prompt and str(response_prompt).strip():
            dynamic_sections.append(
                f"SERVICE_RESPONSE_PROMPT:\n{str(response_prompt).strip()}"
            )
        if client_instructions and str(client_instructions).strip():
            dynamic_sections.append(
                f"CLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}"
            )
        if max_length:
            dynamic_sections.append(
                f"LUNGHEZZA: Rispondi in massimo {max_length} parole."
            )

        prompt = prompt_config.compose_with_dynamic_boundary(
            static_sections=static_sections,
            dynamic_sections=dynamic_sections,
        )
        result = self._ask_analyst(prompt)
        logger.info(
            "event=format_payload_done command=%s output_chars=%s ms=%s",
            command,
            len(result or ""),
            int((time.perf_counter() - t0) * 1000),
        )
        return result

    def compile_notification_shortcut(
        self, user_message: str, session_id: str, notify_target: str | None = None
    ) -> dict:
        """Process a notification shortcut command and return a result dict."""
        signals = self._memory_service.extract_and_save_preferences(
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            force_notification_compiler=True,
        )
        notification_events = {"subscription.added",
                               "subscription.changed", "subscription.removed"}
        matched = [s for s in (signals or []) if str(
            s.get("event", "")).lower() in notification_events]
        if matched:
            return {"ok": True, "message": "✅ Notifica elaborata con il comando rapido.", "signals": signals}
        return {"ok": False, "message": "⚠️ Nessuna notifica creata. Specifica meglio dominio, evento o filtri.", "signals": signals or []}

    def delete_chat_history(self, session_id: str):
        """Delete chat history for *session_id* via Hub/Archive."""
        return self._hub.delete(f"/chat/history/{session_id}")

    def estimate_context_stats(self, session_id: str) -> dict:
        """Return context-window usage estimates for *session_id*.

        Uses Ollama /api/tokenize when available; falls back to heuristic.
        Context window = setting oracle.provider.ollama.num_ctx (sent to Ollama on every call);
        ``runtime`` = measured per-agent stats of the last calls (prompt size, cache reuse, speed).
        """
        from core.agent_loop import TokenCounter
        counter = TokenCounter()
        _est = counter.estimate
        _window = counter.context_window

        # History
        history_data = self._hub.get_history(session_id, limit=200) or []
        history_chars = sum(len(str(m.get("content", ""))) for m in history_data if isinstance(m, dict))
        history_tokens = _est("x" * history_chars)

        # Tools from Hestia-MCP
        all_commands = self._mcp.list_tools()
        tool_count = len(all_commands)
        tool_chars_est = tool_count * 120  # compact name+desc average
        tools_tokens = _est("x" * tool_chars_est)

        # Preferences
        prefs = self._load_preferences(["general"]) or []
        pref_count = len(prefs)
        pref_chars = sum(len(str(p.get("fact", ""))) for p in prefs[:10])
        pref_tokens = _est("x" * pref_chars)

        # System overhead (preamble, style, boundary markers)
        system_overhead_chars = 3_500
        system_tokens = _est("x" * system_overhead_chars)

        total_chars = history_chars + tool_chars_est + pref_chars + system_overhead_chars
        total_tokens = history_tokens + tools_tokens + pref_tokens + system_tokens

        # Provider in use for chat (use case generic): its own window, billing kind, and the real
        # prompt size of this conversation's last call when a provider reported it.
        from agents.providers import runtime_info
        generic = self._agents.generic
        active = {"use_case": "generic", "model": generic.model_name,
                  **runtime_info(generic.provider, _window)}
        _window = active["context_window"]
        usage = llm_stats.session_usage(session_id)
        measured = int(usage.get("last_prompt_tokens") or 0)
        used_tokens = measured or total_tokens
        pct = min(100.0, 100.0 * used_tokens / _window) if _window else 0.0

        return {
            "context_window": _window,
            "history_messages": len(history_data) if isinstance(history_data, list) else 0,
            "history_chars": history_chars,
            "history_tokens_est": history_tokens,
            "tool_count": tool_count,
            "tool_chars_est": tool_chars_est,
            "tool_tokens_est": tools_tokens,
            "preference_count": pref_count,
            "preference_chars": pref_chars,
            "preference_tokens_est": pref_tokens,
            "system_overhead_chars": system_overhead_chars,
            "system_overhead_tokens_est": system_tokens,
            "total_chars_est": total_chars,
            "total_tokens_est": total_tokens,
            "context_used_pct": round(pct, 1),
            "context_remaining_est": max(0, _window - used_tokens),
            "compaction_available": (len(history_data) if isinstance(history_data, list) else 0) > 10,
            "context_used_tokens": used_tokens,
            "context_measured": bool(measured),
            "active": active,
            "session_usage": usage,
            "runtime": llm_stats.summary(),
        }

    def get_user_controls(self) -> dict:
        """Return current durable user controls."""
        return self._control_service.get_controls()

    def update_user_controls(self, patch: dict, source: str = "api") -> tuple[dict, bool]:
        """Apply a partial control update and persist the merged result."""
        return self._control_service.update_controls(patch, source=source)

    def extract_and_save_preferences(self, user_message: str, session_id: str) -> None:
        """Delegate preference extraction to MemoryService."""
        self._memory_service.extract_and_save_preferences(
            user_message, session_id)

    def submit_feedback(
        self,
        *,
        quality_label: str,
        quality_score: int | None = None,
        session_id: str | None = None,
        interaction_id: str | None = None,
        source_client: str | None = None,
        outcome_label: str | None = None,
        feedback_text: str | None = None,
        tags: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict | None:
        """Persist a feedback record in Archive and return the created row."""
        normalized_label = self._derive_quality_label(
            quality_label, quality_score)
        data_payload: dict[str, Any] = payload.copy(
        ) if isinstance(payload, dict) else {}
        if session_id and ("instruction" not in data_payload or "output" not in data_payload):
            data_payload.update(
                self._build_feedback_io_from_history(session_id))
        body = {
            "session_id": session_id,
            "interaction_id": interaction_id,
            "source_service": "oracle",
            "source_client": source_client,
            "quality_label": normalized_label,
            "quality_score": quality_score,
            "outcome_label": outcome_label,
            "feedback_text": feedback_text,
            "tags": tags or [],
            "payload": data_payload,
        }
        return self._hub.create_feedback_record(body)

    def list_feedback(
        self,
        *,
        session_id: str | None = None,
        quality_label: str | None = None,
        source_client: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return feedback records from Archive."""
        normalized = self._derive_quality_label(
            quality_label, None) if quality_label else None
        return self._hub.list_feedback_records(
            session_id=session_id,
            quality_label=normalized,
            source_client=source_client,
            source_service="oracle",
            limit=limit,
        )

    def export_feedback_jsonl(
        self,
        *,
        session_id: str | None = None,
        quality_label: str | None = None,
        source_client: str | None = None,
        limit: int = 1000,
    ) -> str:
        """Return filtered feedback rows as JSONL text."""
        normalized = self._derive_quality_label(
            quality_label, None) if quality_label else None
        return self._hub.export_feedback_jsonl(
            session_id=session_id,
            quality_label=normalized,
            source_client=source_client,
            source_service="oracle",
            limit=limit,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _derive_quality_label(
        quality_label: str | None,
        quality_score: int | None,
    ) -> str:
        """Normalize explicit labels and derive one from score when needed."""
        if quality_label:
            normalized = str(quality_label).strip().lower()
            alias_map = {
                "great": "excellent",
                "excellent": "excellent",
                "good": "good",
                "ok": "mixed",
                "mixed": "mixed",
                "bad": "poor",
                "poor": "poor",
                "reject": "rejected",
                "rejected": "rejected",
            }
            if normalized in alias_map:
                return alias_map[normalized]
        if quality_score is None:
            return "mixed"
        if quality_score >= 5:
            return "excellent"
        if quality_score == 4:
            return "good"
        if quality_score == 3:
            return "mixed"
        if quality_score == 2:
            return "poor"
        return "rejected"

    def _build_feedback_io_from_history(self, session_id: str) -> dict[str, str]:
        """Extract latest user input / assistant output pair from chat history."""
        rows = self._hub.get(
            f"/chat/history/{session_id}?limit=20",
            timeout=self._policy_timeout("foreground_chat"),
            headers=self._trace_headers(session_id),
        ) or []
        if not isinstance(rows, list):
            return {}
        last_user = None
        last_assistant = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role", "")).strip().lower()
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            if role == "assistant":
                last_assistant = content
            elif role == "user":
                last_user = content
        out: dict[str, str] = {}
        if last_user:
            out["instruction"] = last_user
            out["input"] = last_user
        if last_assistant:
            out["output"] = last_assistant
        return out

    def _phase_init(self, session_id: str, trace_id: str | None = None) -> tuple:
        """Load history and domain manifest from Hub. Returns (history_text, domains, schemas)."""
        logger.trace("event=phase_init_entry session_id=%s trace_id=%s", session_id, trace_id)
        t0 = time.perf_counter()
        history_data = self._hub.get(
            f"/chat/history/{session_id}?limit={self._context_builder.history_fetch_limit}",
            timeout=self._policy_timeout("foreground_chat"),
            headers=self._trace_headers(session_id, trace_id),
        )
        t_history_ms = int((time.perf_counter() - t0) * 1000)

        now = time.time()
        history_text = self._context_builder.compact_history(history_data, session_id)

        t_domains = time.perf_counter()
        available_domains = self._hub.hub_get(
            "/api/domains",
            timeout=self._policy_timeout("foreground_chat"),
        ) or ["general"]
        t_domains_ms = int((time.perf_counter() - t_domains) * 1000)

        schemas_from_cache = False
        from core.services import oracle_settings as _os
        if now - self._schemas_cache_ts <= _os.get_int(_os.SCHEMAS_CACHE_TTL, 0) and isinstance(self._schemas_cache_value, dict):
            schemas = dict(self._schemas_cache_value)
            schemas_from_cache = True
            t_schemas_ms = 0
        else:
            t_schemas = time.perf_counter()
            schemas = self._hub.hub_get(
                "/api/schemas",
                timeout=self._policy_timeout("foreground_chat"),
            ) or {}
            t_schemas_ms = int((time.perf_counter() - t_schemas) * 1000)
            self._schemas_cache_value = dict(
                schemas) if isinstance(schemas, dict) else {}
            self._schemas_cache_ts = now

        logger.trace(
            "event=chat_init_breakdown_ms Chat init breakdown | session=%s history_ms=%s domains_ms=%s schemas_ms=%s schemas_cache_hit=%s",
            session_id,
            t_history_ms,
            t_domains_ms,
            t_schemas_ms,
            schemas_from_cache,
        )
        logger.trace("event=phase_init_exit session_id=%s domains=%s history_len=%d schemas_keys=%s",
                     session_id, available_domains, len(history_text or ""),
                     list((schemas or {}).keys()))
        return history_text, available_domains, schemas

    def _phase_classify(
        self,
        user_message: str,
        history_text: str,
        available_domains: list,
        schemas: dict,
        current_datetime_context: str | None = None,
    ) -> SessionIntent:
        """Run router LLM to classify intent. Returns a SessionIntent."""
        logger.trace("event=phase_classify_entry msg=%s domains=%s",
                     json.dumps(user_message[:100], ensure_ascii=False), available_domains)
        (
            mode, explicit_domain, confidence, valid_domains,
            filters, filters_gt, filters_lt, sort_by, sort_order, action_intent,
        ) = self._classifier.classify(
            user_message,
            history_text,
            available_domains,
            schemas,
            current_datetime_context=current_datetime_context,
        )
        # Ensure explicit_domain is surfaced first in valid_domains
        if explicit_domain and explicit_domain not in valid_domains:
            valid_domains = [explicit_domain] + \
                [d for d in valid_domains if d != explicit_domain]
        logger.trace("event=phase_classify_exit mode=%s domain=%s conf=%.2f valid_domains=%s action_intent=%s",
                     mode, explicit_domain, confidence, valid_domains, action_intent)
        return SessionIntent(
            mode=mode,
            explicit_domain=explicit_domain,
            confidence=confidence,
            valid_domains=valid_domains,
            filters=filters or {},
            filters_gt=filters_gt or {},
            filters_lt=filters_lt or {},
            sort_by=sort_by,
            sort_order=sort_order,
            action_intent=bool(action_intent),
        )

    def _phase_context(
        self,
        user_message: str,
        intent: SessionIntent,
        client_instructions: str | None,
        notify_target: str | None,
        session_id: str,
        history_text: str = "",
        no_action_contract: str | None = None,
        athena_hints: list[dict[str, Any]] | None = None,
        planner_contract: str | None = None,
        current_datetime_context: str | None = None,
    ) -> str:
        """Load preferences, retrieve entities, build the analyst prompt. Returns prompt str."""
        all_prefs = self._load_preferences(intent.valid_domains)
        preference_facts = [str(p.get("fact", "")).strip()
                            for p in all_prefs if p.get("fact")]

        all_entities = self._retrieval_service.retrieve_entities(
            user_message=user_message,
            session_id=session_id,
            valid_domains=intent.valid_domains,
            preference_facts=preference_facts,
            active_filters=intent.filters,
            filters_gt=intent.filters_gt,
            filters_lt=intent.filters_lt,
            sort_by=intent.sort_by,
            sort_order=intent.sort_order,
        )

        formatted_context = self._context_builder.compact_entities_for_prompt(
            all_entities)

        # Inject relevant document chunks
        doc_chunks = self._doc_rag.search_relevant_chunks(
            user_message, notify_target, session_id)
        if doc_chunks:
            doc_section = DocumentRAG.format_chunks_for_prompt(doc_chunks)
            formatted_context = f"{formatted_context}\n\n{doc_section}".strip(
            ) if formatted_context else doc_section
        elif self._doc_rag.message_is_about_docs(user_message):
            brief = self._doc_rag.list_user_docs_brief(
                chat_id=notify_target, session_id=session_id)
            if brief:
                formatted_context = f"{formatted_context}\n\n{brief}".strip(
                ) if formatted_context else brief

        athena_hint_section = self._format_athena_hints_for_prompt(
            athena_hints or [])
        if athena_hint_section:
            athena_context_block = f"ATHENA_ADVISORY_HINTS:\n{athena_hint_section}"
            formatted_context = (
                f"{formatted_context}\n\n{athena_context_block}".strip()
                if formatted_context else athena_context_block
            )

        prompt = self._context_builder.build_analysis_prompt(
            preference_facts=preference_facts,
            valid_domains=intent.valid_domains,
            active_filters=intent.filters,
            filters_gt=intent.filters_gt,
            filters_lt=intent.filters_lt,
            sort_by=intent.sort_by,
            sort_order=intent.sort_order,
            formatted_context=formatted_context,
            history_text=history_text,
            user_message=user_message,
            current_datetime_context=current_datetime_context,
        )
        return prompt_config.compose_with_dynamic_boundary(
            static_sections=[
                conversation_style_contract(),
                str(no_action_contract or "").strip(),
                str(planner_contract or "").strip(),
            ],
            dynamic_sections=[
                prompt,
                prompt_config.optional_section(
                    "CLIENT_INSTRUCTIONS", client_instructions
                ).strip(),
            ],
        )

    def _phase_background_memory(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None,
        force_notification_compiler: bool,
        skip_memory_extract: bool = False,
        trace_id: str | None = None,
        memory_by_tool: bool = False,
        done_actions: list[str] | None = None,
    ) -> dict:
        """Memory extraction + compaction check in a daemon thread.

        Returns a waiter ``{"done": Event, "signals": [...]}``: the chat generator
        waits a few seconds after the final answer to stream memory notices
        (the user always sees what was remembered), then lets the rest run on.
        """
        waiter: dict = {"done": threading.Event(), "signals": []}
        logger.info(
            "event=background_memory_start session_id=%s trace_id=%s skip_memory_extract=%s",
            session_id,
            trace_id,
            bool(skip_memory_extract),
        )

        def _run():
            t0 = time.perf_counter()
            mem_ms = 0
            ctrl_ms = 0
            compaction_ms = 0
            compacted = False

            # ── Quiet mood capture («oggi sono stanco» → the mood module, no confirmation) ──
            mood_signals: list[dict] = []
            try:
                mood_signals = self._mood_capture.run(user_message)
            except Exception as exc:
                logger.warning("[🔄] event=background_mood_capture_failed error=%s fallback=skip", exc)

            # ── Memory extraction ──────────────────────────────────────────────
            if not skip_memory_extract:
                waiter["signals"] = mood_signals
                try:
                    t_mem = time.perf_counter()
                    waiter["signals"] = mood_signals + (self._memory_service.extract_and_save_preferences(
                        user_message, session_id,
                        notify_target=notify_target,
                        force_notification_compiler=force_notification_compiler,
                        memory_by_tool=memory_by_tool,
                        done_actions=done_actions,
                    ) or [])
                    mem_ms = int((time.perf_counter() - t_mem) * 1000)
                    logger.info(
                        "event=background_phase_timing_ms Background phase timing | session=%s phase=memory_extract ms=%s",
                        session_id, mem_ms,
                    )
                except Exception as exc:
                    logger.warning(
                        "event=background_memory_sync_failed Background memory sync failed: %s", exc)
                finally:
                    waiter["done"].set()
            else:
                waiter["signals"] = mood_signals
                waiter["done"].set()
                logger.trace(
                    "event=background_memory_extract_skipped Background memory extraction skipped because sync persistence already ran | session=%s",
                    session_id,
                )

            # ── User controllability extraction (P1-9) ────────────────────────
            try:
                t_ctrl = time.perf_counter()
                self._control_service.extract_and_save_controls(user_message)
                ctrl_ms = int((time.perf_counter() - t_ctrl) * 1000)
                logger.info(
                    "event=background_phase_timing_ms Background phase timing | session=%s phase=controls_extract ms=%s",
                    session_id, ctrl_ms,
                )
            except Exception as exc:
                logger.warning(
                    "event=background_control_extraction_failed Background control extraction failed: %s", exc)

            # ── Context compaction (inactivity trigger — runs only when needed) ─
            compaction_task = self._task_store.create_task(
                task_type="oracle.compaction",
                session_id=session_id,
                trace_id=trace_id,
                metadata={
                    "source": "background_memory",
                    "policy_timeout_seconds": self._policy_timeout("background_compaction"),
                },
            )
            compaction_task_id = str(compaction_task.get("task_id") or "")
            self._task_store.mark_running(
                compaction_task_id,
                progress=0.1,
                metadata={"phase": "history_fetch"},
            )
            try:
                t_compaction = time.perf_counter()
                history_data = self._hub.get_history(
                    session_id,
                    timeout=self._policy_timeout("background_compaction"),
                )
                history_size = len(history_data) if isinstance(
                    history_data, list) else 0
                self._task_store.mark_running(
                    compaction_task_id,
                    progress=0.4,
                    metadata={"history_messages": history_size},
                )
                should_compact = self._context_builder.needs_compaction(
                    history_data)
                compacted = bool(should_compact)
                if should_compact:
                    self._task_store.mark_running(
                        compaction_task_id,
                        progress=0.75,
                        metadata={"phase": "compaction"},
                    )
                    self._context_builder.run_background_compaction(
                        session_id=session_id,
                        history_data=history_data,
                        scribe_agent=self._agents.generic,
                        hub_client=self._hub,
                    )
                self._task_store.mark_succeeded(
                    compaction_task_id,
                    progress=1.0,
                    result={
                        "compacted": bool(should_compact),
                        "history_messages": history_size,
                    },
                )
                compaction_ms = int((time.perf_counter() - t_compaction) * 1000)
                logger.info(
                    "event=background_phase_timing_ms Background phase timing | session=%s phase=compaction_check ms=%s task_id=%s compacted=%s",
                    session_id, compaction_ms, compaction_task_id, bool(should_compact),
                )
            except Exception as exc:
                self._task_store.mark_failed(
                    compaction_task_id,
                    error={"message": str(exc), "phase": "compaction_check"},
                )
                logger.warning(
                    "event=background_compaction_check_failed Background compaction check failed: %s", exc)

            total_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "event=background_memory_done session_id=%s total_ms=%s extract_ms=%s controls_ms=%s compaction_ms=%s compacted=%s",
                session_id, total_ms, mem_ms, ctrl_ms, compaction_ms, compacted,
            )

        threading.Thread(target=_run, daemon=True).start()
        return waiter

    def _memory_notice_frames(self, waiter: dict | None):
        """After the final answer: stream what background memory saved (notices), or nothing."""
        if not waiter:
            return
        from core.services import oracle_settings as _os
        wait_s = _os.get_float(_os.NOTICE_WAIT, 0.0)
        if not waiter["done"].wait(max(0.0, wait_s)):
            logger.info("event=memory_notice_wait_timeout wait_s=%s", wait_s)
            return
        for signal in waiter.get("signals") or []:
            yield stream_emitter.emit_signal(
                event=str(signal.get("event") or "memory.updated"),
                message=str(signal.get("message") or "Memoria aggiornata."),
                data=signal.get("data") if isinstance(signal.get("data"), dict) else {},
            )

    def _sync_memory_if_needed(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None,
        force_notification_compiler: bool,
        memory_by_tool: bool = False,
        done_actions: list[str] | None = None,
    ) -> tuple[list[dict], bool]:
        """Synchronously persist memory/subscription updates on explicit mutation turns.

        Returns ``(signals, attempted)`` where ``attempted`` indicates whether
        synchronous persistence was executed for this turn.
        """
        should_sync = bool(force_notification_compiler) or has_notification_intent(
            user_message) or has_deprecate_intent(user_message) or has_preference_intent(user_message)
        if not should_sync:
            return [], False

        t0 = time.perf_counter()
        try:
            signals = self._memory_service.extract_and_save_preferences(
                user_message=user_message,
                session_id=session_id,
                notify_target=notify_target,
                force_notification_compiler=force_notification_compiler,
                memory_by_tool=memory_by_tool,
                done_actions=done_actions,
            ) or []
            logger.info(
                "event=memory_sync_persist_result session_id=%s attempted=true signals=%s ms=%s",
                session_id,
                len(signals),
                int((time.perf_counter() - t0) * 1000),
            )
            return signals, True
        except Exception as exc:
            logger.warning(
                "event=memory_sync_persist_failed_non Sync memory persistence failed (non-fatal): %s",
                exc,
            )
            return [], True

    def _build_domain_tools(
        self,
        intent: "SessionIntent",
        session_id: str,
        notify_target: str | None,
        trace_id: str | None = None,
        fallback_domains: list[str] | None = None,
    ) -> list[ToolDefinition]:
        """Build ToolDefinitions for the agentic loop from registered module tools.

        Domain filtering (rulebook 1.2 — organ model):
        - Only domains with a ``layer:domain`` owner get a ``{domain}.search`` tool.
        - Hub command tools are filtered to domain-owning services only.
        - Domains with no canonical owner log a warning and are skipped —
          the LLM still has ``memory.*`` + ``documents.search`` tools.
        """
        tools: list[ToolDefinition] = []
        rs = self._retrieval_service

        # ── Resolve domain-owning services ──────────────────────────────────
        if self._module_registry._needs_refresh():
            self._module_registry.refresh()

        domains = fallback_domains if fallback_domains else intent.valid_domains

        # _relevant_services = all services with layer:domain that own at
        # least one of the intent's domains.  Used to filter command tools.
        _relevant_services: set[str] = set()
        _owned_domains: list[str] = []
        _unowned_domains: list[str] = []

        for domain in domains:
            owners = self._module_registry.get_domain_owners(domain)
            if owners:
                _relevant_services.update(owners)
                _owned_domains.append(domain)
            else:
                _unowned_domains.append(domain)

        if _unowned_domains:
            logger.warning(
                "event=domain_tool_no_owner session_id=%s unowned_domains=%s "
                "all_domains=%s — no layer:domain service owns these domains; "
                "only memory.* + documents.search tools will be available",
                session_id, _unowned_domains, domains,
            )

        # ── Build {domain}.search tools for OWNED domains only ──────────────
        for domain in _owned_domains:
            _domain = domain

            def _domain_search_handler(
                query: str = "",
                filters: dict | None = None,
                filters_gt: dict | None = None,
                filters_lt: dict | None = None,
                sort_by: str | None = None,
                sort_order: str | None = None,
                _d: str = _domain,
            ) -> tuple[bool, list]:
                try:
                    entities = rs.retrieve_entities(
                        user_message=query,
                        session_id=session_id,
                        valid_domains=[_d],
                        preference_facts=[],
                        active_filters=filters or {},
                        filters_gt=filters_gt or {},
                        filters_lt=filters_lt or {},
                        sort_by=sort_by,
                        sort_order=sort_order,
                    )
                    return (True, entities)
                except Exception as exc:
                    return (False, f"Search failed: {exc}")

            tools.append(ToolDefinition(
                name=f"{domain}.search",
                description=f"Search {domain} domain entities. Use for queries related to {domain}.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query text"},
                        "filters": {"type": "object", "description": "Exact-match field filters"},
                        "filters_gt": {"type": "object", "description": "Greater-than numeric filters"},
                        "filters_lt": {"type": "object", "description": "Less-than numeric filters"},
                        "sort_by": {"type": "string", "description": "Field to sort by"},
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    "required": [],
                },
                handler=_domain_search_handler,
            ))

        # Document chunk search tool
        doc_rag = self._doc_rag

        def _doc_search_handler(query: str = "") -> tuple[bool, str]:
            try:
                chunks = doc_rag.search_relevant_chunks(
                    query, notify_target, session_id)
                if not chunks:
                    return (True, "No relevant document chunks found.")
                return (True, DocumentRAG.format_chunks_for_prompt(chunks))
            except Exception as exc:
                return (False, f"Document search failed: {exc}")

        tools.append(ToolDefinition(
            name="documents.search",
            description="Search through uploaded documents and files for relevant content.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
            handler=_doc_search_handler,
        ))

        # ── Hub Action Commands — filtered to domain-owning services ────────
        all_commands = [as_command(t) for t in self._mcp.list_tools()]
        _filtered_cmds = 0
        for cmd in all_commands:
            cmd_name = cmd.get("command")
            if not cmd_name:
                continue

            # Domain-gate: only include commands from domain-owning services.
            # memory.* / documents.* tools are added separately below.
            cmd_service = str(cmd.get("service", "") or "").strip()
            if _relevant_services and cmd_service not in _relevant_services and cmd_name not in _ALWAYS_TOOLS:
                _filtered_cmds += 1
                continue

            # Schema: Hestia-MCP already gives it (declared arguments, or the variables of the tool's templates).
            # The tool's own JSON Schema when there is one: enums, array items and nested fields tell the model
            # the valid values (the flattened arguments_schema lost them; Gemini refused arrays without items).
            args_schema = cmd.get("arguments_schema") or {}
            schema = cmd.get("input_schema") if isinstance(cmd.get("input_schema"), dict) \
                and isinstance(cmd["input_schema"].get("properties"), dict) else {
                "type": "object",
                "properties": {k: {"description": str(v.get("description", k)), "type": str(v.get("type", "string"))}
                               for k, v in args_schema.items()},
                "required": [k for k, v in args_schema.items() if dict(v).get("required", False)],
            }

            def make_handler(command_def):
                def _hub_command_handler(**kwargs):
                    # Hestia-MCP fills templates/path and routes through Hub (hestia_common.tool_call).
                    args = {k: v for k, v in kwargs.items() if v is not None}
                    return _error_payload_fails(self._mcp.call(
                        str(command_def.get("command")), args,
                        session_id=session_id, notify_target=str(notify_target or ""),
                        trace_id=str(trace_id or ""), service=str(command_def.get("service", "")),
                        origin_client=self._session_clients.get(session_id) or "",
                        origin=self._origin_header(session_id),
                        timeout=self._policy_timeout("action_service_route")))

                return _hub_command_handler

            if any(t.name == cmd_name for t in tools):
                continue

            tools.append(ToolDefinition(
                name=cmd_name,
                description=cmd.get(
                    "description", f"Execute {cmd_name} command"),
                parameters=schema,
                handler=make_handler(cmd),
                writes=bool(cmd.get("writes")),
                title=str(cmd.get("title") or cmd_name),
                method=str(cmd.get("method") or "GET").upper(),
            ))

        if _filtered_cmds:
            logger.debug(
                "event=domain_tool_commands_filtered session_id=%s "
                "filtered_out=%s kept=%s relevant_services=%s",
                session_id, _filtered_cmds,
                sum(1 for _ in all_commands) - _filtered_cmds,
                sorted(_relevant_services),
            )

        # ── Memory tools (first-class agent loop tools) ──────────────────────
        _mem_svc = self._memory_service

        def _memory_save_handler(fact: str = "", domain: str = "general") -> tuple[bool, str]:
            ok, msg = _mem_svc.save_memory(fact=fact, domain=domain)
            return (ok, msg)

        tools.append(ToolDefinition(
            name="memory.save",
            description="Save a durable fact or preference about the user for future reference. "
                        "Use when the user expresses a preference, constraint, or personal detail "
                        "that should be remembered across conversations.",
            parameters={
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The durable fact to remember"},
                    "domain": {"type": "string", "description": "Domain category (default 'general')"},
                },
                "required": ["fact"],
            },
            handler=_memory_save_handler,
            writes=True,
            title="💾 Memoria",
        ))

        def _memory_forget_handler(id: int | str = 0) -> tuple[bool, dict | str]:
            try:
                memory_id = int(id)
            except (TypeError, ValueError):
                return (False, "id must be the number from memory.search")
            if not _mem_svc.forget(memory_id):
                return (False, f"memory {memory_id} not found")
            return (True, {"forgotten": memory_id})

        tools.append(ToolDefinition(
            name="memory.forget",
            description="Forget one saved memory (the user asks to forget/remove it). First memory.search, "
                        "then call this once per matching id.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "The memory id from memory.search"}},
                "required": ["id"],
            },
            handler=_memory_forget_handler,
            writes=True,
            title="Memoria dimenticata",
        ))

        def _memory_search_handler(query: str = "") -> tuple[bool, list]:
            ok, results = _mem_svc.search_memories(query=query)
            return (ok, results)

        tools.append(ToolDefinition(
            name="memory.search",
            description="Search saved memories and preferences about the user. "
                        "Use before answering to recall user preferences, or when the user "
                        "asks what you remember about them.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search for in memories"},
                },
                "required": [],
            },
            handler=_memory_search_handler,
        ))

        # ── Conversations (Cindy 26): Oracle's own tools, so not in the module commands; default = this chat ──
        def _chat_tag_handler(**kw) -> tuple[bool, dict]:
            try:
                out = chat_sessions.tool_tag(_mem_svc._route_archive, **{"session_id": session_id, **{
                    k: v for k, v in kw.items() if v not in (None, "")}})
            except chat_sessions.ChatSessionsError as exc:
                return (False, {"error": exc.detail})
            return (True, out)

        def _chat_list_handler(**kw) -> tuple[bool, dict]:
            try:
                return (True, chat_sessions.tool_list(_mem_svc._route_archive, **{
                    k: v for k, v in kw.items() if v not in (None, "")}))
            except chat_sessions.ChatSessionsError as exc:
                return (False, {"error": exc.detail})

        tools.append(ToolDefinition(
            name="chat_tag", description=chat_sessions.TAG_DESCRIPTION, parameters=chat_sessions.TAG_PARAMETERS,
            handler=_chat_tag_handler, writes=True, title="Etichetta la conversazione", method="POST"))
        tools.append(ToolDefinition(
            name="chat_list", description=chat_sessions.LIST_DESCRIPTION, parameters=chat_sessions.LIST_PARAMETERS,
            handler=_chat_list_handler, title="Le tue conversazioni", method="GET"))

        # ── Asking the user (always available, v3 A): the turn stops on it ─────
        tools.append(ToolDefinition(
            name="ask_user",
            description=user_questions.TOOL_DESCRIPTION,
            parameters=user_questions.TOOL_PARAMETERS,
            handler=user_questions.build_question,
            title="❓ Domanda",
        ))

        # ── Oracle self-introspection tools (always available) ─────────────
        # These let the LLM answer "come stai?", "stato servizi?", system
        # health questions with real data instead of platitudes.

        def _oracle_session_info_handler() -> tuple[bool, dict]:
            info = self.get_session_info()
            return (True, info)

        tools.append(ToolDefinition(
            name="oracle.session_info",
            description="Get full Hestia system state: Oracle's models, uptime, "
                        "AND health status of all registered services from Hub. "
                        "Use this for ANY question about your state, system health, "
                        "service status, or 'come stai'. One call gives everything.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=_oracle_session_info_handler,
        ))

        def _oracle_logs_query_handler(
            level: str = "WARNING",
            contains: str = "",
            limit: int = 10,
        ) -> tuple[bool, list[str]]:
            lines = self.query_logs(level=level or None,
                                    contains=contains or None,
                                    limit=int(limit or 10))
            return (True, lines)

        tools.append(ToolDefinition(
            name="oracle.logs_query",
            description="Query Oracle's recent in-memory log buffer. "
                        "Use to check for errors, warnings, or recent events "
                        "when the user asks about system health or operational issues. "
                        "Filterable by log level and text content.",
            parameters={
                "type": "object",
                "properties": {
                    "level": {"type": "string", "description": "Log level filter (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO"},
                    "contains": {"type": "string", "description": "Filter logs containing this text"},
                    "limit": {"type": "integer", "description": "Max lines to return (default 10, max 500)"},
                },
                "required": [],
            },
            handler=_oracle_logs_query_handler,
        ))

        return tools

    # ── Turn tools, origin gate, goal rounds (dossier 2026-10-24-tutto-brainstorm-cindy) ─────────
    def _origin_header(self, session_id: str) -> str:
        """``X-Hestia-Origin`` for the module calls of this turn; empty for the owner typing (X-Hestia-Client says it)."""
        o = self._session_origins.get(session_id) or {}
        if not o.get("kind") or o.get("kind") == "utente":
            return ""
        return f"{o['kind']}:{o.get('ref') or ''}".rstrip(":")

    def _turn_tools(self, session_id: str, origin: dict) -> list[ToolDefinition]:
        """Tools every turn has besides the modules': module manuals (Cindy 30) and the conversation goal (23)."""
        registry = self._module_registry

        def _manual(module: str = "") -> tuple[bool, Any]:
            text = registry.manual(module)
            if not text:
                return False, f"Nessun manuale per «{module}». Moduli: {', '.join(sorted(registry.guides()))}"
            return True, text

        tools = [ToolDefinition(
            name="module_manual", title="Manuale del modulo",
            description="Manuale breve di un modulo (cosa sa fare, come usarne gli strumenti). Usalo quando non sai "
                        "quale strumento di quel modulo serve.",
            parameters={"type": "object", "properties": {"module": {"type": "string"}}, "required": ["module"]},
            handler=_manual)]
        if origin.get("level") != "utente":
            return tools
        hub = self._hub

        def _goal_set(text: str = "") -> tuple[bool, Any]:
            if not str(text or "").strip():
                return False, "text is required"
            goal = conversation_goal.set_goal(hub, session_id, str(text))
            return True, {"goal": goal["text"], "note": "Obiettivo fissato: ci lavoro dopo ogni risposta."}

        def _goal_done(summary: str = "") -> tuple[bool, Any]:
            goal = conversation_goal.end(hub, session_id, "raggiunto", summary)
            return (True, {"done": True, "goal": goal["text"]}) if goal else (False, "nessun obiettivo attivo")

        def _goal_stop() -> tuple[bool, Any]:
            goal = conversation_goal.end(hub, session_id, "fermato")
            return (True, {"stopped": True}) if goal else (False, "nessun obiettivo attivo")

        handlers = {"goal_set": _goal_set, "goal_done": _goal_done, "goal_stop": _goal_stop}
        for spec in conversation_goal.tool_specs():
            tools.append(ToolDefinition(name=spec["name"], description=spec["description"],
                                        parameters=spec["parameters"], handler=handlers[spec["name"]],
                                        title=spec["title"]))
        return tools

    @staticmethod
    def _apply_origin_gate(tools: list[ToolDefinition], origin: dict) -> None:
        """Turn authority (Cindy 6): a routine never deletes, an autonomous turn never writes (it proposes)."""
        if origin.get("level") == "utente":
            return
        blocked = 0
        for t in tools:
            if not t.writes and t.name not in ("memory.save",):
                continue
            reason = origin_mod.blocks_write(origin, method=t.method or "POST", name=t.name)
            if reason:
                t.handler = (lambda _r: (lambda **_kw: (False, _r)))(reason)
                blocked += 1
        if blocked:
            logger.info("event=origin_gate_applied level=%s kind=%s blocked_tools=%d", origin.get("level"),
                        origin.get("kind"), blocked)

    def _wants_ui_blocks(self, client: str) -> bool:
        """Components in answers (Cindy 9): WebUI only, and only when a capable (non-local) model answers."""
        if str(client or "").lower() not in ("webui", "ui", "web"):
            return False
        from core.services import llm_providers
        try:
            ptype = llm_providers.type_of(self._agents.generic.provider)
        except Exception:
            return False
        return bool(ptype) and ptype not in ("ollama", "llamacpp")

    def _goal_rounds(self, *, session_id: str, history_text: str, preference_facts: list[str],
                     tools: list[ToolDefinition], ask_tools, think_level, instructions: str | None
                     ) -> tuple[str, list[dict], list[str]]:
        """Work on the conversation goal for a few rounds; returns (report, tool log, thinking frames)."""
        goal = conversation_goal.active(self._hub, session_id)
        if not goal:
            return "", [], []
        total, per_answer = conversation_goal.budget()
        frames: list[str] = []
        log: list[dict] = []
        last = ""
        for _ in range(per_answer):
            goal = conversation_goal.active(self._hub, session_id)
            if not goal:
                break
            if int(goal.get("rounds") or 0) >= total:
                conversation_goal.end(self._hub, session_id, "budget")
                last = (f"Obiettivo «{goal['text']}»: ho finito i giri a disposizione ({total}). "
                        "Dimmi se continuo.")
                break
            try:
                ans, _toks, round_log = run_agent_loop(
                    user_message=conversation_goal.continuation_message(goal), history_text=history_text,
                    preference_facts=preference_facts, tools=tools,
                    ask_fn=lambda p: self._ask_analyst(p, thinking=think_level), ask_tools_fn=ask_tools,
                    stream_fn=None, client_instructions=instructions,
                    conversation_style=conversation_style_contract(), on_thinking=frames.append,
                    guard_checker=loop_guard.llm_checker)
            except Exception as exc:
                logger.warning("[🔄] event=goal_round_failed session_id=%s error=%s", session_id, exc)
                break
            log.extend(round_log)
            conversation_goal.note_round(self._hub, goal, ans)
            last = ans
            frames.append(stream_emitter.emit_notice("goal.progress", detail=str(ans or "")[:300],
                                                     data={"goal": goal["text"], "round": goal["rounds"]}))
            if any(e.get("ask") for e in round_log) or not conversation_goal.active(self._hub, session_id):
                break
        if not last:
            return "", log, frames
        state = conversation_goal.active(self._hub, session_id)
        head = "Obiettivo" + (f" (giro {state['rounds']}/{total})" if state else " — fatto")
        return f"**{head}:** {last}", log, frames

    # ── Context compaction (REST + MCP) ──────────────────────────────────────

    def compact_context(self, session_id: str) -> dict:
        """Force-compact *session_id* conversation history.

        Sends older messages through the memory compactor LLM (generic model),
        preserves recent messages and protected content, writes back to Archive.
        """
        from core.agent_loop import TokenCounter
        counter = TokenCounter()

        # Load full history
        history_raw: list[dict] = []
        try:
            history_raw = self._hub.get(
                f"/chat/history/{session_id}?limit=200",
                timeout=self._policy_timeout("foreground_chat"),
                headers=self._trace_headers(session_id, None),
            ) or []
        except Exception as exc:
            logger.warning("event=compact_history_load_failed session_id=%s error=%s",
                          session_id, exc)
            return {"error": str(exc), "before_tokens": 0, "after_tokens": 0}

        before_history = self._context_builder.compact_history(history_raw)
        before_tokens = counter.estimate(before_history)
        before_count = len(history_raw)

        if before_count <= 6:
            return {
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "messages_before": before_count,
                "messages_after": before_count,
                "summary_chars": 0,
                "note": "History too short to compact (≤6 messages).",
            }

        # Separate: keep last 6 messages, compact the rest
        from core.services import oracle_settings as _os
        keep_count = _os.get_int(_os.COMPACT_KEEP, 1)
        to_compact = history_raw[:-keep_count] if len(history_raw) > keep_count else []
        to_keep = history_raw[-keep_count:] if len(history_raw) > keep_count else history_raw

        if not to_compact:
            return {
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "messages_before": before_count,
                "messages_after": before_count,
                "summary_chars": 0,
                "note": "No messages to compact after keeping recent N.",
            }

        # Build compactable text
        compactable_text = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'Hestia'}: {str(m.get('content', ''))}"
            for m in to_compact
        )

        # Compaction prompt
        compact_prompt = prompt_config.prompt(
            "memory_compactor",
            history_block=compactable_text,
        )

        try:
            summary = self._agents.generic.ask(compact_prompt)
            summary = (summary or "").strip()
        except Exception as exc:
            logger.warning("event=compact_llm_failed session_id=%s error=%s", session_id, exc)
            summary = f"[Compaction skipped — LLM unavailable: {exc}]"

        # Write compacted history: summary block + kept messages
        compacted_messages = [
            {"role": "system",
             "content": f"[CONVERSATION SUMMARY — older messages compacted]\n{summary}"}
        ] + to_keep

        try:
            self._hub.put(
                f"/chat/history/{session_id}",
                json={"messages": compacted_messages},
                timeout=self._policy_timeout("foreground_chat"),
                headers=self._trace_headers(session_id, None),
            )
        except Exception as exc:
            logger.warning("event=compact_write_failed session_id=%s error=%s", session_id, exc)
            return {"error": f"Write failed: {exc}", "before_tokens": before_tokens,
                    "after_tokens": before_tokens}

        after_history = self._context_builder.compact_history(compacted_messages)
        after_tokens = counter.estimate(after_history)

        logger.info(
            "event=context_compacted session_id=%s before_tokens=%d after_tokens=%d "
            "messages_before=%d messages_after=%d summary_chars=%d",
            session_id, before_tokens, after_tokens,
            before_count, len(compacted_messages), len(summary),
        )

        return {
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "messages_before": before_count,
            "messages_after": len(compacted_messages),
            "summary_chars": len(summary),
        }

    # ── Oracle self-tools (MCP + REST) ──────────────────────────────────────

    def get_session_info(self) -> dict:
        """Return full Hestia state: Oracle + all registered services."""
        services_health: list[dict] = []
        try:
            status = self._hub.hub_get("/status", timeout=5)
            raw = status.get("services", []) if isinstance(status, dict) else []
            for svc in (raw or []):
                if not isinstance(svc, dict):
                    continue
                services_health.append({
                    "name": svc.get("name", "?"),
                    "status": svc.get("status", "unknown"),
                })
        except Exception:
            services_health = [{"name": "hub", "status": "unreachable"}]

        return {
            "oracle": {
                "models": {
                    "generic": self._agents.generic_model_name,
                    "reasoning": self._agents.reasoning.model_name,
                    "code": self._agents.code.model_name,
                },
                "hub_url": self._hub_url,
                "uptime_seconds": int(time.time() - _STARTUP_TS),
            },
            "services": services_health,
            "total_services": len(services_health),
        }

    def query_logs(self, level: str | None = None, contains: str | None = None, limit: int = 50) -> list[str]:
        """Query Oracle's in-memory log buffer for the ``oracle.logs_query`` MCP tool.

        Returns matching log lines, newest first, capped at *limit* (max 500).
        """
        from main import log_buffer
        limit = max(1, min(int(limit), 500))
        lines: list[str] = []
        try:
            records = log_buffer.get_all() if hasattr(log_buffer, 'get_all') else []
        except Exception:
            return []
        for record in reversed(records):
            if len(lines) >= limit:
                break
            msg = str(record) if not hasattr(record, 'getMessage') else record.getMessage()
            if level:
                lvl = getattr(record, 'levelname', '') if hasattr(record, 'levelname') else ''
                if lvl.upper() != level.upper():
                    continue
            if contains and contains.lower() not in msg.lower():
                continue
            lines.append(msg)
        return lines

    # ── Skill system: session summaries + discovery ─────────────────────────

    def _write_session_summary(
        self,
        session_id: str,
        user_message: str,
        tool_log: list[dict],
        domain: str,
        success: bool,
        turn_count: int,
        total_ms: int,
    ) -> None:
        """Write a compact session summary to Archive for Athena skill mining.

        Hermes Agent pattern: skills are created from multi-step sessions
        (≥2 tool calls).  Athena reads these summaries during its daily
        cycle, clusters by embedding similarity, and creates/updates skills.
        """
        try:
            # Embed the user message for clustering
            embedding = self._embed(user_message)

            payload = {
                "entity_type": "session_summary",
                "domain": domain,
                "user_message": user_message[:500],
                "embedding": embedding,
                "tool_sequence": [
                    {"tool": t.get("tool", ""), "ok": t.get("ok", False)}
                    for t in tool_log
                ],
                "success": success,
                "turn_count": turn_count,
                "total_ms": total_ms,
            }
            # Archive contract: POST /api/entities {entity_id, domain, payload}.
            # (Was POST /entity/{session_id}: no such route, wrong body, and one
            # id per session would overwrite earlier summaries.)
            now = datetime.now(datetime_timezone.utc)
            payload["created_at"] = now.isoformat()
            payload["session_id"] = session_id
            self._hub.post(
                "entities",
                body={
                    "entity_id": f"session_summary:{session_id}:{int(now.timestamp() * 1000)}",
                    "domain": "session_summary",
                    "status": "active",
                    "payload": payload,
                },
                timeout=self._policy_timeout("foreground_chat"),
                headers=self._trace_headers(session_id, None),
            )
            logger.debug(
                "event=session_summary_written session_id=%s domain=%s "
                "tools=%d success=%s",
                session_id, domain, turn_count, success,
            )
        except Exception as exc:
            logger.warning(
                "event=session_summary_write_failed session_id=%s error=%s",
                session_id, exc,
            )

    def _discover_skills(
        self, user_message: str, domain: str, session_id: str,
    ) -> list[dict]:
        """Search Archive for skills matching *user_message* + *domain*.

        Uses Archive's ``POST /api/memory/search/similar`` (pgvector cosine
        similarity).  Returns top 3 matches with similarity ≥ 0.85.
        Called ONCE per session, not per turn.
        """
        try:
            embedding = self._embed(user_message)
            results = self._hub.route_to_service(
                service="archive",
                path="/api/memory/search/similar",
                method="POST",
                body={
                    "embedding": embedding,
                    "memory_class": "skill",
                    "domain": domain,
                    "limit": 5,
                },
                timeout=self._policy_timeout("foreground_chat"),
                headers=self._trace_headers(session_id, None),
            )
            # route_to_service returns (ok, result)
            if isinstance(results, tuple):
                _, results = results
            if not isinstance(results, list):
                return []

            # Archive already ranks by similarity; filter by threshold
            matched: list[dict] = [
                r for r in results
                if isinstance(r, dict) and r.get("_similarity", 0) >= 0.85
            ]
            logger.debug(
                "event=skills_discovered session_id=%s domain=%s "
                "candidates=%d matched=%d",
                session_id, domain, len(results), len(matched),
            )
            return matched[:3]
        except Exception as exc:
            logger.warning(
                "event=skills_discovery_failed session_id=%s error=%s",
                session_id, exc,
            )
            return []

    def _cleanup_expired_action_approvals(self) -> None:
        now = time.time()
        expired_tokens: list[str] = []
        with self._approval_lock:
            for token, row in list(self._pending_action_approvals.items()):
                try:
                    expires_at = float(row.get("expires_at") or 0)
                except Exception:
                    expires_at = 0
                if expires_at and expires_at <= now:
                    expired_tokens.append(token)
            for token in expired_tokens:
                self._pending_action_approvals.pop(token, None)

    def _requires_high_impact_approval(
        self,
        matched: dict,
        action_name: str,
        param_sets: list[dict],
    ) -> bool:
        from core.services import oracle_settings as _os
        if not _os.get_bool(_os.APPROVAL_ENABLED):
            return False

        method = str(matched.get("method", "POST")).upper().strip()
        if method in set(_os.get_list(_os.APPROVAL_METHODS, upper=True)):
            return True

        commands = set(_os.get_list(_os.APPROVAL_COMMANDS, lower=True))
        if commands and action_name.strip().lower() in commands:
            return True

        return len(param_sets) >= _os.get_int(_os.APPROVAL_BULK_MIN, 1)

    def _queue_high_impact_approval(
        self,
        *,
        matched: dict,
        action_name: str,
        title: str,
        param_sets: list[dict],
        session_id: str,
        notify_target: str | None,
        trace_id: str | None,
        client_instructions: str | None,
    ) -> str:
        self._cleanup_expired_action_approvals()
        token = uuid.uuid4().hex[:16]
        with self._approval_lock:
            self._pending_action_approvals[token] = {
                "matched": dict(matched or {}),
                "action_name": str(action_name or ""),
                "title": str(title or action_name or ""),
                "param_sets": [dict(p) for p in (param_sets or []) if isinstance(p, dict)],
                "session_id": str(session_id or ""),
                "notify_target": str(notify_target or "").strip() or None,
                "trace_id": str(trace_id or "").strip() or None,
                "client_instructions": str(client_instructions or "").strip() or None,
                "created_at": time.time(),
                "expires_at": time.time() + _approval_ttl(),
            }
        return token

    def _execute_selected_action(
        self,
        *,
        matched: dict,
        action_name: str,
        param_sets: list[dict],
        session_id: str,
        notify_target: str | None,
        trace_id: str | None,
        client_instructions: str | None,
    ) -> dict[str, Any]:
        if not param_sets:
            return {
                "executed": False,
                "command": action_name,
                "title": matched.get("title") or action_name,
                "service": matched.get("service") or "",
                "path": str(matched.get("path") or ""),
                "text": "⚠️ Parametri azione non validi o incompleti.",
            }

        route_results: list[dict] = []
        all_ok = True

        for params in param_sets:
            path = str(matched.get("path") or "")
            logger.info(
                "event=tool_call_cmd_service_path Tool call | cmd=%s service=%s path=%s",
                action_name,
                matched.get("service", ""),
                path,
            )
            ok, result = self._mcp.call(
                action_name, params, session_id=session_id, notify_target=str(notify_target or ""),
                trace_id=str(trace_id or ""), service=str(matched.get("service", "")),
                origin_client=self._session_clients.get(session_id) or "",
                origin=self._origin_header(session_id),
                timeout=self._policy_timeout("action_service_route"))
            route_results.append({
                "ok": ok,
                "result": result,
                "params": params,
                "path": str(path or ""),
            })
            if not ok:
                all_ok = False

        if not all_ok:
            logger.warning(
                "event=tool_call_failed_cmd_result Tool call failed | cmd=%s | route_results=%s",
                action_name,
                route_results,
            )
            return {
                "executed": False,
                "command": action_name,
                "title": matched.get("title") or action_name,
                "service": matched.get("service") or "",
                "path": str(matched.get("path") or ""),
                "text": "⚠️ Non è stato possibile completare l'azione. Uno o più target non sono stati aggiornati.",
            }

        payload_for_format: Any
        if len(route_results) == 1:
            payload_for_format = route_results[0].get("result")
        else:
            payload_for_format = {
                "action": action_name,
                "executions": [
                    {
                        "path": row.get("path"),
                        "params": row.get("params"),
                        "result": row.get("result"),
                    }
                    for row in route_results
                ],
                "count": len(route_results),
            }

        answer = self.format_payload(
            command=action_name,
            payload=payload_for_format,
            response_prompt=matched.get("response_prompt", ""),
            client_instructions=client_instructions,
            variant_seed=str(trace_id or session_id or action_name),
        )
        return {
            "executed": True,
            "command": action_name,
            "title": matched.get("title") or action_name,
            "service": matched.get("service") or "",
            "path": str(matched.get("path") or ""),
            "text": answer,
        }

    def _embed(self, text: str) -> list[float]:
        """Embed *text* via the primary embedding agent.  Rulebook 1.6: WORKS or LOG AND FAIL."""
        try:
            vector = self._agents.embedding.embed(text)
            if vector:
                return vector
        except Exception:
            logger.error("event=embed_failed text_len=%d", len(text or ""), exc_info=True)
        return []

    def _resolve_agent(self, model: str):
        """Return the UniversalAgent for the given use case. Falls back to generic."""
        usecase = str(model or "generic").strip().lower()
        if usecase == "reasoning":
            return self._agents.reasoning
        if usecase == "code":
            return self._agents.code
        return self._agents.generic

    def _ask_analyst(self, prompt: str, thinking: bool = False) -> str:
        """Ask the primary analyst.  Rulebook 1.6: WORKS or LOG AND FAIL."""
        try:
            return self._agents.generic.ask(prompt, thinking=thinking)
        except Exception:
            logger.error(
                "event=primary_analyst_failed prompt_len=%d", len(prompt), exc_info=True)
            raise

    def _ask_analyst_with_tools(
        self, prompt: str, tools_manifest: list[dict],
        agent_override: "UniversalAgent | None" = None,
        thinking: bool = False,
    ) -> dict:
        """Ask analyst with provider-native tool-calling.

        *agent_override* selects the brain (from _resolve_agent(model)).
        *thinking* controls the Ollama ``think`` flag (derived from mode).
        Both are independent — any mode × any model combination works.

        Rulebook 1.6: WORKS or LOG AND FAIL — no silent fallback chain.
        """
        primary = agent_override if agent_override is not None else self._agents.generic

        logger.trace("event=ask_analyst_with_tools_entry prompt_len=%d tool_count=%d tool_names=%s agent=%s thinking=%s",
                     len(prompt), len(tools_manifest),
                     [t.get("name", "?") for t in (tools_manifest or [])[:10]],
                     getattr(primary, 'model_name', 'unknown'),
                     thinking)
        try:
            return primary.ask_with_tools(prompt, tools_manifest, thinking=thinking)
        except Exception:
            logger.error(
                "event=ask_analyst_with_tools_failed agent=%s prompt_len=%d tool_count=%d",
                getattr(primary, 'model_name', 'unknown'),
                len(prompt), len(tools_manifest),
                exc_info=True,
            )
            raise

    def _stream_analyst(self, prompt: str):
        """Stream tokens from primary analyst.  Rulebook 1.6: WORKS or LOG AND FAIL.

        If the stream fails after partial output, returns collected tokens.
        If it fails before any output, LOG AND RAISE — no silent fallback.
        """
        tokens: list[str] = []
        try:
            for token in self._agents.generic.ask_stream(prompt):
                tokens.append(token)
                yield stream_emitter.emit_token(token)
            return "".join(tokens)
        except Exception:
            if tokens:
                logger.warning(
                    "event=primary_analyst_failed_mid_stream tokens=%d", len(tokens), exc_info=True)
                return "".join(tokens)
            logger.error(
                "event=primary_analyst_stream_failed_zero_tokens prompt_len=%d", len(prompt), exc_info=True)
            raise

    def _quick_answer(
        self,
        user_message: str,
        history_text: str,
        client_instructions: str | None,
        extra_context: str | None,
        current_datetime_context: str | None = None,
    ) -> str:
        # Only when the user asked for a change: otherwise small models repeat the
        # contract to the user ("Non risulta eseguita alcuna azione di modifica").
        no_action_contract = prompt_config.prompt(
            "no_action_execution_contract") if has_write_intent(user_message) else ""
        combined_client_instructions = "\n\n".join(
            part for part in [no_action_contract, client_instructions or ""] if str(part).strip()
        )
        prompt = prompt_config.compose_with_dynamic_boundary(
            static_sections=[
                prompt_config.prompt(
                    "quick_chat_static_instruction",
                    conversation_style_contract=conversation_style_contract(),
                )
            ],
            dynamic_sections=[
                prompt_config.optional_section(
                    "CURRENT_DATETIME_CONTEXT", current_datetime_context
                ).strip(),
                prompt_config.optional_section(
                    "CONTESTO CONVERSAZIONE", history_text
                ).strip(),
                prompt_config.optional_section(
                    "CONTESTO AGGIUNTIVO", extra_context
                ).strip(),
                prompt_config.optional_section(
                    "STILE CLIENTE", combined_client_instructions
                ).strip(),
                f"MESSAGGIO UTENTE:\n{user_message}",
            ],
        )
        # The generic chain already tries its fallback steps.
        answer = self._ask_analyst(prompt)
        if _CLAIMED_ACTION.search(answer or ""):
            # No tools here: an answer that says it did something is false (bench 2026-10-30: «oggi sono stanco»
            # → «Ho registrato la stanchezza, riduco gli impegni»). One more try with the reason spelled out.
            logger.info("[🔄] event=quick_answer_claimed_action answer=%s", (answer or "")[:120])
            answer = self._ask_analyst(prompt + "\n\n" + prompt_config.prompt("quick_chat_no_claim_retry")) or answer
        return answer

    def _now_in_oracle_timezone(self) -> datetime:
        """Return timezone-aware current datetime in the container TZ when valid."""
        if ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(self._oracle_timezone))
            except Exception:
                logger.warning(
                    "event=oracle_timezone_invalid_fallback_utc Invalid TZ value | timezone=%s fallback=UTC",
                    self._oracle_timezone,
                )
        return datetime.now(datetime_timezone.utc)

    def _current_datetime_context(self) -> str:
        """Build an enriched temporal context block for relative date reasoning.

        Includes: timezone, datetime, weekday, time-of-day, season, and
        calendar events from Chronos (when available).
        """
        now_dt = self._now_in_oracle_timezone()
        tomorrow_dt = now_dt + timedelta(days=1)

        # Time-of-day
        hour = now_dt.hour
        if 5 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 18:
            time_of_day = "afternoon"
        elif 18 <= hour < 22:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        # Season (Northern Hemisphere)
        month = now_dt.month
        if 3 <= month <= 5:
            season = "Spring"
        elif 6 <= month <= 8:
            season = "Summer"
        elif 9 <= month <= 11:
            season = "Autumn"
        else:
            season = "Winter"

        lines = [
            f"timezone={str(now_dt.tzinfo or 'UTC')}",
            f"now_iso={now_dt.isoformat()}",
            f"today_date={now_dt.strftime('%Y-%m-%d')}",
            f"today_weekday={now_dt.strftime('%A')}",
            f"tomorrow_date={tomorrow_dt.strftime('%Y-%m-%d')}",
            f"tomorrow_weekday={tomorrow_dt.strftime('%A')}",
            f"time_of_day={time_of_day}",
            f"season={season}",
        ]

        # Calendar context from Chronos (best-effort, non-blocking)
        from core.services import oracle_settings as _os
        if _os.get_bool(_os.TODAY_AGENDA):
            try:
                agenda = self._hub.route_to_service(
                    service="chronos",
                    path="api/calendar/agenda",
                    method="GET",
                    query={"days": 1},
                    timeout=4,
                )
                if agenda[0] and isinstance(agenda[1], dict):
                    events = agenda[1].get("events", [])
                    if events:
                        lines.append("TODAY_AGENDA:")
                        for ev in events[:5]:
                            title = ev.get("title", "?")
                            start = ev.get("start", "")
                            end = ev.get("end", "")
                            lines.append(f"  {start} → {end}: {title}")
            except Exception:
                pass  # Non-critical — calendar context is a bonus

        return "\n".join(lines)

    def _save_history(self, session_id: str, user_message: str, answer: str, trace_id: str | None = None) -> None:
        try:
            headers = self._trace_headers(session_id, trace_id)
            self._hub.post(
                "/chat/history",
                {"session_id": session_id, "role": "user", "content": user_message},
                headers=headers,
            )
            self._hub.post(
                "/chat/history",
                {"session_id": session_id, "role": "assistant", "content": answer},
                headers=headers,
            )
        except Exception as exc:
            logger.warning(
                "event=failed_persist_chat_history Failed to persist chat history: %s", exc)

    def _load_preferences(self, valid_domains: list[str]) -> list[dict]:
        """Load preferences relevant to *valid_domains* (multi-domain aware).

        Preferences with a ``domains`` list (from embedding-based assignment)
        are included if ANY of their domains match *valid_domains*.
        Legacy single-``domain`` preferences match directly.
        ``general`` domain preferences are always included.
        """
        all_prefs: list[dict] = []
        seen: set[str] = set()
        search_domains = set(valid_domains) | {"general"}

        for domain in search_domains:
            rows = self._hub.get(
                f"/memory/active?domain={domain}&memory_class=durable_user_preference") or []
            if not rows:
                rows = self._hub.get(f"/memory/active?domain={domain}") or []
            for pref in rows:
                pid = str(pref.get("id") or "")
                if pid and pid in seen:
                    continue
                seen.add(pid)
                # Check multi-domain compatibility
                pref_domains = pref.get("domains")
                if isinstance(pref_domains, list) and pref_domains:
                    if not search_domains.intersection(pref_domains):
                        continue  # no domain overlap — skip
                all_prefs.append(pref)

        logger.trace(
            "event=preferences_loaded valid_domains=%s total=%d",
            valid_domains, len(all_prefs),
        )
        return all_prefs
