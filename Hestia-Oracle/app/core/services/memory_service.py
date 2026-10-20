"""MemoryService — preference and subscription extraction orchestrator.

Single responsibility: coordinate intent detection, LLM-driven parsing, and
Archive persistence for user preferences and alert subscriptions.

All text-analysis helpers live in *memory_intent*; all LLM-output parsers
live in *memory_parsers*.  This class only owns I/O and orchestration.
"""
from __future__ import annotations

import json
import logging
import time

import requests
from urllib.parse import urlparse, parse_qs

from core.services.memory_intent import (
    has_notification_intent,
    has_deprecate_intent,
    is_memory_worthy,
)
from core.services.memory_parsers import (
    parse_preference_actions,
    parse_subscription_actions,
)
from core.services import prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── Memory taxonomy classes (P1-8) ──────────────────────────────────────────
# Keep these classes distinct in storage and retrieval to avoid state mixing.
MEMORY_CLASS_CONVERSATION = "conversational_history"
MEMORY_CLASS_PREFERENCE = "durable_user_preference"
MEMORY_CLASS_TASK = "task_goal_state"
MEMORY_CLASS_DOMAIN_FACT = "domain_fact_entity"
MEMORY_CLASS_COMMITMENT = "assistant_commitment"

# ── Notes from external AIs (docs/work/2026-10-20-memory-note) ───────────────
NOTE_MAX_FACTS = 10
NOTE_MAX_CHARS = 300
RECALL_MAX = 20


def fact_key(text: str) -> str:
    """Comparison key: lower case, letters and digits only."""
    return " ".join("".join(c if c.isalnum() else " " for c in str(text or "").lower()).split())


