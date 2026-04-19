"""MemoryService — preference and subscription extraction orchestrator.

Single responsibility: coordinate intent detection, LLM-driven parsing, and
Archive persistence for user preferences and alert subscriptions.

All text-analysis helpers live in *memory_intent*; all LLM-output parsers
live in *memory_parsers*.  This class only owns I/O and orchestration.
"""
from __future__ import annotations

import json
import logging

import requests
from urllib.parse import urlparse, parse_qs

from core.services.memory_intent import (
    has_notification_intent,
    has_preference_intent,
    has_deprecate_intent,
)
from core.services.memory_parsers import (
    parse_preference_actions,
    parse_subscription_actions,
)

logger = logging.getLogger(__name__)

_PREF_PROMPT_TEMPLATE = """
You are Hestia's enterprise Memory Manager.

TASK:
Infer enduring user preferences, constraints, and profile facts from natural language context.
Do not rely on explicit trigger phrases. Infer intent semantically.

CURRENT PREFS: {pref_context}
KNOWN DOMAINS: {domains}
USER MESSAGE: "{user_message}"

CONVERSATION CONTEXT:
{history_text}

RULES:
1. Ignore temporary requests and conversational noise (e.g., "ciao", "grazie", "ok").
2. Add only durable preferences likely useful in future interactions.
3. NEVER emit DEPRECATE unless user explicitly requests removal with clear keywords like: "cancella", "rimuovi", "elimina", "dimentica", "reset", "togli".
4. Even if a message seems to contradict a preference, preserve the old value unless removal is explicit.
5. Use known domains; fallback to "general" when uncertain.
6. When uncertain, output NONE rather than guessing.

ACTION SCHEMA:
- ADD: {{"action":"ADD","fact":"<durable fact>","domain":"<known_domain_or_general>"}}
- DEPRECATE: {{"action":"DEPRECATE","id":<existing_pref_id>}}

Output ONLY JSON array or NONE.
"""

_SUB_PROMPT_TEMPLATE = """
You are Hestia's subscription compiler.

Given user message and context, create subscriptions ONLY when user intent is explicit and direct.
If the user is only chatting, sharing preferences, or discussing hobbies/plans without asking alerts, output NONE.

KNOWN DOMAINS: {domains}
USER MESSAGE: "{user_message}"
CONTEXT:
{history_text}

Return ONLY JSON array with items:
{{
    "action": "ADD",
  "domain": "<known_domain_or_general>",
  "event_type": "entity.upserted",
  "filters": {{"city": "...", "max_price": 350000}},
  "channels": [{{"type": "telegram", "target": "<id>"}}]
}}

For removals/disabling, use:
{{"action":"DEPRECATE","subscription_id":"<existing_subscription_id>"}}

If user changes criteria, prefer ADD with updated filters (same deterministic subscription_id logic will upsert).

STRICT RULE:
- Do not create subscriptions unless user clearly asks for alerts/notifications.

Output NONE when not needed.
"""

_SUB_FORCED_SUFFIX = """

FORCED MODE:
- The current request explicitly asks to create/update a notification workflow.
- Do not output NONE unless absolutely impossible due to missing mandatory details.
- If details are partially missing, infer safe defaults and still produce one ADD action.
"""


