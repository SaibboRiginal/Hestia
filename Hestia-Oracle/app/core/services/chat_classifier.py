"""Chat mode classifier — determines routing intent from a user message.

Single responsibility: decide whether a message is a quick conversational
exchange ("quick_chat") or a data retrieval / action request ("domain_query"),
and extract structured routing parameters including action intent.

Open/Closed: change the classification prompt or tune thresholds here
without touching the main chat orchestrator.
"""
import json
import logging

logger = logging.getLogger(f"hestia_oracle.{__name__}")

_DEFAULT_MODE = "domain_query"
_CONFIDENCE_THRESHOLD = 0.55  # Minimum confidence to accept quick_chat classification


class ChatClassifier:
    """Classifies a user message and returns routing parameters including action intent."""

    def __init__(self, router_agent, fallback_router_agent) -> None:
        self._router = router_agent
        self._fallback = fallback_router_agent

    def classify(
        self,
        user_message: str,
        history_text: str,
        available_domains: list[str],
        schemas: dict | None = None,
        current_datetime_context: str | None = None,
    ) -> tuple[str, str | None, float, list[str], dict, dict, dict, str | None, str, bool]:
        """Classify *user_message* and return routing parameters.

        Returns:
            mode: "quick_chat" or "domain_query"
            domain: explicit domain string or None
            confidence: 0.0–1.0
            valid_domains: list of valid domain strings
            filters: exact-match filter dict
            filters_gt: numeric greater-than filter dict
            filters_lt: numeric less-than filter dict
            sort_by: field name or None
            sort_order: "asc" or "desc"
            action_intent: True if the user is explicitly requesting a
                           state-changing action (create, update, delete, etc.)
        """
        prompt = self._build_prompt(
            user_message, history_text, available_domains, schemas, current_datetime_context)
        defaults = self._defaults()

        try:
            raw = self._router.ask(prompt).strip()
        except Exception:
            try:
                raw = self._fallback.ask(prompt).strip()
            except Exception:
                return defaults

        return self._parse(raw, available_domains, defaults)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _defaults() -> tuple:
        return (
            _DEFAULT_MODE, None, 0.0, ["general"],
            {}, {}, {}, None, "desc", False,
        )

    @staticmethod
    def _build_prompt(
        user_message: str,
        history_text: str,
        available_domains: list[str],
        schemas: dict | None,
        current_datetime_context: str | None = None,
    ) -> str:
        domain_candidates = [
            d.strip().lower()
            for d in (available_domains or [])
            if d.strip().lower() and d.strip().lower() != "general"
        ]
        datetime_block = (
            f"CURRENT_DATETIME_CONTEXT:\n{str(current_datetime_context or '').strip()}\n\n"
            if str(current_datetime_context or "").strip()
            else ""
        )
        return (
            "You classify and route user intent for a chat orchestrator.\n\n"
            "Return ONLY valid JSON with:\n"
            '1) "mode": "quick_chat" or "domain_query"\n'
            '2) "domain": one domain from AVAILABLE_DOMAINS or null\n'
            '3) "confidence": float 0..1\n'
            '4) "domains": array of routed domains (or ["general"]) for domain_query\n'
            '5) "filters": exact-match filters object\n'
            '6) "filters_gt": numeric greater-than filters object\n'
            '7) "filters_lt": numeric less-than filters object\n'
            '8) "sort_by": field name or null\n'
            '9) "sort_order": "asc" or "desc"\n'
            '10) "action_intent": true if the message explicitly requests a state-changing '
            "action (create, update, delete, enable, disable, set, remove, execute), "
            "false for informational queries, chat, or read-only requests\n\n"
            "Rules:\n"
            '- Use "quick_chat" for normal conversation, generic Q&A, short personal exchanges, '
            "or messages that do not need structured retrieval or actions.\n"
            '- Use "domain_query" when the user asks for domain records, '
            "filters, listings, alerts/subscriptions, data-driven operations, "
            "OR explicitly requests a state-changing action.\n"
            "- Set \"domain\" only if it is explicit/high-confidence from AVAILABLE_DOMAINS; otherwise null.\n\n"
            "- Resolve relative time references (oggi, domani, next week) using CURRENT_DATETIME_CONTEXT when available.\n"
            '- Set "action_intent": true for imperative action requests (commands like /xxx, '
            "or natural language like 'crea', 'aggiungi', 'modifica', 'elimina', 'imposta', "
            "'esegui', 'disattiva'). Use semantic intent, not keyword spotting.\n\n"
            f"AVAILABLE_DOMAINS: {', '.join(domain_candidates) or 'none'}\n\n"
            f"{datetime_block}"
            f"CONTEXT DATA STRUCTURES:\n{json.dumps(schemas or {}, ensure_ascii=False, indent=2)}\n\n"
            f"CONTEXT:\n{history_text}\n\n"
            f"USER_MESSAGE: {user_message}\n"
        )

    @staticmethod
    def _parse(
        raw: str,
        available_domains: list[str],
        defaults: tuple,
    ) -> tuple:
        (
            default_mode, _, _, _, default_filters,
            default_filters_gt, default_filters_lt, _, default_sort_order, _,
        ) = defaults

        domain_candidates = [d.strip().lower()
                             for d in (available_domains or [])]

        try:
            s, e = raw.find("{"), raw.rfind("}")
            if s == -1 or e == -1:
                return defaults
            data = json.loads(raw[s: e + 1])
        except Exception:
            return defaults

        try:
            mode = str(data.get("mode", default_mode)).strip().lower()
            if mode not in {"quick_chat", "domain_query"}:
                mode = default_mode

            raw_domain = data.get("domain")
            domain = str(raw_domain).strip().lower() if raw_domain else None
            if domain and domain not in domain_candidates:
                domain = None

            confidence = max(
                0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0)))

            selected = [str(d).lower()
                        for d in (data.get("domains") or []) if str(d).strip()]
            if domain and domain not in selected:
                selected.insert(0, domain)
            valid_domains = [
                d for d in selected if d in available_domains or d == "general"
            ] or ["general"]

            filters = data.get("filters") if isinstance(
                data.get("filters"), dict) else {}
            filters_gt = data.get("filters_gt") if isinstance(
                data.get("filters_gt"), dict) else {}
            filters_lt = data.get("filters_lt") if isinstance(
                data.get("filters_lt"), dict) else {}
            sort_by = data.get("sort_by")
            sort_order = "asc" if str(
                data.get("sort_order", "desc")).lower() == "asc" else "desc"

            action_intent = bool(data.get("action_intent"))

            return mode, domain, confidence, valid_domains, filters, filters_gt, filters_lt, sort_by, sort_order, action_intent
        except Exception:
            return defaults


# Module-level confidence threshold export for oracle_engine
QUICK_CHAT_CONFIDENCE_THRESHOLD = _CONFIDENCE_THRESHOLD