class MemoryService:
    """Coordinate user-preference and alert-subscription lifecycle.

    Parameters
    ----------
    archive_url:
        Direct URL to Hestia-Archive (unused for routing; kept for compatibility).
    hub_api_url:
        Hestia-Hub base URL. All Archive requests are routed via Hub.
    scribe_agent:
        LLM agent with an ``ask(prompt) -> str`` interface (a use case chain: fallback is in the chain).
    context_builder:
        Object exposing ``max_history_messages``, ``max_history_chars``, and
        ``truncate(text, max_chars) -> str``.
    pref_domain_classifier:
        Optional PreferenceDomainClassifier for embedding-based domain assignment.
        When provided, ``save_memory`` auto-assigns domains via cosine similarity
        instead of trusting the LLM-supplied domain.
    """

    def __init__(
        self,
        archive_url: str,
        hub_api_url: str,
        scribe_agent,
        context_builder,
        pref_domain_classifier=None,
    ) -> None:
        self.archive_url = archive_url
        self.hub_api_url = hub_api_url.rstrip("/")
        self.scribe = scribe_agent
        self.context_builder = context_builder
        self.pref_domain_classifier = pref_domain_classifier

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
                logger.warning("[🔄] event=memoryservice_hub_non200 method=%s endpoint=%s status=%s",
                               method, endpoint, resp.status_code)
                return None
            payload = resp.json() or {}
            if int(payload.get("status_code", 500)) < 400:
                return payload.get("payload")
            # Silent failure is forbidden (rule 7): memory writes were dropped unseen.
            logger.warning("[🔄] event=memoryservice_archive_rejected method=%s endpoint=%s status=%s detail=%s",
                           method, endpoint, payload.get("status_code"), str(payload.get("payload"))[:200])
            return None
        except Exception as exc:
            logger.warning(
                "[🔄] event=memoryservice_failed method=%s endpoint=%s error=%s", method, endpoint, exc)
            return None

    def _api_get(self, endpoint: str, default_val=None):
        """GET an Archive endpoint and return its payload or *default_val*."""
        parsed = urlparse(endpoint)
        path = parsed.path if parsed.path.startswith(
            "/") else f"/{parsed.path}"
        query = {
            k: v[0] if len(v) == 1 else v
            for k, v in parse_qs(parsed.query).items()
        }
        result = self._route_archive("GET", path, query=query)
        if result is None:
            return default_val if default_val is not None else []
        return result

    def _get_active_memory(self, domain: str | None = None, memory_class: str | None = None) -> list[dict]:
        """Load active memory rows with optional class/domain filters.

        Compatibility note:
        Archive may not yet enforce/filter on memory_class. We still send it,
        then defensively post-filter client-side when possible.
        """
        query_parts = []
        if domain:
            query_parts.append(f"domain={domain}")
        if memory_class:
            query_parts.append(f"memory_class={memory_class}")
        query = "&".join(query_parts)
        endpoint = "/memory/active" + (f"?{query}" if query else "")
        rows = self._api_get(endpoint, default_val=[]) or []
        if not isinstance(rows, list):
            return []

        if memory_class:
            # If Archive ignores unknown query params, keep backward-compat by
            # accepting untyped rows too (legacy data), but prefer typed rows.
            typed = [r for r in rows if str(
                r.get("memory_class", "")).strip() == memory_class]
            if typed:
                return typed
        return rows

    def _save_memory_fact(self, fact: str, domain: str, memory_class: str, extra_fields: dict | None = None) -> bool:
        """Persist a typed memory fact row."""
        payload = {
            "fact": fact,
            "domain": domain,
            "weight": 1.0,
            "memory_class": memory_class,
        }
        if extra_fields:
            payload.update(extra_fields)
        created = self._route_archive("POST", "/memory", body=payload)
        return created is not None

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
        """Best-effort write of a compact typed interaction record."""
        body = {
            "session_id": session_id,
            "actor": actor,
            "event_type": event_type,
            "domain": domain,
            "source_service": "oracle",
            "reference_id": reference_id,
            "payload": payload or {},
        }
        self._route_archive("POST", "/interaction-ledger", body=body)

    # ── LLM interaction helpers ───────────────────────────────────────────────

    def _ask(self, prompt: str) -> str:
        """Query the scribe (its chain already falls back); "NONE" when every step failed."""
        try:
            return self.scribe.ask(prompt).strip()
        except Exception:
            return "NONE"

    # ── Preference extraction ─────────────────────────────────────────────────

    def _build_conversation_context(self, session_id: str) -> tuple[list[dict], list[str], str]:
        """Fetch and return (active_prefs, domains, history_text) from Archive."""
        prefs: list[dict] = self._get_active_memory(
            memory_class=MEMORY_CLASS_PREFERENCE) or []
        domains: list[str] = self._api_get(
            "/domains", ["general"]) or ["general"]
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
                saved = self._save_memory_fact(
                    fact=action["fact"],
                    domain=action.get("domain", "general"),
                    memory_class=MEMORY_CLASS_PREFERENCE,
                )
                if saved:
                    signals.append({
                        "event": "memory.preference.added",
                        "message": f"Preferenza salvata: {action['fact']}",
                        "data": {"domain": action.get("domain", "general"), "fact": action["fact"]},
                    })

            elif action.get("action") == "DEPRECATE" and action.get("id") is not None:
                pref_id = action["id"]
                removed_pref = prefs_by_id.get(int(pref_id)) or {}
                removed_fact = str(removed_pref.get("fact", "")).strip()
                removed_domain = str(removed_pref.get(
                    "domain", "general")).strip() or "general"
                updated = self._route_archive(
                    "PATCH", f"/memory/{pref_id}", body={"is_active": False})
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
                updated = self._route_archive(
                    "POST", "/subscriptions", body=disabled_payload)
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
                    self._append_interaction_ledger(
                        event_type="assistant_commitment_completed",
                        session_id=session_id,
                        actor="assistant",
                        domain=str(disabled_payload.get(
                            "domain", "general")) or "general",
                        reference_id=sub_id,
                        payload={
                            "subscription_id": sub_id,
                            "event_type": disabled_payload.get("event_type"),
                            "filters": disabled_payload.get("filters") or {},
                            "reason": "subscription_deactivated",
                        },
                    )
                    # Track assistant-side commitment lifecycle in a dedicated class.
                    self._save_memory_fact(
                        fact=f"[COMMITMENT] subscription removed: {sub_id}",
                        domain=str(disabled_payload.get(
                            "domain", "general")) or "general",
                        memory_class=MEMORY_CLASS_COMMITMENT,
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
            result = self._route_archive(
                "POST", "/subscriptions", body=sub_payload)
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
                self._append_interaction_ledger(
                    event_type="assistant_commitment_created",
                    session_id=session_id,
                    actor="assistant",
                    domain=str(sub_payload.get(
                        "domain", "general")) or "general",
                    reference_id=sub_id,
                    payload={
                        "subscription_id": sub_id,
                        "event_type": sub_payload.get("event_type"),
                        "filters": sub_payload.get("filters") or {},
                        "channels": sub_payload.get("channels") or [],
                    },
                )
                self._save_memory_fact(
                    fact=f"[COMMITMENT] active subscription {sub_id} ({sub_payload.get('event_type')})",
                    domain=str(sub_payload.get(
                        "domain", "general")) or "general",
                    memory_class=MEMORY_CLASS_COMMITMENT,
                )
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
                self._append_interaction_ledger(
                    event_type="assistant_commitment_created",
                    session_id=session_id,
                    actor="assistant",
                    domain=str(sub_payload.get(
                        "domain", "general")) or "general",
                    reference_id=sub_id,
                    payload={
                        "subscription_id": sub_id,
                        "event_type": sub_payload.get("event_type"),
                        "filters": sub_payload.get("filters") or {},
                        "channels": sub_payload.get("channels") or [],
                        "reason": "subscription_updated",
                    },
                )
                self._save_memory_fact(
                    fact=f"[COMMITMENT] subscription updated: {sub_id}",
                    domain=str(sub_payload.get(
                        "domain", "general")) or "general",
                    memory_class=MEMORY_CLASS_COMMITMENT,
                )

        return signals

    # ── Agent-loop tool handlers (public, callable from ToolDefinition) ───────

    def save_memory(self, fact: str, domain: str = "general") -> tuple[bool, str]:
        """Save a durable memory fact. Usable as an agent loop tool handler.

        When *pref_domain_classifier* is configured, the LLM-supplied *domain*
        is ignored — domains are assigned via embedding cosine similarity
        against fixed domain descriptions (multi-domain, 0→N matches).

        Returns (ok, message).
        """
        clean_fact = str(fact or "").strip()
        if not clean_fact:
            return (False, "Cannot save empty memory fact.")

        # ── Auto-classify domains via embedding (bypass LLM) ──────────────
        if self.pref_domain_classifier is not None:
            try:
                assigned_domains = self.pref_domain_classifier.classify(
                    clean_fact)
            except Exception as exc:
                logger.warning(
                    "event=pref_domain_classify_failed fact_preview=%s error=%s",
                    clean_fact[:100], exc,
                )
                assigned_domains = ["general"]
            primary_domain = assigned_domains[0] if assigned_domains else "general"
        else:
            clean_domain = str(domain or "general").strip() or "general"
            assigned_domains = [clean_domain]
            primary_domain = clean_domain

        try:
            saved = self._save_memory_fact(
                fact=clean_fact,
                domain=primary_domain,
                memory_class=MEMORY_CLASS_PREFERENCE,
                extra_fields={"domains": assigned_domains, "extra_data": {"source": "chat"}},
            )
            if saved:
                logger.info(
                    "event=memory_tool_saved primary_domain=%s domains=%s fact_preview=%s",
                    primary_domain, assigned_domains, clean_fact[:120],
                )
                return (True, f"Memory saved [{', '.join(assigned_domains)}]: {clean_fact}")
            return (False, "Failed to persist memory fact.")
        except Exception as exc:
            logger.warning(
                "event=memory_tool_save_failed error=%s", exc)
            return (False, f"Memory save error: {exc}")

    def search_memories(self, query: str) -> tuple[bool, list[dict]]:
        """Search active user memories by keyword. Usable as an agent loop tool handler.

        Returns (ok, list_of_memory_dicts).
        """
        clean_query = str(query or "").strip().lower()
        try:
            all_memories = self._get_active_memory(
                memory_class=MEMORY_CLASS_PREFERENCE) or []
            if not clean_query:
                return (True, all_memories[:20])

            # Simple relevance: keyword overlap on fact text
            scored: list[tuple[int, dict]] = []
            for mem in all_memories:
                if not isinstance(mem, dict):
                    continue
                fact_text = str(mem.get("fact", "")).strip().lower()
                if not fact_text:
                    continue
                score = sum(
                    1 for word in clean_query.split()
                    if word in fact_text
                )
                if score > 0:
                    scored.append((score, mem))

            scored.sort(key=lambda item: item[0], reverse=True)
            results = [mem for _, mem in scored[:15]]
            logger.info(
                "event=memory_tool_search query=%s results=%s",
                clean_query,
                len(results),
            )
            return (True, results)
        except Exception as exc:
            logger.warning(
                "event=memory_tool_search_failed error=%s", exc)
            return (False, f"Memory search error: {exc}")

    # ── Notes from external AIs (memory_note / memory_recall) ───────────────

    def _classify(self, fact: str) -> list[str]:
        if self.pref_domain_classifier is None:
            return ["general"]
        try:
            return self.pref_domain_classifier.classify(fact) or ["general"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=memory_note_classify_failed error=%s", exc)
            return ["general"]

    def save_note(self, facts, topic: str = "", access: str = "") -> tuple[bool, dict | str]:
        """Save the durable facts an external AI distilled from a conversation (no LLM call).

        *facts*: list of sentences or one string with a fact per line. Duplicates of an active memory
        (same words, case/punctuation ignored) are skipped. Returns (ok, {saved, skipped}) or (False, reason)."""
        items = facts if isinstance(facts, list) else str(facts or "").splitlines()
        clean: list[str] = []
        for item in items:
            text = " ".join(str(item or "").split()).lstrip("-•* ").strip()
            if text and text not in clean:
                clean.append(text)
        if not clean:
            return (False, "No facts to save.")
        if len(clean) > NOTE_MAX_FACTS:
            return (False, f"Too many facts: max {NOTE_MAX_FACTS} per note.")
        too_long = [f for f in clean if len(f) > NOTE_MAX_CHARS]
        if too_long:
            return (False, f"Each fact must be at most {NOTE_MAX_CHARS} characters.")

        existing = {fact_key(str(m.get("fact") or "")): m for m in
                    self._get_active_memory(memory_class=MEMORY_CLASS_PREFERENCE) or [] if isinstance(m, dict)}
        access = str(access or "").strip()
        origin = {"source": "external" if access else "chat", "access": access,
                  "topic": str(topic or "").strip()[:120],
                  "noted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        saved, skipped = [], []
        for fact in clean:
            same = existing.get(fact_key(fact))
            if same is not None:
                skipped.append({"fact": fact, "existing_id": same.get("id")})
                continue
            domains = self._classify(fact)
            ok = self._save_memory_fact(fact=fact, domain=domains[0], memory_class=MEMORY_CLASS_PREFERENCE,
                                        extra_fields={"domains": domains, "extra_data": origin})
            if not ok:
                return (False, f"Archive did not save the note (saved so far: {len(saved)}).")
            saved.append({"fact": fact, "domains": domains})
            existing[fact_key(fact)] = {"id": None, "fact": fact}
        logger.info("event=memory_note_saved access=%s saved=%d skipped=%d",
                    origin["access"], len(saved), len(skipped))
        return (True, {"saved": saved, "skipped": skipped})

    def recall(self, query: str = "") -> tuple[bool, list[dict] | str]:
        """What Hestia knows about the user (keyword match), compact rows for an external AI."""
        ok, rows = self.search_memories(query)
        if not ok:
            return (False, rows)
        return (True, [{"fact": r.get("fact"), "domains": r.get("domains") or [r.get("domain")],
                        "since": str(r.get("created_at") or "")[:10]} for r in rows[:RECALL_MAX]])

    def list_memories(self) -> list[dict]:
        """Active user memories with their origin, newest first (Memoria page)."""
        rows = self._get_active_memory(memory_class=MEMORY_CLASS_PREFERENCE) or []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            extra = r.get("extra_data") if isinstance(r.get("extra_data"), dict) else {}
            out.append({"id": r.get("id"), "fact": r.get("fact"), "domains": r.get("domains") or [r.get("domain")],
                        "source": extra.get("source") or "chat", "access": extra.get("access") or "",
                        "topic": extra.get("topic") or "", "created_at": r.get("created_at")})
        return out

    def forget(self, memory_id: int) -> bool:
        """Deactivate one memory (Archive keeps the row, Oracle stops using it)."""
        done = self._route_archive("PATCH", f"/memory/{int(memory_id)}", body={"is_active": False})
        if done is not None:
            logger.info("event=memory_forgotten id=%s", memory_id)
        return done is not None

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
        t0 = time.perf_counter()
        logger.info(
            "event=memory_extract_start session_id=%s force_notification=%s",
            session_id, bool(force_notification_compiler),
        )
        signals: list[dict] = []
        # Selective memory (like Claude): the LLM extractor runs only when the message
        # can carry a durable fact; greetings/tests/questions never touch memory.
        should_extract_prefs = is_memory_worthy(user_message)
        should_extract_subs = force_notification_compiler or has_notification_intent(
            user_message)

        if not should_extract_prefs and not should_extract_subs:
            return signals

        prefs, domains, history_text = self._build_conversation_context(
            session_id)
        prefs_by_id: dict[int, dict] = {
            int(p["id"]): p for p in prefs if p.get("id") is not None
        }
        pref_context = (
            "\n".join(f"ID: {p['id']} | Fact: {p['fact']}" for p in prefs)
            if prefs else "Nessuna."
        )

        if should_extract_prefs:
            allow_deprecate = has_deprecate_intent(user_message)
            pref_prompt = prompt_config.prompt(
                "memory_preferences_template",
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
                signals.extend(self._save_preferences(
                    pref_actions, prefs_by_id))
            except Exception as exc:
                logger.warning(
                    "event=memoryservice_save_preferences_failed [MemoryService] save preferences failed: %s", exc)

        if not should_extract_subs:
            return signals

        sub_prompt = prompt_config.prompt(
            "memory_subscriptions_template",
            domains=", ".join(domains),
            user_message=user_message,
            history_text=history_text,
        )
        if force_notification_compiler:
            sub_prompt += prompt_config.prompt(
                "memory_subscriptions_forced_suffix")

        raw_sub = self._ask(sub_prompt)
        fallback_target = (notify_target or "").strip() or session_id
        subscriptions = parse_subscription_actions(
            raw_sub, domains, owner=session_id, default_target=fallback_target
        )

        if not subscriptions:
            total_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "event=memory_extract_done session_id=%s total_ms=%s signals=%s",
                session_id, total_ms, len(signals),
            )
            return signals

        existing_subs = self._api_get(
            f"/subscriptions/active?owner={session_id}", default_val=[]) or []
        existing_map: dict[str, dict] = {
            str(s["subscription_id"]): s
            for s in existing_subs
            if s.get("subscription_id")
        }

        try:
            signals.extend(self._save_subscriptions(
                subscriptions, existing_map, session_id))
        except Exception as exc:
            logger.warning(
                "event=memoryservice_save_subscriptions_failed [MemoryService] save subscriptions failed: %s", exc)

        total_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "event=memory_extract_done session_id=%s total_ms=%s signals=%s",
            session_id, total_ms, len(signals),
        )
        return signals
