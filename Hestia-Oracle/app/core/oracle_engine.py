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
from importlib import import_module
from pathlib import Path
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

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
_WORD_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]{2,}")

_DEFAULT_ACTION_INTENT_HINT_TERMS = (
    "crea",
    "aggiungi",
    "modifica",
    "aggiorna",
    "imposta",
    "setta",
    "attiva",
    "disattiva",
    "rimuovi",
    "elimina",
    "cancella",
    "esegui",
    "abilita",
    "disable",
    "enable",
    "delete",
    "remove",
    "update",
    "create",
    "set",
    "run",
)
_ACTION_INTENT_HINT_TERMS = tuple(
    item.strip().lower()
    for item in os.getenv(
        "ORACLE_ACTION_INTENT_HINT_TERMS",
        ",".join(_DEFAULT_ACTION_INTENT_HINT_TERMS),
    ).split(",")
    if item.strip()
)


def _tokenize_terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_TOKEN_PATTERN.findall(str(text or ""))
        if token and len(token) >= 2
    }


def _heuristic_action_intent(user_message: str) -> bool:
    text = str(user_message or "").strip().lower()
    if not text:
        return False
    if text.startswith("/"):
        return True
    return any(term in text for term in _ACTION_INTENT_HINT_TERMS)


def _heuristic_select_action_command(
    user_message: str,
    action_commands: list[dict],
) -> tuple[dict[str, Any] | None, float, str, list[str]]:
    text = str(user_message or "").strip().lower()
    if not text or not action_commands:
        return None, 0.0, "no_message_or_commands", []

    by_name: dict[str, dict[str, Any]] = {}
    for command in action_commands:
        cmd_name = str(command.get("command") or "").strip().lower()
        if cmd_name:
            by_name[cmd_name] = command

    for alias in re.findall(r"/([a-zA-Z0-9_]+)", text):
        command = by_name.get(alias.strip().lower())
        if command:
            return command, 100.0, "direct_slash_command", [alias.strip().lower()]

    for cmd_name, command in by_name.items():
        if re.search(rf"(^|\\b){re.escape(cmd_name)}($|\\b)", text):
            return command, 90.0, "direct_command_name", [cmd_name]

    user_tokens = _tokenize_terms(text)
    if not user_tokens:
        return None, 0.0, "no_user_tokens", []

    best_command: dict[str, Any] | None = None
    best_score = 0.0
    best_terms: list[str] = []

    for command in action_commands:
        cmd_name = str(command.get("command") or "").strip().lower()
        if not cmd_name:
            continue

        meta_text = " ".join(
            [
                cmd_name.replace("_", " "),
                str(command.get("title") or ""),
                str(command.get("description") or ""),
            ]
        )
        metadata_tokens = _tokenize_terms(meta_text)
        overlap = sorted(user_tokens & metadata_tokens)

        parts = [part for part in cmd_name.split("_") if part]
        part_hits = [part for part in parts if part in user_tokens]
        args_schema = command.get("arguments_schema") if isinstance(
            command.get("arguments_schema"), dict) else {}
        arg_hits = [
            str(name).strip().lower()
            for name in args_schema.keys()
            if str(name).strip().lower() in user_tokens
        ]

        score = float(len(overlap))
        if parts and len(part_hits) == len(parts):
            score += 1.5
        elif part_hits:
            score += 0.35 * float(len(part_hits))
        if arg_hits:
            score += 0.25 * float(len(arg_hits))

        if score > best_score:
            best_score = score
            best_command = command
            best_terms = list(dict.fromkeys((overlap + part_hits + arg_hits)))

    if best_command is None:
        return None, 0.0, "no_candidate", []
    return best_command, best_score, "token_overlap", best_terms[:10]


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


def _extract_arg_names_from_command(cmd: dict) -> set[str]:
    names: set[str] = set()

    for field in [cmd.get("path") or "", cmd.get("body_template") or {}, cmd.get("query_template") or {}]:
        collected: set[str] = set()
        _collect_vars(field, collected)
        for var in collected:
            if str(var).startswith("arg."):
                names.add(str(var).replace("arg.", "", 1).strip().lower())
            elif str(var) not in {"session_id", "chat_id", "owner"}:
                names.add(str(var).strip().lower())

    args_schema = cmd.get("arguments_schema") or {}
    if isinstance(args_schema, dict):
        for key in args_schema.keys():
            names.add(str(key).strip().lower())

    return {n for n in names if n}


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


