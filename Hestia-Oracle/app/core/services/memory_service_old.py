import json
import os
import hashlib
import requests
from urllib.parse import urlparse, parse_qs
import re


class MemoryService:
    def __init__(self, archive_url: str, hub_api_url: str, scribe_agent, fallback_scribe_agent, context_builder):
        self.archive_url = archive_url
        self.hub_api_url = hub_api_url.rstrip("/")
        self.scribe = scribe_agent
        self.fallback_scribe = fallback_scribe_agent
        self.context_builder = context_builder

    def _has_explicit_notification_intent(self, user_message: str) -> bool:
        message = str(user_message or "").strip().lower()
        if not message:
            return False

        intent_keywords = [
            "avvisami",
            "notifica",
            "notifiche",
            "alert",
            "fammi sapere",
            "voglio essere avvisato",
            "voglio essere avvisata",
            "mandami",
            "inviami",
            "attiva notifica",
            "attiva notifiche",
            "seguimi",
            "monitor",
            "monitorare",
        ]
        return any(keyword in message for keyword in intent_keywords)

    def _has_explicit_preference_intent(self, user_message: str) -> bool:
        message = str(user_message or "").strip().lower()
        if not message:
            return False

        preference_keywords = [
            "preferisco",
            "mi piace",
            "non mi piace",
            "vorrei",
            "voglio",
            "cerco",
            "evita",
            "evitare",
            "odio",
            "amo",
            "interessa",
            "budget",
            "zona",
            "stanze",
            "metri",
            "prefer",
            "i like",
            "i don't like",
            "i want",
            "looking for",
            "avoid",
        ]
        return any(keyword in message for keyword in preference_keywords)

    def _is_fact_grounded_in_user_message(self, fact: str, user_message: str) -> bool:
        fact_text = str(fact or "").strip().lower().replace("_", " ")
        user_text = str(user_message or "").strip().lower()
        if not fact_text or not user_text:
            return False

        synthetic_fragments = [
            "hermes",
            "oracle",
            "assistant",
            "hestia",
            "telegram",
        ]
        for fragment in synthetic_fragments:
            if fragment in fact_text and fragment not in user_text:
                return False

        fact_tokens = {token for token in re.findall(
            r"[a-zA-Z0-9à-öø-ÿ]+", fact_text) if len(token) >= 4}
        user_tokens = {token for token in re.findall(
            r"[a-zA-Z0-9à-öø-ÿ]+", user_text) if len(token) >= 4}
        if not fact_tokens or not user_tokens:
            return False
        return len(fact_tokens.intersection(user_tokens)) > 0

    def _route_archive(self, method: str, endpoint: str, body=None, query=None, timeout: int = 6):
        normalized = f"api{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        response = requests.post(
            f"{self.hub_api_url}/route/archive/{normalized}",
            json={
                "method": method.upper(),
                "headers": {},
                "query": query or {},
                "body": body,
                "timeout_seconds": timeout,
            },
            timeout=timeout + 1,
        )
        if response.status_code != 200:
            return None
        routed = response.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            return None
        return routed.get("payload")

    def _api_get(self, endpoint: str, default_val=None):
        try:
            parsed = urlparse(endpoint)
            endpoint_path = parsed.path if parsed.path.startswith(
                "/") else f"/{parsed.path}"
            query = {k: v[0] if len(v) == 1 else v for k,
                     v in parse_qs(parsed.query).items()}
            payload = self._route_archive("GET", endpoint_path, query=query)
            if payload is not None:
                return payload
            return default_val if default_val is not None else []
        except Exception:
            return default_val if default_val is not None else []

    def parse_actions(self, raw_output: str, domains: list[str], active_prefs: list[dict], user_message: str = "") -> list[dict]:
        if not raw_output:
            return []

        if "NONE" in raw_output.upper() and '"ADD"' not in raw_output.upper() and '"DEPRECATE"' not in raw_output.upper():
            return []

        # Defensive guard: only allow DEPRECATE if user message contains explicit removal keywords
        user_lower = (user_message or "").lower()
        deprecate_keywords = ["cancella", "rimuovi", "elimina", "dimentica",
                              "reset", "togli", "delete", "remove", "forget", "clear"]
        allow_deprecate = any(
            keyword in user_lower for keyword in deprecate_keywords)

        start_idx = raw_output.find("[")
        end_idx = raw_output.rfind("]")
        if start_idx == -1 or end_idx == -1:
            return []

        try:
            parsed = json.loads(raw_output[start_idx: end_idx + 1])
        except Exception:
            return []

        if not isinstance(parsed, list):
            return []

        allowed_domains = {str(d).strip().lower()
                           for d in domains if str(d).strip()}
        allowed_domains.add("general")
        existing_ids = {int(p.get("id"))
                        for p in active_prefs if p.get("id") is not None}
        existing_facts = {str(p.get("fact", "")).strip().lower()
                          for p in active_prefs if p.get("fact")}

        validated_actions = []
        seen_keys = set()

        for item in parsed:
            if not isinstance(item, dict):
                continue

            action = str(item.get("action", "")).strip().upper()
            if action not in {"ADD", "DEPRECATE"}:
                continue

            if action == "ADD":
                fact = str(item.get("fact", "")).strip()
                if len(fact) < 8:
                    continue
                if not self._is_fact_grounded_in_user_message(fact, user_message):
                    continue
                fact_key = fact.lower()
                if fact_key in existing_facts:
                    continue

                domain = str(item.get("domain", "general")
                             ).strip().lower() or "general"
                if domain not in allowed_domains:
                    domain = "general"

                dedupe_key = ("ADD", fact_key, domain)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                validated_actions.append(
                    {"action": "ADD", "fact": fact, "domain": domain})
                continue

            # Block DEPRECATE unless user explicitly requested removal
            if action == "DEPRECATE" and not allow_deprecate:
                continue

            pref_id = item.get("id")
            if pref_id is None:
                continue

            try:
                pref_id = int(pref_id)
            except Exception:
                continue

            if pref_id not in existing_ids:
                continue

            dedupe_key = ("DEPRECATE", pref_id)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            validated_actions.append({"action": "DEPRECATE", "id": pref_id})

        return validated_actions

    def parse_subscription_actions(self, raw_output: str, domains: list[str], owner: str, default_target: str) -> list[dict]:
        if not raw_output:
            return []

        if "NONE" in raw_output.upper() and "[" not in raw_output:
            return []

        start_idx = raw_output.find("[")
        end_idx = raw_output.rfind("]")
        if start_idx == -1 or end_idx == -1:
            return []

        try:
            parsed = json.loads(raw_output[start_idx: end_idx + 1])
        except Exception:
            return []

        if not isinstance(parsed, list):
            return []

        allowed_domains = {str(d).strip().lower()
                           for d in domains if str(d).strip()}
        allowed_domains.add("general")

        fallback_target = default_target or os.getenv(
            "ORACLE_NOTIFY_DEFAULT_TARGET", owner)
        validated = []
        seen = set()
        allowed_event_types = {"entity.upserted"}
        force_telegram_target = os.getenv(
            "ORACLE_FORCE_TELEGRAM_TARGET", "1").strip().lower() not in {"0", "false", "no"}

        for item in parsed:
            if not isinstance(item, dict):
                continue

            action = str(item.get("action", "ADD")).strip().upper()
            if action == "DEPRECATE":
                subscription_id = str(
                    item.get("subscription_id", item.get("id", ""))).strip()
                if not subscription_id:
                    continue
                dedupe_key = ("DEPRECATE", subscription_id)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                validated.append(
                    {
                        "action": "DEPRECATE",
                        "subscription_id": subscription_id,
                        "owner": owner,
                    }
                )
                continue

            domain = str(item.get("domain", "general")).strip().lower()
            if domain not in allowed_domains:
                domain = "general"

            event_type = str(
                item.get("event_type", "entity.upserted")).strip().lower()
            if not event_type or event_type not in allowed_event_types:
                event_type = "entity.upserted"

            filters = item.get("filters") if isinstance(
                item.get("filters"), dict) else {}
            channels = item.get("channels") if isinstance(
                item.get("channels"), list) else []
            if not channels:
                channels = [{"type": "telegram", "target": fallback_target}]

            normalized_channels = []
            for channel in channels:
                if not isinstance(channel, dict):
                    continue
                channel_type = str(
                    channel.get("type", "telegram")).strip().lower()
                if channel_type != "telegram":
                    channel_type = "telegram"

                channel_target = str(channel.get(
                    "target", fallback_target)).strip()
                if force_telegram_target or not channel_target:
                    channel_target = fallback_target

                if not channel_target:
                    continue
                normalized_channels.append(
                    {"type": channel_type, "target": channel_target})

            if not normalized_channels:
                continue

            dedupe_payload = json.dumps(
                {
                    "owner": owner,
                    "domain": domain,
                    "event_type": event_type,
                    "filters": filters,
                    "channels": normalized_channels,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            subscription_id = hashlib.sha1(
                dedupe_payload.encode("utf-8")).hexdigest()
            dedupe_key = (subscription_id,)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            validated.append(
                {
                    "action": "UPSERT",
                    "subscription_id": subscription_id,
                    "owner": owner,
                    "domain": domain,
                    "event_type": event_type,
                    "filters": filters,
                    "channels": normalized_channels,
                    "is_active": True,
                }
            )

        return validated

    def extract_and_save_preferences(self, user_message: str, session_id: str, notify_target: str | None = None, force_notification_compiler: bool = False):
        signals: list[dict] = []
        should_extract_preferences = self._has_explicit_preference_intent(
            user_message)
        should_extract_notifications = force_notification_compiler or self._has_explicit_notification_intent(
            user_message)

        if not should_extract_preferences and not should_extract_notifications:
            return signals

        prefs = self._api_get("/memory/active")
        prefs_by_id = {
            int(item.get("id")): item
            for item in (prefs or [])
            if item.get("id") is not None
        }
        pref_context = "\n".join(
            [f"ID: {p['id']} | Fact: {p['fact']}" for p in prefs]) if prefs else "Nessuna."

        domains = self._api_get("/domains", ["general"])
        if "general" not in domains:
            domains.append("general")

        history_data = self._api_get(
            f"/chat/history/{session_id}?limit={self.context_builder.max_history_messages}")
        history_text = ""
        if history_data:
            history_text = "\n".join(
                [
                    f"{'User' if m['role'] == 'user' else 'Hestia'}: {self.context_builder.truncate(m['content'], self.context_builder.max_history_chars)}"
                    for m in reversed(history_data)
                ]
            )

        prompt = f"""
You are Hestia's enterprise Memory Manager.

TASK:
Infer enduring user preferences, constraints, and profile facts from natural language context.
Do not rely on explicit trigger phrases. Infer intent semantically.

CURRENT PREFS: {pref_context}
KNOWN DOMAINS: {', '.join(domains)}
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

        if should_extract_preferences:
            try:
                result = self.scribe.ask(prompt).strip()
            except Exception:
                try:
                    result = self.fallback_scribe.ask(prompt).strip()
                except Exception:
                    result = "NONE"

            model_actions = self.parse_actions(
                result, domains, prefs, user_message)
            if model_actions:
                try:
                    for action in model_actions:
                        if action.get("action") == "ADD" and action.get("fact"):
                            created = self._route_archive(
                                "POST",
                                "/memory",
                                body={
                                    "fact": action.get("fact"),
                                    "domain": action.get("domain", "general"),
                                    "weight": 1.0,
                                },
                            )
                            if created is not None:
                                signals.append(
                                    {
                                        "event": "memory.preference.added",
                                        "message": f"Preferenza salvata: {action.get('fact')}",
                                        "data": {
                                            "domain": action.get("domain", "general"),
                                            "fact": action.get("fact"),
                                        },
                                    }
                                )

                        elif action.get("action") == "DEPRECATE" and action.get("id"):
                            removed_pref = prefs_by_id.get(
                                int(action.get("id")))
                            removed_fact = str(
                                (removed_pref or {}).get("fact", "")).strip()
                            removed_domain = str((removed_pref or {}).get(
                                "domain", "general")).strip() or "general"
                            updated = self._route_archive(
                                "PATCH",
                                f"/memory/{action.get('id')}",
                                body={"is_active": False},
                            )
                            if updated is not None:
                                message_text = "Preferenza rimossa."
                                if removed_fact:
                                    message_text = f"Preferenza rimossa: {removed_fact}"
                                signals.append(
                                    {
                                        "event": "memory.preference.removed",
                                        "message": message_text,
                                        "data": {
                                            "id": action.get("id"),
                                            "domain": removed_domain,
                                            "fact": removed_fact,
                                        },
                                    }
                                )
                except Exception:
                    pass

        if not should_extract_notifications:
            return signals

        subscription_prompt = f"""
You are Hestia's subscription compiler.

    Given user message and context, create subscriptions ONLY when user intent is explicit and direct.
    If the user is only chatting, sharing preferences, or discussing hobbies/plans without asking alerts, output NONE.

KNOWN DOMAINS: {', '.join(domains)}
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

        if force_notification_compiler:
            subscription_prompt += """

FORCED MODE:
- The current request explicitly asks to create/update a notification workflow.
- Do not output NONE unless absolutely impossible due to missing mandatory details.
- If details are partially missing, infer safe defaults and still produce one ADD action.
"""

        try:
            sub_raw = self.scribe.ask(subscription_prompt).strip()
        except Exception:
            try:
                sub_raw = self.fallback_scribe.ask(subscription_prompt).strip()
            except Exception:
                sub_raw = "NONE"

        subscriptions = self.parse_subscription_actions(
            raw_output=sub_raw,
            domains=domains,
            owner=session_id,
            default_target=(notify_target or "").strip() or session_id,
        )

        if not subscriptions:
            return signals

        existing_subscriptions = self._api_get(
            f"/subscriptions/active?owner={session_id}", default_val=[]
        )
        existing_map = {
            str(item.get("subscription_id")): item
            for item in (existing_subscriptions or [])
            if item.get("subscription_id")
        }

        def normalize_signature(payload: dict) -> str:
            signature = {
                "domain": payload.get("domain"),
                "event_type": payload.get("event_type"),
                "filters": payload.get("filters") or {},
                "channels": payload.get("channels") or [],
                "is_active": bool(payload.get("is_active", True)),
            }
            return json.dumps(signature, sort_keys=True, ensure_ascii=False)

        try:
            for sub in subscriptions:
                action = str(sub.get("action", "UPSERT")).strip().upper()

                if action == "DEPRECATE":
                    sub_id = str(sub.get("subscription_id", "")).strip()
                    if not sub_id:
                        continue
                    existing = existing_map.get(sub_id)
                    if not existing:
                        continue

                    disabled_payload = {
                        "subscription_id": sub_id,
                        "owner": existing.get("owner", session_id),
                        "domain": existing.get("domain", "general"),
                        "event_type": existing.get("event_type", "entity.upserted"),
                        "filters": existing.get("filters") or {},
                        "channels": existing.get("channels") or [],
                        "is_active": False,
                    }
                    updated = self._route_archive(
                        "POST",
                        "/subscriptions",
                        body=disabled_payload,
                    )
                    if updated is not None:
                        signals.append(
                            {
                                "event": "subscription.removed",
                                "message": "Notifiche automatiche disattivate.",
                                "data": {
                                    "subscription_id": sub_id,
                                    "domain": disabled_payload.get("domain"),
                                    "filters": disabled_payload.get("filters") or {},
                                    "channels": disabled_payload.get("channels") or [],
                                },
                            }
                        )
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
                created_or_updated = self._route_archive(
                    "POST",
                    "/subscriptions",
                    body=sub_payload,
                )
                if created_or_updated is None:
                    continue

                if not previous:
                    signals.append(
                        {
                            "event": "subscription.added",
                            "message": "Notifica automatica attivata.",
                            "data": {
                                "subscription_id": sub_id,
                                "domain": sub_payload.get("domain"),
                                "event_type": sub_payload.get("event_type"),
                                "filters": sub_payload.get("filters") or {},
                                "channels": sub_payload.get("channels") or [],
                            },
                        }
                    )
                    existing_map[sub_id] = sub_payload
                    continue

                prev_signature = normalize_signature(previous)
                next_signature = normalize_signature(sub_payload)
                if prev_signature != next_signature:
                    signals.append(
                        {
                            "event": "subscription.changed",
                            "message": "Regole notifica aggiornate.",
                            "data": {
                                "subscription_id": sub_id,
                                "domain": sub_payload.get("domain"),
                                "event_type": sub_payload.get("event_type"),
                                "filters": sub_payload.get("filters") or {},
                                "channels": sub_payload.get("channels") or [],
                            },
                        }
                    )
                    existing_map[sub_id] = sub_payload
        except Exception:
            pass

        return signals