class MemoryService:
    """Coordinate user-preference and alert-subscription lifecycle.

    Parameters
    ----------
    archive_url:
        Direct URL to Hestia-Archive (unused for routing; kept for compatibility).
    hub_api_url:
        Hestia-Hub base URL. All Archive requests are routed via Hub.
    scribe_agent:
        Primary LLM agent with an ``ask(prompt) -> str`` interface.
    fallback_scribe_agent:
        Fallback LLM agent used when *scribe_agent* raises.
    context_builder:
        Object exposing ``max_history_messages``, ``max_history_chars``, and
        ``truncate(text, max_chars) -> str``.
    """

    def __init__(
        self,
        archive_url: str,
        hub_api_url: str,
        scribe_agent,
        fallback_scribe_agent,
        context_builder,
    ) -> None:
        self.archive_url = archive_url
        self.hub_api_url = hub_api_url.rstrip("/")
        self.scribe = scribe_agent
        self.fallback_scribe = fallback_scribe_agent
        self.context_builder = context_builder

    # ── Private HTTP helpers ──────────────────────────────────────────────────

    def _route_archive(self, method: str, endpoint: str, body=None, query: dict | None = None, timeout: int = 6):
        """Route an HTTP request to Archive via Hub's routing envelope."""
        normalized = f"api{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/archive/{normalized}",
                json={
                    "method": method.upper(),
                    "query": query or {},
                    "headers": {},
                    "body": body,
                    "timeout_seconds": timeout,
                },
                timeout=timeout + 2,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json() or {}
            if int(payload.get("status_code", 500)) < 400:
                return payload.get("payload")
            return None
        except Exception as exc:
            logger.debug("[MemoryService] _route_archive %s %s failed: %s", method, endpoint, exc)
            return None

    def _api_get(self, endpoint: str, default_val=None):
        """GET an Archive endpoint and return its payload or *default_val*."""
        parsed = urlparse(endpoint)
        path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"
        query = {
            k: v[0] if len(v) == 1 else v
            for k, v in parse_qs(parsed.query).items()
        }
        result = self._route_archive("GET", path, query=query)
        if result is None:
            return default_val if default_val is not None else []
        return result

    # ── LLM interaction helpers ───────────────────────────────────────────────

    def _ask(self, prompt: str) -> str:
        """Query primary scribe; fall back to fallback_scribe on any exception."""
        try:
            return self.scribe.ask(prompt).strip()
        except Exception:
            try:
                return self.fallback_scribe.ask(prompt).strip()
            except Exception:
                return "NONE"

    # ── Preference extraction ─────────────────────────────────────────────────

    def _build_conversation_context(self, session_id: str) -> tuple[list[dict], list[str], str]:
        """Fetch and return (active_prefs, domains, history_text) from Archive."""
        prefs: list[dict] = self._api_get("/memory/active") or []
        domains: list[str] = self._api_get("/domains", ["general"]) or ["general"]
        if "general" not in domains:
            domains.append("general")

        history_data = self._api_get(
            f"/chat/history/{session_id}?limit={self.context_builder.max_history_messages}"
        )
        history_text = ""
        if history_data:
            history_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Hestia'}: "
                f"{self.context_builder.truncate(m['content'], self.context_builder.max_history_chars)}"
                for m in reversed(history_data)
            )
        return prefs, domains, history_text

    def _save_preferences(self, actions: list[dict], prefs_by_id: dict[int, dict]) -> list[dict]:
        """Persist validated preference actions; return emitted signals."""
        signals: list[dict] = []
        for action in actions:
            if action.get("action") == "ADD" and action.get("fact"):
                created = self._route_archive(
                    "POST", "/memory",
                    body={"fact": action["fact"], "domain": action.get("domain", "general"), "weight": 1.0},
                )
                if created is not None:
                    signals.append({
                        "event": "memory.preference.added",
                        "message": f"Preferenza salvata: {action['fact']}",
                        "data": {"domain": action.get("domain", "general"), "fact": action["fact"]},
                    })

            elif action.get("action") == "DEPRECATE" and action.get("id") is not None:
                pref_id = action["id"]
                removed_pref = prefs_by_id.get(int(pref_id)) or {}
                removed_fact = str(removed_pref.get("fact", "")).strip()
                removed_domain = str(removed_pref.get("domain", "general")).strip() or "general"
                updated = self._route_archive("PATCH", f"/memory/{pref_id}", body={"is_active": False})
                if updated is not None:
                    message_text = f"Preferenza rimossa: {removed_fact}" if removed_fact else "Preferenza rimossa."
                    signals.append({
                        "event": "memory.preference.removed",
                        "message": message_text,
                        "data": {"id": pref_id, "domain": removed_domain, "fact": removed_fact},
                    })
        return signals

    def _save_subscriptions(
        self,
        subscriptions: list[dict],
        existing_map: dict[str, dict],
        session_id: str,
    ) -> list[dict]:
        """Persist validated subscription actions; return emitted signals."""
        signals: list[dict] = []

        def _normalize_signature(payload: dict) -> str:
            sig = {
                "domain": payload.get("domain"),
                "event_type": payload.get("event_type"),
                "filters": payload.get("filters") or {},
                "channels": payload.get("channels") or [],
                "is_active": bool(payload.get("is_active", True)),
            }
            return json.dumps(sig, sort_keys=True, ensure_ascii=False)

        for sub in subscriptions:
            action = str(sub.get("action", "UPSERT")).strip().upper()

            if action == "DEPRECATE":
                sub_id = str(sub.get("subscription_id", "")).strip()
                existing = existing_map.get(sub_id)
                if not sub_id or not existing:
                    continue
                disabled_payload = {
                    **existing,
                    "subscription_id": sub_id,
                    "owner": existing.get("owner", session_id),
                    "is_active": False,
                }
                updated = self._route_archive("POST", "/subscriptions", body=disabled_payload)
                if updated is not None:
                    signals.append({
                        "event": "subscription.removed",
                        "message": "Notifiche automatiche disattivate.",
                        "data": {
                            "subscription_id": sub_id,
                            "domain": disabled_payload.get("domain"),
                            "filters": disabled_payload.get("filters") or {},
                            "channels": disabled_payload.get("channels") or [],
                        },
                    })
                continue

            sub_payload = {
                "subscription_id": sub.get("subscription_id"),
                "owner": sub.get("owner", session_id),
                "domain": sub.get("domain", "general"),
                "event_type": sub.get("event_type", "entity.upserted"),
                "filters": sub.get("filters") or {},
                "channels": sub.get("channels") or [],
                "is_active": bool(sub.get("is_active", True)),
            }
            sub_id = str(sub_payload.get("subscription_id", "")).strip()
            if not sub_id:
                continue

            previous = existing_map.get(sub_id)
            result = self._route_archive("POST", "/subscriptions", body=sub_payload)
            if result is None:
                continue

            if not previous:
                signals.append({
                    "event": "subscription.added",
                    "message": "Notifica automatica attivata.",
                    "data": {
                        "subscription_id": sub_id,
                        "domain": sub_payload.get("domain"),
                        "event_type": sub_payload.get("event_type"),
                        "filters": sub_payload.get("filters") or {},
                        "channels": sub_payload.get("channels") or [],
                    },
                })
                existing_map[sub_id] = sub_payload
            elif _normalize_signature(previous) != _normalize_signature(sub_payload):
                signals.append({
                    "event": "subscription.changed",
                    "message": "Regole notifica aggiornate.",
                    "data": {
                        "subscription_id": sub_id,
                        "domain": sub_payload.get("domain"),
                        "event_type": sub_payload.get("event_type"),
                        "filters": sub_payload.get("filters") or {},
                        "channels": sub_payload.get("channels") or [],
                    },
                })
                existing_map[sub_id] = sub_payload

        return signals

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_and_save_preferences(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        force_notification_compiler: bool = False,
    ) -> list[dict]:
        """Extract and persist user preferences and/or alert subscriptions.

        Runs LLM-driven extraction only when intent signals are detected (or forced).

        Parameters
        ----------
        user_message:
            The raw user message to analyse.
        session_id:
            Current conversation/session identifier, used as subscription owner.
        notify_target:
            Telegram chat-id or other delivery target for new subscriptions.
        force_notification_compiler:
            When True, subscription extraction runs regardless of intent signals.

        Returns
        -------
        list[dict]
            Emitted memory/subscription signals (e.g. ``{"event": "memory.preference.added", ...}``).
        """
        signals: list[dict] = []
        should_extract_prefs = has_preference_intent(user_message)
        should_extract_subs = force_notification_compiler or has_notification_intent(user_message)

        if not should_extract_prefs and not should_extract_subs:
            return signals

        prefs, domains, history_text = self._build_conversation_context(session_id)
        prefs_by_id: dict[int, dict] = {
            int(p["id"]): p for p in prefs if p.get("id") is not None
        }
        pref_context = (
            "\n".join(f"ID: {p['id']} | Fact: {p['fact']}" for p in prefs)
            if prefs else "Nessuna."
        )

        if should_extract_prefs:
            allow_deprecate = has_deprecate_intent(user_message)
            pref_prompt = _PREF_PROMPT_TEMPLATE.format(
                pref_context=pref_context,
                domains=", ".join(domains),
                user_message=user_message,
                history_text=history_text,
            )
            raw_pref = self._ask(pref_prompt)
            pref_actions = parse_preference_actions(
                raw_pref, domains, prefs, user_message, allow_deprecate=allow_deprecate
            )
            try:
                signals.extend(self._save_preferences(pref_actions, prefs_by_id))
            except Exception as exc:
                logger.warning("[MemoryService] save preferences failed: %s", exc)

        if not should_extract_subs:
            return signals

        sub_prompt = _SUB_PROMPT_TEMPLATE.format(
            domains=", ".join(domains),
            user_message=user_message,
            history_text=history_text,
        )
        if force_notification_compiler:
            sub_prompt += _SUB_FORCED_SUFFIX

        raw_sub = self._ask(sub_prompt)
        fallback_target = (notify_target or "").strip() or session_id
        subscriptions = parse_subscription_actions(
            raw_sub, domains, owner=session_id, default_target=fallback_target
        )

        if not subscriptions:
            return signals

        existing_subs = self._api_get(f"/subscriptions/active?owner={session_id}", default_val=[]) or []
        existing_map: dict[str, dict] = {
            str(s["subscription_id"]): s
            for s in existing_subs
            if s.get("subscription_id")
        }

        try:
            signals.extend(self._save_subscriptions(subscriptions, existing_map, session_id))
        except Exception as exc:
            logger.warning("[MemoryService] save subscriptions failed: %s", exc)

        return signals