def _coerce_param_types(user_params: dict, args_schema: dict) -> dict:
    """Coerce action params to schema-declared primitive types when possible."""
    if not isinstance(user_params, dict) or not isinstance(args_schema, dict):
        return user_params if isinstance(user_params, dict) else {}

    coerced: dict = dict(user_params)
    for key, schema in args_schema.items():
        if key not in coerced or not isinstance(schema, dict):
            continue

        val = coerced.get(key)
        expected = str(schema.get("type") or "").strip().lower()
        if not expected:
            continue

        try:
            if expected == "integer":
                parsed = _parse_numeric_like(val)
                if parsed is not None:
                    coerced[key] = int(round(float(parsed)))
            elif expected == "number":
                parsed = _parse_numeric_like(val)
                if parsed is not None:
                    coerced[key] = float(parsed)
            elif expected == "boolean" and isinstance(val, str):
                lowered = val.strip().lower()
                if lowered in {"true", "1", "yes", "y", "on"}:
                    coerced[key] = True
                elif lowered in {"false", "0", "no", "n", "off"}:
                    coerced[key] = False
            elif expected == "string" and val is not None and not isinstance(val, str):
                coerced[key] = str(val)
        except Exception:
            # Best-effort conversion only; never fail the action flow here.
            continue

    return coerced


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
            scribe_agent=self._agents.scribe,
            fallback_scribe_agent=self._agents.fallback_scribe,
            context_builder=self._context_builder,
        )

        self._control_service = UserControlService(
            hub_client=self._hub,
            scribe_agent=self._agents.scribe,
            fallback_scribe_agent=self._agents.fallback_scribe,
        )

        self._classifier = ChatClassifier(
            router_agent=self._agents.router,
            fallback_router_agent=self._agents.fallback_router,
        )

        # ── Document pipeline ─────────────────────────────────────────────────
        self._archiver = DocumentArchiver(
            hub_client=self._hub,
            embed_fn=self._embed,
            analyst=self._agents.analyst,
            fallback_analyst=self._agents.fallback_analyst,
        )

        self._doc_rag = DocumentRAG(
            hub_client=self._hub,
            embed_fn=self._embed,
        )

        self._doc_analyser = DocumentAnalyser(
            hub_client=self._hub,
            archiver=self._archiver,
            analyst=self._agents.analyst,
            fallback_analyst=self._agents.fallback_analyst,
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

        self._action_selector_heuristic_enabled = os.getenv(
            "ORACLE_ACTION_SELECTOR_HEURISTIC_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        try:
            self._action_selector_heuristic_min_score = float(
                os.getenv("ORACLE_ACTION_SELECTOR_HEURISTIC_MIN_SCORE", "1.75"))
        except Exception:
            self._action_selector_heuristic_min_score = 1.75
        self._query_selector_heuristic_min_score = max(
            2.25,
            self._action_selector_heuristic_min_score,
        )
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
            logger.debug(
                "event=interaction_ledger_append_failed_non Interaction ledger append failed (non-fatal): %s", exc)

    def chat(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        force_notification_compiler: bool = False,
        client_instructions: str | None = None,
        save_history: bool = True,
    ):
        """Main conversational loop. Yields NDJSON lines.

        Phases:
          INIT     → load history + domain manifest
          CLASSIFY → route intent (quick_chat vs domain_query)
          CONTEXT  → load prefs, retrieve entities, build prompt
          GENERATE → stream LLM tokens
          PERSIST  → save history (sync), memory extraction (background)
        """
        t0 = time.perf_counter()
        trace_id = uuid.uuid4().hex[:12]
        logger.info(
            "event=chat_turn_start trace_id=%s session_id=%s msg_len=%s save_history=%s force_notification_compiler=%s",
            trace_id,
            session_id,
            len(user_message or ""),
            bool(save_history),
            bool(force_notification_compiler),
        )
        logger.debug("event=chat_session_msg_len Chat | session=%s msg_len=%s",
                     session_id, len(user_message or ""))

        # ── Phase 1: INIT ─────────────────────────────────────────────────────
        yield stream_emitter.emit_status("📂 Recupero cronologia e routing...")
        t_init = time.perf_counter()
        history_text, available_domains, schemas = self._phase_init(
            session_id,
            trace_id=trace_id,
        )
        logger.debug(
            "event=chat_phase_timing_ms Chat phase timing | session=%s phase=init ms=%s domains=%s schemas_keys=%s",
            session_id,
            int((time.perf_counter() - t_init) * 1000),
            len(available_domains or []),
            len((schemas or {}).keys()) if isinstance(schemas, dict) else 0,
        )

        # ── Phase 2: CLASSIFY ─────────────────────────────────────────────────
        t_classify = time.perf_counter()
        intent = self._phase_classify(
            user_message, history_text, available_domains, schemas)
        logger.debug(
            "event=chat_phase_timing_ms Chat phase timing | session=%s phase=classify ms=%s mode=%s conf=%.2f",
            session_id,
            int((time.perf_counter() - t_classify) * 1000),
            intent.mode,
            intent.confidence,
        )
        logger.debug("event=classify_mode_domain_conf Classify | mode=%s domain=%s conf=%.2f",
                     intent.mode, intent.explicit_domain, intent.confidence)

        t_action_intent = time.perf_counter()
        action_intent = self._detect_action_intent(user_message, history_text)
        logger.debug(
            "event=chat_phase_timing_ms Chat phase timing | session=%s phase=action_intent_detect ms=%s action_intent=%s",
            session_id,
            int((time.perf_counter() - t_action_intent) * 1000),
            action_intent,
        )

        # ── Phase 3a: QUICK CHAT shortcut ─────────────────────────────────────
        if intent.mode == "quick_chat" and intent.confidence >= QUICK_CHAT_CONFIDENCE_THRESHOLD:
            yield stream_emitter.emit_status("💬 Conversazione rapida...")
            extra_context = ""
            if self._doc_rag.message_is_about_docs(user_message):
                extra_context = self._doc_rag.list_user_docs_brief(
                    chat_id=notify_target, session_id=session_id)
            answer = self._quick_answer(
                user_message, history_text, client_instructions, extra_context or None)
            if save_history:
                t_save_quick = time.perf_counter()
                self._save_history(session_id, user_message,
                                   answer, trace_id=trace_id)
                logger.debug(
                    "event=chat_phase_timing_ms Chat phase timing | session=%s phase=save_history_quick ms=%s",
                    session_id,
                    int((time.perf_counter() - t_save_quick) * 1000),
                )

            sync_signals, sync_attempted = self._sync_memory_if_needed(
                user_message=user_message,
                session_id=session_id,
                notify_target=notify_target,
                force_notification_compiler=force_notification_compiler,
            )
            if sync_attempted:
                if sync_signals:
                    for signal in sync_signals:
                        yield stream_emitter.emit_signal(
                            event=str(signal.get("event") or "memory.updated"),
                            message=str(signal.get("message")
                                        or "Aggiornamento memoria completato."),
                            data=signal.get("data") if isinstance(
                                signal.get("data"), dict) else {},
                        )
                else:
                    yield stream_emitter.emit_signal(
                        event="memory.noop",
                        message="Nessuna modifica persistita in memoria per questa richiesta.",
                        data={"reason": "no_persisted_mutation"},
                    )

            logger.info("event=quick_chat_done_ms Quick chat done in %sms", int(
                (time.perf_counter() - t0) * 1000))
            yield stream_emitter.emit_final(answer, "general")
            self._phase_background_memory(
                user_message,
                session_id,
                notify_target,
                force_notification_compiler,
                skip_memory_extract=sync_attempted,
                trace_id=trace_id,
            )
            return

        # ── Phase 3b: ACTION CHECK ────────────────────────────────────────────
        yield stream_emitter.emit_status("⚙️ Verifica azioni disponibili...")
        action_skip_reason = "not_evaluated"
        try:
            t_action_check = time.perf_counter()
            action_result, action_skip_reason = self._try_action_call(
                user_message,
                history_text,
                client_instructions,
                session_id,
                notify_target,
                trace_id=trace_id,
            )
            logger.debug(
                "event=chat_phase_timing_ms Chat phase timing | session=%s phase=action_check ms=%s action_hit=%s skip_reason=%s",
                session_id,
                int((time.perf_counter() - t_action_check) * 1000),
                bool(action_result),
                action_skip_reason,
            )
        except Exception as exc:
            logger.warning(
                "event=action_call_attempt_failed_non Action call attempt failed (non-fatal): %s", exc)
            action_result = None
            action_skip_reason = "exception"
        logger.info(
            "event=chat_action_precheck_result trace_id=%s session_id=%s action_hit=%s skip_reason=%s",
            trace_id,
            session_id,
            bool(action_result),
            action_skip_reason,
        )

        query_skip_reason = "not_attempted"
        if action_result is None:
            try:
                t_query_check = time.perf_counter()
                query_result, query_skip_reason = self._try_query_command_call(
                    user_message=user_message,
                    client_instructions=client_instructions,
                    session_id=session_id,
                    notify_target=notify_target,
                    trace_id=trace_id,
                )
                if query_result is not None:
                    action_result = query_result
                    action_skip_reason = f"query:{query_skip_reason}"
                logger.debug(
                    "event=chat_phase_timing_ms Chat phase timing | session=%s phase=query_check ms=%s query_hit=%s skip_reason=%s",
                    session_id,
                    int((time.perf_counter() - t_query_check) * 1000),
                    bool(query_result),
                    query_skip_reason,
                )
            except Exception as exc:
                logger.warning(
                    "event=query_command_call_attempt_failed_non Query command attempt failed (non-fatal): %s",
                    exc,
                )
                query_skip_reason = "exception"

        logger.info(
            "event=chat_precheck_final_result trace_id=%s session_id=%s precheck_hit=%s action_skip_reason=%s query_skip_reason=%s",
            trace_id,
            session_id,
            bool(action_result),
            action_skip_reason,
            query_skip_reason,
        )

        if action_result is not None:
            action_answer = str(action_result.get("text") or "").strip()
            approval_required = bool(action_result.get("approval_required"))
            if approval_required:
                approval_token = str(action_result.get(
                    "approval_token") or "").strip()
                title = str(action_result.get("title") or action_result.get(
                    "command") or "Azione").strip()
                method = str(action_result.get("method") or "POST").upper()
                target_count = int(action_result.get("target_count") or 1)

                yield stream_emitter.emit_signal(
                    event="action.approval.required",
                    message="Conferma richiesta prima dell'esecuzione di un'azione ad alto impatto.",
                    data={
                        "approval_token": approval_token,
                        "command": str(action_result.get("command") or ""),
                        "title": title,
                        "service": str(action_result.get("service") or ""),
                        "path": str(action_result.get("path") or ""),
                        "method": method,
                        "target_count": target_count,
                    },
                )

                if approval_token:
                    question_prompt = (
                        f"{title}\n"
                        f"Metodo: {method}\n"
                        f"Target coinvolti: {target_count}\n\n"
                        "Confermi l'esecuzione?"
                    )
                    yield self.ask_question(
                        session_id=session_id,
                        question_id=approval_token,
                        header="Conferma azione sensibile",
                        prompt=question_prompt,
                        kind="confirm",
                        options=["Conferma", "Annulla"],
                        timeout_sec=max(30, self._approval_ttl_seconds),
                        required=True,
                    )
            elif bool(action_result.get("executed")):
                yield stream_emitter.emit_signal(
                    event="action.executed",
                    message="Azione completata con successo.",
                    data={
                        "command": str(action_result.get("command") or ""),
                        "title": str(action_result.get("title") or ""),
                        "service": str(action_result.get("service") or ""),
                        "path": str(action_result.get("path") or ""),
                    },
                )
            else:
                yield stream_emitter.emit_signal(
                    event="action.failed",
                    message="Azione non completata.",
                    data={
                        "command": str(action_result.get("command") or ""),
                        "title": str(action_result.get("title") or ""),
                        "service": str(action_result.get("service") or ""),
                        "path": str(action_result.get("path") or ""),
                        "error": action_answer,
                    },
                )
            if save_history:
                t_save_action = time.perf_counter()
                self._save_history(
                    session_id,
                    user_message,
                    action_answer,
                    trace_id=trace_id,
                )
                logger.debug(
                    "event=chat_phase_timing_ms Chat phase timing | session=%s phase=save_history_action ms=%s",
                    session_id,
                    int((time.perf_counter() - t_save_action) * 1000),
                )

            sync_signals: list[dict] = []
            sync_attempted = False
            if not approval_required:
                sync_signals, sync_attempted = self._sync_memory_if_needed(
                    user_message=user_message,
                    session_id=session_id,
                    notify_target=notify_target,
                    force_notification_compiler=force_notification_compiler,
                )
                if sync_attempted:
                    if sync_signals:
                        for signal in sync_signals:
                            yield stream_emitter.emit_signal(
                                event=str(signal.get("event")
                                          or "memory.updated"),
                                message=str(signal.get("message")
                                            or "Aggiornamento memoria completato."),
                                data=signal.get("data") if isinstance(
                                    signal.get("data"), dict) else {},
                            )
                    else:
                        yield stream_emitter.emit_signal(
                            event="memory.noop",
                            message="Nessuna modifica persistita in memoria per questa richiesta.",
                            data={"reason": "no_persisted_mutation"},
                        )

            logger.info("event=action_call_done_ms Action call done in %sms", int(
                (time.perf_counter() - t0) * 1000))
            logger.info(
                "event=chat_turn_end trace_id=%s session_id=%s path=%s executed=%s approval_required=%s total_ms=%s",
                trace_id,
                session_id,
                "pre_action_approval_pending" if approval_required else "pre_action",
                bool(action_result.get("executed")),
                approval_required,
                int((time.perf_counter() - t0) * 1000),
            )
            yield stream_emitter.emit_final(action_answer, "action")
            self._phase_background_memory(
                user_message,
                session_id,
                notify_target,
                force_notification_compiler,
                skip_memory_extract=sync_attempted,
                trace_id=trace_id,
            )
            return

        if action_intent:
            logger.warning(
                "event=action_intent_without_execution_fallback_to_agent_loop Action intent detected but no pre-action executed; falling back to agent loop tools | session=%s reason=%s",
                session_id,
                action_skip_reason,
            )
            yield stream_emitter.emit_status(
                "⚙️ Azione non risolta nel pre-check, provo con loop agente multi-step..."
            )

        planner_contract, planner_variant, planner_template_key = prompt_config.prompt_with_variant(
            "planner_behavior_contract",
            surface="planner_behavior",
            seed=session_id,
        )
        logger.info(
            "event=prompt_variant_selected trace_id=%s session_id=%s surface=planner_behavior variant=%s template_key=%s",
            trace_id,
            session_id,
            planner_variant,
            planner_template_key,
        )

        athena_hints = self._select_relevant_athena_hints(
            session_id=session_id,
            valid_domains=intent.valid_domains,
            limit=3,
        )
        athena_hint_prompt_block = self._format_athena_hints_for_prompt(
            athena_hints)
        if athena_hints:
            logger.info(
                "event=athena_hints_selected trace_id=%s session_id=%s hints=%s domains=%s",
                trace_id,
                session_id,
                len(athena_hints),
                ",".join(intent.valid_domains or ["general"]),
            )
            yield stream_emitter.emit_status("🧭 Integro suggerimenti Athena...")

        # ── Phase 4: CONTEXT + GENERATE (agentic loop) ───────────────────────
        yield stream_emitter.emit_status(f"🧠 Analisi domini: {', '.join(intent.valid_domains)}...")
        yield stream_emitter.emit_status("🧾 Recupero preferenze attive...")

        t_prefs = time.perf_counter()
        all_prefs = self._load_preferences(intent.valid_domains)
        preference_facts = [str(p.get("fact", "")).strip()
                            for p in all_prefs if p.get("fact")]
        logger.debug(
            "event=chat_phase_timing_ms Chat phase timing | session=%s phase=load_preferences ms=%s prefs=%s",
            session_id,
            int((time.perf_counter() - t_prefs) * 1000),
            len(all_prefs),
        )

        # Build domain tools from module registry for this session
        t_tools = time.perf_counter()
        domain_tools = self._build_domain_tools(
            intent,
            session_id,
            notify_target,
            trace_id=trace_id,
        )
        logger.debug(
            "event=chat_phase_timing_ms Chat phase timing | session=%s phase=build_tools ms=%s tools=%s",
            session_id,
            int((time.perf_counter() - t_tools) * 1000),
            len(domain_tools),
        )

        if domain_tools:
            # Agentic loop: LLM decides which tools to call and when
            yield stream_emitter.emit_status("🔄 Ciclo agente in corso...")
            agent_loop_client_instructions = str(
                client_instructions or "").strip()
            if planner_contract:
                agent_loop_client_instructions = "\n\n".join(
                    part
                    for part in [planner_contract, agent_loop_client_instructions]
                    if part
                )
            if action_intent and self._agent_action_tool_policy:
                agent_loop_client_instructions = "\n\n".join(
                    part
                    for part in [self._agent_action_tool_policy,
                                 agent_loop_client_instructions]
                    if part
                )
            if athena_hint_prompt_block:
                agent_loop_client_instructions = "\n\n".join(
                    part
                    for part in [
                        f"ATHENA_ADVISORY_HINTS:\n{athena_hint_prompt_block}",
                        agent_loop_client_instructions,
                    ]
                    if part
                )
            logger.info(
                "event=chat_agent_loop_start trace_id=%s session_id=%s tools=%s action_intent=%s",
                trace_id,
                session_id,
                len(domain_tools),
                action_intent,
            )

            # Accumulate token strings for streaming to client
            streamed_tokens: list[str] = []

            def _stream_token_and_yield(token: str) -> None:
                streamed_tokens.append(token)

            # For the streaming path we yield token frames as they arrive
            # via a wrapper generator used only by run_agent_loop's final turn
            def _stream_final(prompt: str) -> Iterator[str]:
                for tok in self._agents.analyst.ask_stream(prompt):
                    yield tok

            t_agent_loop = time.perf_counter()
            answer, tokens = run_agent_loop(
                user_message=user_message,
                history_text=history_text,
                preference_facts=preference_facts,
                tools=domain_tools,
                ask_fn=self._ask_analyst,
                ask_tools_fn=self._ask_analyst_with_tools,
                stream_fn=_stream_final,
                client_instructions=agent_loop_client_instructions or None,
                conversation_style=conversation_style_contract(),
            )
            logger.debug(
                "event=chat_phase_timing_ms Chat phase timing | session=%s phase=agent_loop ms=%s tokens=%s answer_len=%s",
                session_id,
                int((time.perf_counter() - t_agent_loop) * 1000),
                len(tokens),
                len(answer or ""),
            )
            logger.info(
                "event=chat_agent_loop_result trace_id=%s session_id=%s tools=%s tokens=%s answer_len=%s",
                trace_id,
                session_id,
                len(domain_tools),
                len(tokens),
                len(answer or ""),
            )

            # Emit token frames from the final streaming turn
            for token in tokens:
                yield stream_emitter.emit_token(token)

        else:
            # Fallback: no domain tools — use pre-fetch approach (original flow)
            yield stream_emitter.emit_status("🔎 Recupero entità dai moduli/Archive...")
            yield stream_emitter.emit_status("🧱 Compattazione contesto...")
            t_context = time.perf_counter()
            no_action_contract = prompt_config.prompt(
                "no_action_execution_contract")
            analysis_prompt = self._phase_context(
                user_message,
                intent,
                client_instructions,
                notify_target,
                session_id,
                history_text,
                no_action_contract=no_action_contract,
                athena_hints=athena_hints,
                planner_contract=planner_contract,
            )
            logger.debug(
                "event=chat_phase_timing_ms Chat phase timing | session=%s phase=context_build ms=%s prompt_len=%s",
                session_id,
                int((time.perf_counter() - t_context) * 1000),
                len(analysis_prompt or ""),
            )
            yield stream_emitter.emit_status("🧠 Sintesi finale in corso...")
            t_stream = time.perf_counter()
            answer = yield from self._stream_analyst(analysis_prompt)
            logger.debug(
                "event=chat_phase_timing_ms Chat phase timing | session=%s phase=stream_analyst ms=%s answer_len=%s",
                session_id,
                int((time.perf_counter() - t_stream) * 1000),
                len(answer or ""),
            )

        # ── Phase 6: PERSIST ──────────────────────────────────────────────────
        if save_history:
            t_save = time.perf_counter()
            self._save_history(session_id, user_message,
                               answer, trace_id=trace_id)
            logger.debug(
                "event=chat_phase_timing_ms Chat phase timing | session=%s phase=save_history ms=%s",
                session_id,
                int((time.perf_counter() - t_save) * 1000),
            )
        logger.info("event=chat_done_session_total_ms Chat done | session=%s total=%sms", session_id,
                    int((time.perf_counter() - t0) * 1000))
        logger.info(
            "event=chat_turn_end trace_id=%s session_id=%s path=standard total_ms=%s domain=%s",
            trace_id,
            session_id,
            int((time.perf_counter() - t0) * 1000),
            intent.valid_domains[0] if intent.valid_domains else "general",
        )

        sync_signals, sync_attempted = self._sync_memory_if_needed(
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            force_notification_compiler=force_notification_compiler,
        )
        if sync_attempted:
            if sync_signals:
                for signal in sync_signals:
                    yield stream_emitter.emit_signal(
                        event=str(signal.get("event") or "memory.updated"),
                        message=str(signal.get("message")
                                    or "Aggiornamento memoria completato."),
                        data=signal.get("data") if isinstance(
                            signal.get("data"), dict) else {},
                    )
            else:
                yield stream_emitter.emit_signal(
                    event="memory.noop",
                    message="Nessuna modifica persistita in memoria per questa richiesta.",
                    data={"reason": "no_persisted_mutation"},
                )

        yield stream_emitter.emit_final(answer, intent.valid_domains[0] if intent.valid_domains else "general")
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
            analyst_model_name=self._agents.analyst_model_name,
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
        return self._ask_analyst(prompt)

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
        t0 = time.perf_counter()
        history_data = self._hub.get(
            f"/chat/history/{session_id}?limit={self._context_builder.max_history_messages}",
            timeout=self._policy_timeout("foreground_chat"),
            headers=self._trace_headers(session_id, trace_id),
        )
        t_history_ms = int((time.perf_counter() - t0) * 1000)

        now = time.time()
        history_text = self._context_builder.compact_history(history_data)

        domains_from_cache = False
        if now - self._domains_cache_ts <= self._domains_cache_ttl_seconds and self._domains_cache_value:
            available_domains = list(self._domains_cache_value)
            domains_from_cache = True
            t_domains_ms = 0
        else:
            t_domains = time.perf_counter()
            available_domains = self._hub.get(
                "/domains",
                timeout=self._policy_timeout("foreground_chat"),
                headers=self._trace_headers(session_id, trace_id),
            ) or ["general"]
            t_domains_ms = int((time.perf_counter() - t_domains) * 1000)
            self._domains_cache_value = list(available_domains)
            self._domains_cache_ts = now

        schemas_from_cache = False
        if now - self._schemas_cache_ts <= self._schemas_cache_ttl_seconds and isinstance(self._schemas_cache_value, dict):
            schemas = dict(self._schemas_cache_value)
            schemas_from_cache = True
            t_schemas_ms = 0
        else:
            t_schemas = time.perf_counter()
            schemas = self._hub.get(
                "/schemas",
                timeout=self._policy_timeout("foreground_chat"),
                headers=self._trace_headers(session_id, trace_id),
            ) or {}
            t_schemas_ms = int((time.perf_counter() - t_schemas) * 1000)
            self._schemas_cache_value = dict(
                schemas) if isinstance(schemas, dict) else {}
            self._schemas_cache_ts = now

        logger.debug(
            "event=chat_init_breakdown_ms Chat init breakdown | session=%s history_ms=%s domains_ms=%s schemas_ms=%s domains_cache_hit=%s schemas_cache_hit=%s",
            session_id,
            t_history_ms,
            t_domains_ms,
            t_schemas_ms,
            domains_from_cache,
            schemas_from_cache,
        )
        return history_text, available_domains, schemas

    def _phase_classify(
        self,
        user_message: str,
        history_text: str,
        available_domains: list,
        schemas: dict,
    ) -> SessionIntent:
        """Run router LLM to classify intent. Returns a SessionIntent."""
        mode, explicit_domain, confidence, valid_domains, filters, filters_gt, filters_lt, sort_by, sort_order = (
            self._classifier.classify(
                user_message, history_text, available_domains, schemas)
        )
        # Ensure explicit_domain is surfaced first in valid_domains
        if explicit_domain and explicit_domain not in valid_domains:
            valid_domains = [explicit_domain] + \
                [d for d in valid_domains if d != explicit_domain]
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
        def _run():
            t0 = time.perf_counter()
            # ── Memory extraction ──────────────────────────────────────────────
            if not skip_memory_extract:
                try:
                    t_mem = time.perf_counter()
                    self._memory_service.extract_and_save_preferences(
                        user_message, session_id,
                        notify_target=notify_target,
                        force_notification_compiler=force_notification_compiler,
                    )
                    logger.debug(
                        "event=background_phase_timing_ms Background phase timing | session=%s phase=memory_extract ms=%s",
                        session_id,
                        int((time.perf_counter() - t_mem) * 1000),
                    )
                except Exception as exc:
                    logger.warning(
                        "event=background_memory_sync_failed Background memory sync failed: %s", exc)
            else:
                logger.debug(
                    "event=background_memory_extract_skipped Background memory extraction skipped because sync persistence already ran | session=%s",
                    session_id,
                )

            # ── User controllability extraction (P1-9) ────────────────────────
            try:
                t_ctrl = time.perf_counter()
                self._control_service.extract_and_save_controls(user_message)
                logger.debug(
                    "event=background_phase_timing_ms Background phase timing | session=%s phase=controls_extract ms=%s",
                    session_id,
                    int((time.perf_counter() - t_ctrl) * 1000),
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
                if should_compact:
                    self._task_store.mark_running(
                        compaction_task_id,
                        progress=0.75,
                        metadata={"phase": "compaction"},
                    )
                    self._context_builder.run_background_compaction(
                        session_id=session_id,
                        history_data=history_data,
                        scribe_agent=self._agents.scribe,
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
                logger.debug(
                    "event=background_phase_timing_ms Background phase timing | session=%s phase=compaction_check ms=%s task_id=%s compacted=%s",
                    session_id,
                    int((time.perf_counter() - t_compaction) * 1000),
                    compaction_task_id,
                    bool(should_compact),
                )
            except Exception as exc:
                self._task_store.mark_failed(
                    compaction_task_id,
                    error={"message": str(exc), "phase": "compaction_check"},
                )
                logger.warning(
                    "event=background_compaction_check_failed Background compaction check failed: %s", exc)

            logger.debug(
                "event=background_phase_timing_ms Background phase timing | session=%s phase=total ms=%s",
                session_id,
                int((time.perf_counter() - t0) * 1000),
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
    ) -> list[ToolDefinition]:
        """Build ToolDefinitions for the agentic loop from registered module tools.

        Each domain in the intent gets a '{domain}.search' tool that calls the
        retrieval service. Document chunk search is added when relevant.
        Returns an empty list if no module tools are registered (falls back to
        the pre-fetch approach in the caller).
        """
        tools: list[ToolDefinition] = []
        rs = self._retrieval_service

        for domain in intent.valid_domains:
            # Capture domain in closure
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

        # Only return tools if domain module tools are actually registered
        if self._module_registry._needs_refresh():
            self._module_registry.refresh()

        # Add all Hub Action Commands to domain tools
        # This replaces _try_action_call, empowering the Agent Loop to fetch/delete/add seamlessly.
        all_commands = self._hub.get_commands() or []
        for cmd in all_commands:
            cmd_name = cmd.get("command")
            if not cmd_name:
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

    def _try_query_command_call(
        self,
        user_message: str,
        client_instructions: str | None,
        session_id: str,
        notify_target: str | None,
        trace_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Attempt to match and execute a read-only (GET) Hub command."""
        all_commands = self._hub.get_commands() or []
        query_commands = [
            command
            for command in all_commands
            if str(command.get("method") or "GET").upper() == "GET"
            and str(command.get("command") or "").strip()
            and str(command.get("service") or "").strip()
            and str(command.get("path") or "").strip()
        ]
        if not query_commands:
            return None, "no_query_commands"

        matched, score, reason, terms = _heuristic_select_action_command(
            user_message=user_message,
            action_commands=query_commands,
        )
        if not matched:
            return None, "query_selector_no_match"

        is_direct_match = reason in {
            "direct_slash_command",
            "direct_command_name",
        }
        if not is_direct_match and score < self._query_selector_heuristic_min_score:
            logger.debug(
                "event=query_selector_low_confidence session_id=%s score=%.2f min_score=%.2f reason=%s terms=%s",
                session_id,
                float(score or 0.0),
                self._query_selector_heuristic_min_score,
                reason,
                ",".join(terms or []),
            )
            return None, "query_selector_low_confidence"

        action_name = str(matched.get("command") or "").strip()
        required_args = _extract_arg_names_from_command(matched)
        base_params: dict[str, Any] = {}
        missing_required = [
            arg_name
            for arg_name in required_args
            if base_params.get(arg_name) in (None, "")
        ]
        if missing_required:
            logger.debug(
                "event=query_selector_missing_required_args session_id=%s command=%s missing=%s",
                session_id,
                action_name,
                missing_required,
            )
            return None, "query_missing_required_args"

        body = _resolve_template(
            matched.get("body_template") or {},
            base_params,
            session_id,
            notify_target,
        )
        query = _resolve_template(
            matched.get("query_template") or {},
            base_params,
            session_id,
            notify_target,
        )
        path = _resolve_template(
            str(matched.get("path") or "").strip(),
            base_params,
            session_id,
            notify_target,
        )

        if body and isinstance(body, dict):
            body = _strip_nones(body) or None
        if query and isinstance(query, dict):
            query = {key: value for key,
                     value in query.items() if value is not None}

        logger.info(
            "event=query_selector_decision session_id=%s command=%s score=%.2f reason=%s terms=%s",
            session_id,
            action_name,
            float(score or 0.0),
            reason,
            ",".join(terms or []),
        )

        ok, result = self._hub.route_to_service(
            service=str(matched.get("service") or ""),
            path=str(path or "").lstrip("/"),
            method="GET",
            body=body,
            query=query or {},
            timeout=self._policy_timeout("action_service_route"),
            headers=self._trace_headers(session_id, trace_id),
        )
        if not ok:
            logger.warning(
                "event=query_command_route_failed session_id=%s command=%s error=%s",
                session_id,
                action_name,
                result,
            )
            return {
                "executed": False,
                "command": action_name,
                "title": matched.get("title") or action_name,
                "service": matched.get("service") or "",
                "path": str(path or matched.get("path") or ""),
                "text": f"⚠️ Non sono riuscita a completare il comando '{action_name}'.",
            }, "query_service_route_failed"

        answer = self.format_payload(
            command=action_name,
            payload=result,
            response_prompt=str(matched.get("response_prompt") or ""),
            client_instructions=client_instructions,
            variant_seed=str(trace_id or session_id or action_name),
        )
        return {
            "executed": True,
            "command": action_name,
            "title": matched.get("title") or action_name,
            "service": matched.get("service") or "",
            "path": str(path or matched.get("path") or ""),
            "text": answer,
        }, "query_executed"

    def _try_action_call(
        self,
        user_message: str,
        history_text: str,
        client_instructions: str | None,
        session_id: str,
        notify_target: str | None,
        trace_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Attempt to match the user request to a Hub action command and execute it.

        Returns (result_dict_or_none, reason).

        Returns a result dict if a tool was selected, or None if no
        matching action was found (caller should fall through to domain query path).
        """
        from datetime import datetime

        t0 = time.perf_counter()

        def _select_picker_scope(command_name: str, options_count: int) -> str:
            """Choose whether to apply picker command to one or all source options."""
            if options_count <= 1:
                return "single"
            prompt = prompt_config.prompt(
                "arg_picker_scope_selector_template",
                command_name=command_name,
                options_count=options_count,
                user_message=user_message,
                history_text_or_none=history_text or "(nessuna)",
            )
            raw = ""
            try:
                raw = self._agents.scribe.ask(prompt)
            except Exception:
                try:
                    raw = self._agents.fallback_scribe.ask(prompt)
                except Exception:
                    return "single"

            try:
                parsed = json.loads(str(raw or "").strip())
                mode = str(parsed.get("scope") or "").strip().lower()
                return mode if mode in {"single", "all"} else "single"
            except Exception:
                return "single"

        def _fetch_arg_picker_values(command_meta: dict, arg_name: str, base_params: dict) -> list[str]:
            picker = command_meta.get("arg_picker") if isinstance(
                command_meta.get("arg_picker"), dict) else {}
            source = picker.get("source") if isinstance(
                picker.get("source"), dict) else {}
            picker_arg = str(picker.get("arg", "")).strip().lower()
            if not source or picker_arg != arg_name:
                return []

            source_service = str(source.get("service", "")).strip()
            source_method = str(source.get("method", "GET")).strip().upper()
            source_path = _resolve_template(
                str(source.get("path", "")).strip(),
                base_params,
                session_id,
                notify_target,
            )
            source_query = _resolve_template(
                source.get("query_template") if isinstance(
                    source.get("query_template"), dict) else {},
                base_params,
                session_id,
                notify_target,
            )
            source_body = _resolve_template(
                source.get("body_template") if isinstance(
                    source.get("body_template"), dict) else {},
                base_params,
                session_id,
                notify_target,
            )

            ok, payload = self._hub.route_to_service(
                service=source_service,
                path=str(source_path or "").lstrip("/"),
                method=source_method,
                body=source_body if isinstance(source_body, dict) else {},
                query=source_query if isinstance(source_query, dict) else {},
                timeout=self._policy_timeout("action_selection"),
                headers=self._trace_headers(session_id, trace_id),
            )

            logger.debug(
                "event=fetch_arg_picker_result Arg picker request result | arg=%s ok=%s payload_type=%s payload=%s",
                arg_name,
                ok,
                type(payload).__name__,
                payload,
            )

            if not ok or not isinstance(payload, list):
                logger.warning(
                    "event=fetch_arg_picker_failed Arg picker routing failed or invalid payload | arg=%s ok=%s payload=%s",
                    arg_name, ok, str(payload)[:200]
                )
                return []

            value_field = str(picker.get("value_field", arg_name)
                              ).strip() or arg_name
            values: list[str] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                value = str(row.get(value_field, "")).strip()
                if value:
                    values.append(value)

            logger.debug(
                "event=fetch_arg_picker_values_extracted Extracted arg picker values | arg=%s field=%s values=%s",
                arg_name, value_field, values
            )

            return values

        # Fetch action commands (state-changing methods only) from Hub discovery
        t_discovery = time.perf_counter()
        all_commands = self._hub.get_commands()
        logger.debug(
            "event=action_phase_timing_ms Action phase timing | phase=commands_discovery ms=%s commands=%s",
            int((time.perf_counter() - t_discovery) * 1000),
            len(all_commands or []),
        )
        action_commands = [
            c for c in all_commands
            if c.get("method", "GET").upper() in ("POST", "PUT", "PATCH", "DELETE")
        ]
        if not action_commands:
            return None, "no_non_interactive_action_commands"

        today_str = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

        # Build a compact tool schema for the LLM
        tool_schemas = []
        for cmd in action_commands:
            schema: dict = {
                "name": cmd["command"],
                "description": cmd.get("description", ""),
                "params": {},
            }
            args_schema = cmd.get("arguments_schema") or {}
            if args_schema:
                schema["params"] = {
                    k: {"desc": v.get("description", k),
                        "required": v.get("required", False),
                        "type": v.get("type", "string")}
                    for k, v in args_schema.items()
                }
            else:
                flat: set[str] = set()
                _collect_vars(cmd.get("body_template") or {}, flat)
                _collect_vars(cmd.get("query_template") or {}, flat)
                flat -= {"session_id", "chat_id", "owner"}
                if flat:
                    schema["params"] = {
                        v: {"desc": v, "required": True} for v in flat}
            tool_schemas.append(schema)

        tools_json = json.dumps(tool_schemas, ensure_ascii=False, indent=2)

        selection_prompt = prompt_config.prompt(
            "action_selector_template",
            today_str=today_str,
            history_text_or_none=history_text or "(nessuna)",
            user_message=user_message,
            tools_json=tools_json,
        )

        def _select_action_with_heuristics(trigger_reason: str) -> tuple[dict[str, Any] | None, str, float, list[str]]:
            candidate, score, reason, terms = _heuristic_select_action_command(
                user_message=user_message,
                action_commands=action_commands,
            )
            if not self._action_selector_heuristic_enabled:
                return None, trigger_reason, score, terms
            if candidate and score >= self._action_selector_heuristic_min_score:
                return candidate, f"heuristic:{trigger_reason}:{reason}", score, terms
            return None, trigger_reason, score, terms

        # Use the fast scribe for tool selection.
        raw = ""
        selection: dict[str, Any] = {}
        selection_source = "llm"
        selector_reason = ""
        t_select = time.perf_counter()
        try:
            raw = self._agents.scribe.ask(selection_prompt)
        except Exception as primary_exc:
            logger.warning(
                "event=tool_selection_primary_failed Tool selection primary model failed; trying fallback | error=%s",
                primary_exc,
            )
            try:
                raw = self._agents.fallback_scribe.ask(selection_prompt)
            except Exception as fallback_exc:
                logger.warning(
                    "event=tool_selection_llm_failed Tool selection LLM failed on primary+fallback | primary_error=%s fallback_error=%s",
                    primary_exc,
                    fallback_exc,
                )
                selector_reason = "selector_llm_failed"
        logger.debug(
            "event=action_phase_timing_ms Action phase timing | phase=selector_llm ms=%s",
            int((time.perf_counter() - t_select) * 1000),
        )

        # Parse the JSON response from selector model when available.
        if raw:
            try:
                raw_stripped = raw.strip()
                if raw_stripped.startswith("```"):
                    raw_stripped = re.sub(
                        r"^```[a-z]*\n?", "", raw_stripped, flags=re.MULTILINE)
                    raw_stripped = raw_stripped.rstrip("`").strip()
                selection = json.loads(raw_stripped)
            except Exception as exc:
                logger.warning(
                    "event=tool_selection_json_parse_failed Tool selection JSON parse failed | error=%s raw_preview=%s",
                    exc,
                    raw[:300],
                )
                selector_reason = "selector_json_parse_failed"

        action_name = ""
        if isinstance(selection, dict):
            action_name = str(selection.get("action") or "").strip()
        if not action_name and not selector_reason:
            selector_reason = "selector_action_null"

        matched = next(
            (c for c in action_commands if c["command"] == action_name), None)
        if action_name and not matched:
            logger.warning(
                "event=tool_selected_not_found_in_commands Tool selected command not found in catalog | cmd=%s",
                action_name,
            )
            selector_reason = "selector_action_not_found"

        if not matched:
            fallback_cmd, fallback_source, fallback_score, fallback_terms = _select_action_with_heuristics(
                selector_reason or "selector_action_null"
            )
            if not fallback_cmd:
                logger.info(
                    "event=action_selector_no_match session_id=%s reason=%s heuristic_enabled=%s heuristic_score=%.2f heuristic_terms=%s",
                    session_id,
                    selector_reason or "selector_action_null",
                    self._action_selector_heuristic_enabled,
                    float(fallback_score or 0.0),
                    ",".join(fallback_terms or []),
                )
                return None, (selector_reason or "selector_action_null")

            matched = fallback_cmd
            action_name = str(matched.get("command") or "").strip()
            selection = {"action": action_name, "params": {}}
            selection_source = fallback_source
            logger.warning(
                "event=action_selector_heuristic_selected session_id=%s trigger=%s command=%s score=%.2f terms=%s",
                session_id,
                selector_reason or "selector_action_null",
                action_name,
                float(fallback_score or 0.0),
                ",".join(fallback_terms or []),
            )

        logger.info(
            "event=action_selector_decision session_id=%s source=%s command=%s",
            session_id,
            selection_source,
            action_name,
        )

        user_params = selection.get("params") or {}
        args_schema = matched.get("arguments_schema") or {}
        normalized_params = _coerce_param_types(user_params, args_schema)
        logger.info(
            "event=action_selector_params_resolved session_id=%s command=%s params_keys=%s",
            session_id,
            action_name,
            ",".join(sorted(normalized_params.keys())),
        )

        if normalized_params != user_params:
            logger.debug(
                "event=tool_call_params_normalized Tool call params normalized | cmd=%s raw=%s normalized=%s",
                action_name,
                user_params,
                normalized_params,
            )

        required_args = _extract_arg_names_from_command(matched)

        # Validate args against their pickers if a value was hallucinated
        for arg in required_args:
            picker = matched.get("arg_picker") if isinstance(
                matched.get("arg_picker"), dict) else {}
            if picker and str(picker.get("arg", "")).strip().lower() == arg:
                valid_values = _fetch_arg_picker_values(
                    matched, arg, normalized_params)
                current_val = normalized_params.get(arg)
                if current_val and current_val not in valid_values:
                    logger.warning(
                        "event=tool_call_invalid_picker_value Invalid picker value provided by LLM (hallucination) | arg=%s value=%s valid_count=%s. Clearing it.",
                        arg, current_val, len(valid_values)
                    )
                    # Force it to be missing so picker resolution runs
                    normalized_params[arg] = None

        missing_required = [
            arg for arg in required_args
            if normalized_params.get(arg) in (None, "")
        ]

        param_sets: list[dict] = [dict(normalized_params)]
        if missing_required:
            resolved = False
            for missing_arg in missing_required:
                picker_values = _fetch_arg_picker_values(
                    matched, missing_arg, normalized_params)
                if not picker_values:
                    continue

                scope = _select_picker_scope(action_name, len(picker_values))
                if scope == "all":
                    param_sets = []
                    for val in picker_values:
                        p = dict(normalized_params)
                        p[missing_arg] = val
                        param_sets.append(p)
                else:
                    p = dict(normalized_params)
                    p[missing_arg] = picker_values[0]
                    param_sets = [p]
                resolved = True
            if not resolved:
                logger.warning(
                    "event=missing_required_args_unresolved Missing required args could not be resolved | cmd=%s missing=%s normalized=%s",
                    action_name,
                    missing_required,
                    normalized_params,
                )
                return None, "missing_required_args_unresolved"

        if self._requires_high_impact_approval(matched, action_name, param_sets):
            token = self._queue_high_impact_approval(
                matched=matched,
                action_name=action_name,
                title=str(matched.get("title") or action_name),
                param_sets=param_sets,
                session_id=session_id,
                notify_target=notify_target,
                trace_id=trace_id,
                client_instructions=client_instructions,
            )
            target_count = len(param_sets)
            method = str(matched.get("method", "POST")).upper()
            title = str(matched.get("title") or action_name)
            logger.info(
                "event=high_impact_approval_queued token=%s command=%s method=%s targets=%s session_id=%s",
                token,
                action_name,
                method,
                target_count,
                session_id,
            )
            return {
                "executed": False,
                "approval_required": True,
                "approval_token": token,
                "command": action_name,
                "title": title,
                "service": matched.get("service") or "",
                "path": str(matched.get("path") or ""),
                "target_count": target_count,
                "method": method,
                "params_preview": param_sets[:3],
                "text": f"Serve conferma esplicita per eseguire l'azione ad alto impatto: {title} ({method}) su {target_count} target.",
            }, "approval_required"

        t_execute = time.perf_counter()
        result = self._execute_selected_action(
            matched=matched,
            action_name=action_name,
            param_sets=param_sets,
            session_id=session_id,
            notify_target=notify_target,
            trace_id=trace_id,
            client_instructions=client_instructions,
        )
        logger.debug(
            "event=action_phase_timing_ms Action phase timing | phase=execute_action ms=%s executed=%s",
            int((time.perf_counter() - t_execute) * 1000),
            bool(result.get("executed")),
        )
        logger.debug(
            "event=action_phase_timing_ms Action phase timing | phase=total ms=%s action=%s",
            int((time.perf_counter() - t0) * 1000),
            action_name,
        )
        return result, ("executed" if bool(result.get("executed")) else "service_route_failed")

    def _detect_action_intent(self, user_message: str, history_text: str) -> bool:
        """Detect whether the user is explicitly requesting a state-changing action."""
        heuristic_guess = _heuristic_action_intent(user_message)
        try:
            prompt = prompt_config.prompt(
                "action_intent_detector_template",
                user_message=user_message,
                history_text_or_none=history_text or "(nessuna)",
            )
            raw = self._agents.scribe.ask(prompt)
        except Exception as primary_exc:
            logger.warning(
                "event=action_intent_detector_primary_failed Action intent detector primary model failed; trying fallback | error=%s",
                primary_exc,
            )
            try:
                prompt = prompt_config.prompt(
                    "action_intent_detector_template",
                    user_message=user_message,
                    history_text_or_none=history_text or "(nessuna)",
                )
                raw = self._agents.fallback_scribe.ask(prompt)
            except Exception as fallback_exc:
                logger.warning(
                    "event=action_intent_detector_failed_non Action intent detector failed on primary+fallback; using heuristic | primary_error=%s fallback_error=%s heuristic=%s",
                    primary_exc,
                    fallback_exc,
                    heuristic_guess,
                )
                return heuristic_guess

        try:
            raw_stripped = str(raw or "").strip()
            if raw_stripped.startswith("```"):
                raw_stripped = re.sub(
                    r"^```[a-z]*\n?", "", raw_stripped, flags=re.MULTILINE)
                raw_stripped = raw_stripped.rstrip("`").strip()
            parsed = json.loads(raw_stripped)
            llm_guess = bool(parsed.get("action_intent"))
            final_guess = llm_guess or heuristic_guess
            logger.info(
                "event=action_intent_detector_result llm=%s heuristic=%s final=%s",
                llm_guess,
                heuristic_guess,
                final_guess,
            )
            return final_guess
        except Exception as exc:
            logger.warning(
                "event=action_intent_detector_parse_failed_non Action intent detector parse failed; using heuristic | error=%s raw_preview=%s heuristic=%s",
                exc,
                str(raw)[:300],
                heuristic_guess,
            )
            return heuristic_guess

    def _embed(self, text: str) -> list[float]:
        """Embed *text*, falling back to the secondary embedder on failure."""
        for agent in (self._agents.embedder, self._agents.fallback_embedder):
            try:
                vector = agent.embed(text)
                if vector:
                    return vector
            except Exception:
                pass
        return []

    def _ask_analyst(self, prompt: str) -> str:
        """Ask the primary analyst, falling back to secondary on error."""
        try:
            return self._agents.analyst.ask(prompt)
        except Exception as exc:
            logger.warning(
                "event=primary_analyst_failed_using_fallback Primary analyst failed, using fallback: %s", exc)
        try:
            return self._agents.fallback_analyst.ask(prompt)
        except Exception as exc:
            logger.error(
                "event=fallback_analyst_also_failed Fallback analyst also failed: %s", exc)
            return "⚠️ In questo momento i modelli sono temporaneamente non disponibili. Riprova tra poco."

    def _ask_analyst_with_tools(self, prompt: str, tools_manifest: list[dict]) -> dict:
        """Ask analyst with provider-native tool-calling when available."""
        try:
            return self._agents.analyst.ask_with_tools(prompt, tools_manifest)
        except Exception as exc:
            logger.warning(
                "event=primary_analyst_tool_call_failed_using_fallback Primary analyst tool call failed, using fallback: %s", exc)
        try:
            return self._agents.fallback_analyst.ask_with_tools(prompt, tools_manifest)
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
            for token in self._agents.analyst.ask_stream(prompt):
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
            for token in self._agents.fallback_analyst.ask_stream(prompt):
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
        # For quick chat, prefer the fast fallback analyst (Gemini Flash) over the heavy local model
        try:
            return self._agents.fallback_analyst.ask(prompt)
        except Exception:
            return self._ask_analyst(prompt)

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
