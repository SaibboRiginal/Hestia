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
from core.services.chat_classifier import ChatClassifier, QUICK_CHAT_CONFIDENCE_THRESHOLD
from core.services import stream_emitter
from core.services import prompt_config
from core.services.context_builder import ContextBuilder
from core.services.memory_intent import (
    has_deprecate_intent,
    has_notification_intent,
    has_preference_intent,
)
from core.services.memory_service import MemoryService
from core.services.user_control_service import UserControlService
from core.services.module_registry import ModuleToolRegistry
from core.services.retrieval_service import RetrievalService
from core.document.archiver import DocumentArchiver
from core.document.rag import DocumentRAG
from core.document.analyser import DocumentAnalyser
from core.agent_loop import run_agent_loop, ToolDefinition


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

_NUMERIC_SHORTHAND_PATTERN = re.compile(
    r"^\s*([0-9]+(?:[\.,][0-9]+)?)\s*([kKmM])\s*$")
_TEMPLATE_VAR_PATTERN = re.compile(
    r"\$(session_id|chat_id|owner|arg\.[a-zA-Z0-9_]+)")


# ── Tool-call helper functions ─────────────────────────────────────────────────

def _collect_vars(obj, result: set) -> None:
    """Collect all $variable names from a nested template structure."""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_vars(v, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_vars(item, result)
    elif isinstance(obj, str):
        text = obj.strip()
        if text.startswith("$"):
            result.add(text[1:])
        for match in _TEMPLATE_VAR_PATTERN.finditer(obj):
            result.add(match.group(1))


def _resolve_var_token(var: str, args: dict, session_id: str, notify_target: str | None):
    if var == "session_id":
        return session_id
    if var in ("chat_id", "owner") and notify_target:
        return notify_target
    if var.startswith("arg."):
        return args.get(var.replace("arg.", "", 1).strip().lower())
    return args.get(var)


def _resolve_template(obj, args: dict, session_id: str, notify_target: str | None):
    """Recursively resolve $var references in a template dict/list/str."""
    if isinstance(obj, dict):
        return {k: _resolve_template(v, args, session_id, notify_target) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_template(item, args, session_id, notify_target) for item in obj]
    if isinstance(obj, str):
        text = obj.strip()
        if text.startswith("$"):
            # Check if it exactly matches one token so we can preserve real types (like int/bool)
            if _TEMPLATE_VAR_PATTERN.fullmatch(text):
                return _resolve_var_token(text[1:], args, session_id, notify_target)

        def _sub(match: re.Match) -> str:
            token = match.group(1)
            resolved = _resolve_var_token(
                token, args, session_id, notify_target)
            if resolved is None:
                return ""
            # If the resolved token needs to be inserted into a path, ensure it's URL-encoded if it has spaces or special chars
            from urllib.parse import quote
            return quote(str(resolved), safe="")

        return _TEMPLATE_VAR_PATTERN.sub(_sub, obj)
    return obj


def _strip_nones(obj):
    """Remove None values from nested dicts/lists (for clean API payloads)."""
    if isinstance(obj, dict):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nones(item) for item in obj if item is not None]
    return obj


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


class OracleEngine:
    """Top-level orchestrator — instantiate once per process."""

    def __init__(self) -> None:
        self._hub_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self._archive_url = os.getenv(
            "ARCHIVE_API_URL", "http://hestia_archive:19002/api")

        # ── LLM agents ────────────────────────────────────────────────────────
        self._agents = AgentFactory.create()

        # ── Infrastructure services ───────────────────────────────────────────
        self._hub = HubClient(self._hub_url)

        # Small TTL caches for quasi-static discovery endpoints.
        self._domains_cache_ttl_seconds = int(
            os.getenv("ORACLE_DOMAINS_CACHE_TTL_SECONDS", "30"))
        self._schemas_cache_ttl_seconds = int(
            os.getenv("ORACLE_SCHEMAS_CACHE_TTL_SECONDS", "30"))
        self._domains_cache_value: list[str] = ["general"]
        self._domains_cache_ts: float = 0.0
        self._schemas_cache_value: dict = {}
        self._schemas_cache_ts: float = 0.0

        self._context_builder = ContextBuilder(
            max_history_messages=int(os.getenv("ORACLE_HISTORY_LIMIT", "6")),
            max_history_chars=int(
                os.getenv("ORACLE_HISTORY_CHAR_LIMIT", "500")),
            max_entities_in_context=int(
                os.getenv("ORACLE_CONTEXT_ENTITIES_LIMIT", "12")),
            max_field_chars=int(
                os.getenv("ORACLE_CONTEXT_FIELD_CHAR_LIMIT", "280")),
        )

        module_tool_urls = [
            u.strip()
            for u in os.getenv("MODULE_TOOLS_URLS", "").split(",")
            if u.strip()
        ]
        if single := os.getenv("MODULE_TOOLS_URL", "").strip():
            module_tool_urls.append(single)

        self._module_registry = ModuleToolRegistry(
            module_tool_urls=module_tool_urls,
            ttl_seconds=int(
                os.getenv("MODULE_TOOL_REGISTRY_TTL_SECONDS", "120")),
            hub_api_url=self._hub_url,
        )

        self._retrieval_service = RetrievalService(
            archive_url=self._archive_url,
            hub_api_url=self._hub_url,
            module_registry=self._module_registry,
            embedder=self._embed,
        )

        self._memory_service = MemoryService(
            archive_url=self._archive_url,
            hub_api_url=self._hub_url,
            scribe_agent=self._agents.generic,
            fallback_scribe_agent=self._agents.generic_fallback,
            context_builder=self._context_builder,
        )

        self._control_service = UserControlService(
            hub_client=self._hub,
            scribe_agent=self._agents.generic,
            fallback_scribe_agent=self._agents.generic_fallback,
        )

        self._classifier = ChatClassifier(
            router_agent=self._agents.generic,
            fallback_router_agent=self._agents.generic_fallback,
        )

        # ── Document pipeline ─────────────────────────────────────────────────
        self._archiver = DocumentArchiver(
            hub_client=self._hub,
            embed_fn=self._embed,
            analyst=self._agents.generic,
            fallback_analyst=self._agents.generic_fallback,
        )

        self._doc_rag = DocumentRAG(
            hub_client=self._hub,
            embed_fn=self._embed,
        )

        self._doc_analyser = DocumentAnalyser(
            hub_client=self._hub,
            archiver=self._archiver,
            analyst=self._agents.generic,
            fallback_analyst=self._agents.generic_fallback,
            style_contract_fn=conversation_style_contract,
        )

        # ── Cross-client question store ────────────────────────────────────────
        # In-process dict: question_id → {session_id, question, answer, resolved}
        # Future: persist to Archive for multi-process / restart resilience.
        self._pending_questions: dict[str, dict] = {}
        self._questions_lock = threading.Lock()

        # ── Phase 2: query-source execution policy matrix ─────────────────────
        # Keep execution behavior explicit by request source.
        self._execution_policy_timeouts: dict[str, int] = {
            "foreground_chat": int(os.getenv("ORACLE_POLICY_FOREGROUND_CHAT_TIMEOUT_SEC", "8")),
            "action_selection": int(os.getenv("ORACLE_POLICY_ACTION_SELECTION_TIMEOUT_SEC", "12")),
            "action_service_route": int(os.getenv("ORACLE_POLICY_ACTION_SERVICE_ROUTE_TIMEOUT_SEC", "25")),
            "memory_extraction": int(os.getenv("ORACLE_POLICY_MEMORY_EXTRACTION_TIMEOUT_SEC", "10")),
            "background_compaction": int(os.getenv("ORACLE_POLICY_BACKGROUND_COMPACTION_TIMEOUT_SEC", "8")),
            "notification_formatting": int(os.getenv("ORACLE_POLICY_NOTIFICATION_FORMATTING_TIMEOUT_SEC", "12")),
        }
        self._task_store = TaskLifecycleStore(
            max_tasks=int(os.getenv("ORACLE_TASK_STORE_MAX", "500")),
        )

        self._oracle_timezone = str(
            os.getenv("ORACLE_TIMEZONE", "Europe/Rome")).strip() or "Europe/Rome"
        self._agent_action_tool_policy = os.getenv(
            "ORACLE_AGENT_ACTION_TOOL_POLICY",
            "If the user asks for an operational change (create, update, delete, enable, disable), you must call at least one relevant tool before final answer when matching tools exist.",
        ).strip()

        # ── High-impact action approval gate ────────────────────────────────
        self._approval_enabled = os.getenv(
            "ORACLE_HIGH_IMPACT_APPROVAL_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        self._approval_ttl_seconds = int(
            os.getenv("ORACLE_HIGH_IMPACT_APPROVAL_TTL_SECONDS", "600"))
        self._approval_bulk_min_count = int(
            os.getenv("ORACLE_HIGH_IMPACT_APPROVAL_BULK_MIN_COUNT", "2"))
        self._approval_methods = {
            item.strip().upper()
            for item in os.getenv("ORACLE_HIGH_IMPACT_APPROVAL_METHODS", "DELETE,PUT,PATCH").split(",")
            if item.strip()
        }
        self._approval_command_allowlist = {
            item.strip().lower()
            for item in os.getenv("ORACLE_HIGH_IMPACT_APPROVAL_COMMANDS", "").split(",")
            if item.strip()
        }
        self._pending_action_approvals: dict[str, dict[str, Any]] = {}
        self._approval_lock = threading.Lock()

        # ── Athena advisory hints (Hub-routed ingest) ───────────────────────
        self._athena_hints_enabled = os.getenv(
            "ORACLE_ATHENA_HINTS_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        self._athena_hints_ttl_seconds = int(
            os.getenv("ORACLE_ATHENA_HINTS_TTL_SECONDS", "7200"))
        self._athena_hints_max = int(
            os.getenv("ORACLE_ATHENA_HINTS_MAX", "300"))
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
        if not self._athena_hints_enabled:
            return {
                "status": "disabled",
                "stored": False,
                "reason": "ORACLE_ATHENA_HINTS_ENABLED=0",
            }

        now = time.time()
        ttl_seconds = int(hint_payload.get("ttl_seconds")
                          or self._athena_hints_ttl_seconds)
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
            if len(self._athena_hints) > self._athena_hints_max:
                self._athena_hints = self._athena_hints[-self._athena_hints_max:]

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
    ) -> str:
        """Register a pending question and return the NDJSON question frame to emit."""
        with self._questions_lock:
            self._pending_questions[question_id] = {
                "session_id": session_id,
                "header": header,
                "prompt": prompt,
                "kind": kind,
                "answer": None,
                "resolved": False,
            }
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
            prompt=prompt,
            kind=kind,
            options=options,
            timeout_sec=timeout_sec,
            required=required,
        )

    def _trace_headers(self, session_id: str, trace_id: str | None = None) -> dict:
        headers = {"X-Session-Id": session_id}
        if trace_id:
            headers["X-Trace-Id"] = str(trace_id)
        return headers

    def _policy_timeout(self, source: str, fallback: int = 10) -> int:
        """Return configured timeout seconds for a given execution source."""
        value = self._execution_policy_timeouts.get(source, fallback)
        try:
            return max(1, int(value))
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
        if not self._athena_hints_enabled:
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
            if not entry:
                return False
            entry["answer"] = answer
            entry["resolved"] = True
        self._append_interaction_ledger(
            event_type="question_answered",
            session_id=str(entry.get("session_id") or ""),
            actor="user",
            domain="general",
            reference_id=question_id,
            payload={"answer": answer},
        )
        return True

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
    ):
        """Main conversational loop. Yields NDJSON lines.

        Modes (control PROCESS, same model for all):
          quick    → single ask(), no classify, no tools. <2s latency.
          auto     → classify → agent loop if domain_query. Default.
          thinking → full agent loop, visible chain-of-thought, higher max_turns.

        Model (controls which BRAIN):
          generic   → daily driver (gemma4:e4b)
          reasoning → deep thinking (26B, loaded on demand)
          code      → code generation
        """
        t0 = time.perf_counter()
        trace_id = uuid.uuid4().hex[:12]
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

        # ── MODE: quick ───────────────────────────────────────────────────────
        if mode == "quick":
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
            self._phase_background_memory(
                user_message, session_id, notify_target,
                force_notification_compiler, trace_id=trace_id,
            )
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

        # ── Phase 3: QUICK CHAT shortcut ──────────────────────────────────────
        if intent.mode == "quick_chat" and intent.confidence >= QUICK_CHAT_CONFIDENCE_THRESHOLD:
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
            self._phase_background_memory(
                user_message, session_id, notify_target,
                force_notification_compiler,
                skip_memory_extract=sync_attempted,
                trace_id=trace_id,
            )
            return

        # ── Phase 4: AGENT LOOP (unified — all tools, all commands) ───────────
        yield stream_emitter.emit_status(
            f"🧠 Analisi domini: {', '.join(intent.valid_domains)}..."
        )

        # Load preferences for agent loop context
        all_prefs = self._load_preferences(intent.valid_domains)
        preference_facts = [str(p.get("fact", "")).strip()
                            for p in all_prefs if p.get("fact")]

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

        build_domains = [d for d in available_domains if d != "general"]
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

        # Assemble agent loop client instructions
        agent_loop_client_instructions_parts: list[str] = []
        if planner_contract:
            agent_loop_client_instructions_parts.append(planner_contract)
        if intent.action_intent and self._agent_action_tool_policy:
            agent_loop_client_instructions_parts.append(
                self._agent_action_tool_policy)
        if athena_hint_prompt_block:
            agent_loop_client_instructions_parts.append(
                f"ATHENA_ADVISORY_HINTS:\n{athena_hint_prompt_block}")
        if temporal_context:
            agent_loop_client_instructions_parts.append(
                f"CURRENT_DATETIME_CONTEXT:\n{temporal_context}")
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
        _default_max_turns = int(os.getenv("ORACLE_MAX_AGENT_TURNS", "25"))
        resolved_max_turns = _default_max_turns
        if mode == "thinking":
            resolved_max_turns = max(resolved_max_turns, 50)
            yield stream_emitter.emit_status("🧠 Modalità thinking attivata — ragionamento approfondito...")

        answer, tokens, tool_log = run_agent_loop(
            user_message=user_message,
            history_text=history_text,
            preference_facts=preference_facts,
            tools=domain_tools,
            ask_fn=self._ask_analyst,
            ask_tools_fn=self._ask_analyst_with_tools,
            stream_fn=_stream_final,
            client_instructions=agent_loop_client_instructions,
            conversation_style=conversation_style_contract(),
            max_turns=resolved_max_turns,
            on_thinking=_on_thinking,
            action_intent=intent.action_intent,
        )
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

        # Memory sync (synchronous only for explicit mutation intent)
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

        # Emit final answer
        yield stream_emitter.emit_final(
            answer,
            intent.valid_domains[0] if intent.valid_domains else "general",
        )

        # Emit tool-call summary as a post-answer signal (rendered as separate message)
        if tool_log:
            yield stream_emitter.emit_tool_summary(tool_log)

        total_ms = int((time.perf_counter() - t0) * 1000)
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

        # Background memory extraction (always async, never blocks the user)
        self._phase_background_memory(
            user_message,
            session_id,
            notify_target,
            force_notification_compiler,
            skip_memory_extract=sync_attempted,
            trace_id=trace_id,
        )

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
        """Return context-window usage estimates for *session_id*."""
        _est = lambda s: int(len(s or "") / 3)
        CONTEXT_WINDOW = 256_000  # Gemma 4

        # History
        history_data = self._hub.get_history(session_id, limit=200) or []
        history_chars = sum(len(str(m.get("content", ""))) for m in history_data if isinstance(m, dict))
        history_tokens = _est("x" * history_chars)

        # Tools from Hub
        all_commands = self._hub.get_commands() or []
        tool_count = len(all_commands)
        tool_chars_est = tool_count * 120  # compact name+desc average

        # Preferences
        prefs = self._load_preferences(["general"]) or []
        pref_count = len(prefs)
        pref_chars = sum(len(str(p.get("fact", ""))) for p in prefs[:10])

        # System overhead (preamble, style, boundary markers)
        system_overhead = 3_500

        total_chars = history_chars + tool_chars_est + pref_chars + system_overhead
        total_tokens = _est("x" * total_chars)
        pct = (total_tokens / CONTEXT_WINDOW) * 100

        return {
            "context_window": CONTEXT_WINDOW,
            "history_messages": len(history_data) if isinstance(history_data, list) else 0,
            "history_chars": history_chars,
            "history_tokens_est": history_tokens,
            "tool_count": tool_count,
            "tool_chars_est": tool_chars_est,
            "preference_count": pref_count,
            "preference_chars": pref_chars,
            "total_chars_est": total_chars,
            "total_tokens_est": total_tokens,
            "context_used_pct": round(pct, 1),
            "context_remaining_est": CONTEXT_WINDOW - total_tokens,
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
            f"/chat/history/{session_id}?limit={self._context_builder.max_history_messages}",
            timeout=self._policy_timeout("foreground_chat"),
            headers=self._trace_headers(session_id, trace_id),
        )
        t_history_ms = int((time.perf_counter() - t0) * 1000)

        now = time.time()
        history_text = self._context_builder.compact_history(history_data)

        t_domains = time.perf_counter()
        available_domains = self._hub.hub_get(
            "/api/domains",
            timeout=self._policy_timeout("foreground_chat"),
        ) or ["general"]
        t_domains_ms = int((time.perf_counter() - t_domains) * 1000)

        schemas_from_cache = False
        if now - self._schemas_cache_ts <= self._schemas_cache_ttl_seconds and isinstance(self._schemas_cache_value, dict):
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
    ) -> None:
        """Fire-and-forget memory extraction + compaction check in a daemon thread."""
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

            # ── Memory extraction ──────────────────────────────────────────────
            if not skip_memory_extract:
                try:
                    t_mem = time.perf_counter()
                    self._memory_service.extract_and_save_preferences(
                        user_message, session_id,
                        notify_target=notify_target,
                        force_notification_compiler=force_notification_compiler,
                    )
                    mem_ms = int((time.perf_counter() - t_mem) * 1000)
                    logger.info(
                        "event=background_phase_timing_ms Background phase timing | session=%s phase=memory_extract ms=%s",
                        session_id, mem_ms,
                    )
                except Exception as exc:
                    logger.warning(
                        "event=background_memory_sync_failed Background memory sync failed: %s", exc)
            else:
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

    def _sync_memory_if_needed(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None,
        force_notification_compiler: bool,
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
        all_commands = self._hub.get_commands() or []
        _filtered_cmds = 0
        for cmd in all_commands:
            cmd_name = cmd.get("command")
            if not cmd_name:
                continue

            # Domain-gate: only include commands from domain-owning services.
            # memory.* / documents.* tools are added separately below.
            cmd_service = str(cmd.get("service", "") or "").strip()
            if _relevant_services and cmd_service not in _relevant_services:
                _filtered_cmds += 1
                continue

            # Build schema for Agent
            schema = {
                "type": "object",
                "properties": {},
                "required": []
            }

            args_schema = cmd.get("arguments_schema") or {}

            if args_schema:
                schema["properties"] = {
                    k: {
                        "description": str(v.get("description", k)),
                        "type": str(v.get("type", "string"))
                    } for k, v in args_schema.items()
                }
                schema["required"] = [
                    k for k, v in args_schema.items() if dict(v).get("required", False)]
            else:
                flat = set()
                _collect_vars(cmd.get("body_template") or {}, flat)
                _collect_vars(cmd.get("query_template") or {}, flat)
                _collect_vars(str(cmd.get("path") or ""), flat)
                flat -= {"session_id", "chat_id", "owner"}
                for v in flat:
                    schema["properties"][v] = {
                        "type": "string", "description": v}
                    schema["required"].append(v)

            def make_handler(command_def):
                def _hub_command_handler(**kwargs):
                    method = str(command_def.get("method", "GET")).upper()
                    service = str(command_def.get("service", ""))
                    path_tpl = str(command_def.get("path") or "").strip()

                    body = _resolve_template(
                        command_def.get("body_template") or {},
                        kwargs,
                        session_id,
                        notify_target,
                    )
                    query = _resolve_template(
                        command_def.get("query_template") or {},
                        kwargs,
                        session_id,
                        notify_target,
                    )
                    # Auto-map remaining kwargs as query params for GET/HEAD
                    # requests when no explicit query_template was provided.
                    if method in ("GET", "HEAD", "DELETE") and not command_def.get("query_template"):
                        for k, v in kwargs.items():
                            if k not in query and v is not None:
                                query[k] = v

                    path = _resolve_template(
                        path_tpl,
                        kwargs,
                        session_id,
                        notify_target,
                    )

                    if body and isinstance(body, dict):
                        body = _strip_nones(body) or None
                    if query and isinstance(query, dict):
                        query = {k: v for k, v in query.items()
                                 if v is not None}

                    try:
                        ok, result = self._hub.route_to_service(
                            service=service,
                            path=str(path).lstrip("/"),
                            method=method,
                            body=body,
                            query=query or {},
                            timeout=self._policy_timeout(
                                "action_service_route"),
                            headers=self._trace_headers(session_id, trace_id),
                        )
                        return (ok, result)
                    except Exception as exc:
                        import traceback
                        return (False, f"Hub command execution failed: {exc}\n{traceback.format_exc()}")

                return _hub_command_handler

            if any(t.name == cmd_name for t in tools):
                continue

            tools.append(ToolDefinition(
                name=cmd_name,
                description=cmd.get(
                    "description", f"Execute {cmd_name} command"),
                parameters=schema,
                handler=make_handler(cmd)
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

        return tools

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
        if not self._approval_enabled:
            return False

        method = str(matched.get("method", "POST")).upper().strip()
        if method in self._approval_methods:
            return True

        if self._approval_command_allowlist and action_name.strip().lower() in self._approval_command_allowlist:
            return True

        return len(param_sets) >= max(1, self._approval_bulk_min_count)

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
                "expires_at": time.time() + max(30, self._approval_ttl_seconds),
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
            body = _resolve_template(
                matched.get("body_template") or {},
                params,
                session_id,
                notify_target,
            )
            query = _resolve_template(
                matched.get("query_template") or {},
                params,
                session_id,
                notify_target,
            )
            path = _resolve_template(
                str(matched.get("path") or "").strip(),
                params,
                session_id,
                notify_target,
            )

            if body and isinstance(body, dict):
                body = _strip_nones(body) or None
            if query and isinstance(query, dict):
                query = {k: v for k, v in query.items() if v is not None}

            logger.info(
                "event=tool_call_cmd_service_path Tool call | cmd=%s service=%s path=%s",
                action_name,
                matched.get("service", ""),
                path,
            )
            ok, result = self._hub.route_to_service(
                service=matched.get("service", ""),
                path=str(path or ""),
                method=matched.get("method", "POST"),
                body=body,
                query=query or {},
                timeout=self._policy_timeout("action_service_route"),
                headers=self._trace_headers(session_id, trace_id),
            )
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
        """Embed *text*, falling back to the secondary embedder on failure."""
        for agent in (self._agents.embedding, self._agents.embedding_fallback):
            try:
                vector = agent.embed(text)
                if vector:
                    return vector
            except Exception:
                pass
        return []

    def _resolve_agent(self, model: str):
        """Return the UniversalAgent for the given use case. Falls back to generic."""
        usecase = str(model or "generic").strip().lower()
        if usecase == "reasoning":
            return self._agents.reasoning
        if usecase == "code":
            return self._agents.code
        return self._agents.generic

    def _ask_analyst(self, prompt: str) -> str:
        """Ask the primary analyst, falling back to secondary on error."""
        try:
            return self._agents.generic.ask(prompt)
        except Exception as exc:
            logger.warning(
                "event=primary_analyst_failed_using_fallback Primary analyst failed, using fallback: %s", exc)
        try:
            return self._agents.generic_fallback.ask(prompt)
        except Exception as exc:
            logger.error(
                "event=fallback_analyst_also_failed Fallback analyst also failed: %s", exc)
            return "⚠️ In questo momento i modelli sono temporaneamente non disponibili. Riprova tra poco."

    def _ask_analyst_with_tools(self, prompt: str, tools_manifest: list[dict]) -> dict:
        """Ask analyst with provider-native tool-calling when available."""
        logger.trace("event=ask_analyst_with_tools_entry prompt_len=%d tool_count=%d tool_names=%s",
                     len(prompt), len(tools_manifest),
                     [t.get("name", "?") for t in (tools_manifest or [])[:10]])
        try:
            return self._agents.generic.ask_with_tools(prompt, tools_manifest)
        except Exception as exc:
            logger.warning(
                "event=primary_analyst_tool_call_failed_using_fallback Primary analyst tool call failed, using fallback: %s", exc)
        try:
            return self._agents.generic_fallback.ask_with_tools(prompt, tools_manifest)
        except Exception as exc:
            logger.error(
                "event=fallback_analyst_tool_call_also_failed Fallback analyst tool call also failed: %s", exc)
            return {"tool_call": None, "text": self._ask_analyst(prompt)}

    def _stream_analyst(self, prompt: str):
        """Stream tokens from primary analyst, falling back to secondary on error.

        Yields NDJSON token frames as they arrive from the provider.
        Returns (via StopIteration.value / ``yield from``) the full joined text.

        Fallback strategy:
        - If primary fails BEFORE any tokens are yielded → try fallback streaming.
        - If primary fails AFTER tokens have been yielded → stop mid-stream and
          return whatever was collected (avoids duplicate content to client).
        - If fallback also fails → return generic error message.
        """
        tokens: list[str] = []
        try:
            for token in self._agents.generic.ask_stream(prompt):
                tokens.append(token)
                yield stream_emitter.emit_token(token)
            return "".join(tokens)
        except Exception as exc:
            if tokens:
                # Mid-stream failure after partial output — don't retry (client
                # has already received partial tokens; retrying would duplicate).
                logger.warning(
                    "event=primary_analyst_failed_mid_stream Primary analyst failed mid-stream (%d tokens): %s", len(tokens), exc)
                return "".join(tokens)
            logger.warning(
                "event=primary_analyst_stream_failed_tokens Primary analyst stream failed (0 tokens), trying fallback: %s", exc)

        # Fallback — primary yielded nothing
        try:
            for token in self._agents.generic_fallback.ask_stream(prompt):
                tokens.append(token)
                yield stream_emitter.emit_token(token)
            return "".join(tokens)
        except Exception as exc:
            logger.error(
                "event=fallback_analyst_stream_also_failed Fallback analyst stream also failed: %s", exc)
            return "⚠️ In questo momento i modelli sono temporaneamente non disponibili. Riprova tra poco."

    def _quick_answer(
        self,
        user_message: str,
        history_text: str,
        client_instructions: str | None,
        extra_context: str | None,
        current_datetime_context: str | None = None,
    ) -> str:
        no_action_contract = prompt_config.prompt(
            "no_action_execution_contract")
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
        # Use primary agent first; fall back only on failure
        try:
            return self._agents.generic.ask(prompt)
        except Exception:
            try:
                return self._agents.generic_fallback.ask(prompt)
            except Exception:
                return self._ask_analyst(prompt)

    def _now_in_oracle_timezone(self) -> datetime:
        """Return timezone-aware current datetime using ORACLE_TIMEZONE when valid."""
        if ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(self._oracle_timezone))
            except Exception:
                logger.warning(
                    "event=oracle_timezone_invalid_fallback_utc Invalid ORACLE_TIMEZONE value | timezone=%s fallback=UTC",
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
        if os.getenv("ORACLE_TEMPORAL_CALENDAR_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}:
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
        all_prefs: list[dict] = []
        seen: set = set()
        for domain in valid_domains:
            # P1-8 taxonomy: prefer durable preference class.
            rows = self._hub.get(
                f"/memory/active?domain={domain}&memory_class=durable_user_preference") or []
            # Backward compatibility with legacy untyped preference rows.
            if not rows:
                rows = self._hub.get(f"/memory/active?domain={domain}") or []
            for pref in rows:
                pid = pref.get("id")
                if pid and pid not in seen:
                    all_prefs.append(pref)
                    seen.add(pid)
        return all_prefs
