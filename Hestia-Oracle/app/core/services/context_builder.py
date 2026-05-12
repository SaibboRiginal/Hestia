import json
import logging
import os
from typing import Any

from core.services import prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── Compaction thresholds ─────────────────────────────────────────────────────
# Trigger background compaction when history exceeds this many messages.
_COMPACT_TRIGGER_MESSAGES: int = int(
    os.getenv("ORACLE_COMPACT_TRIGGER_MSGS", "20"))
# Keep this many recent (uncompressed) messages after compaction.
_COMPACT_KEEP_RECENT: int = int(os.getenv("ORACLE_COMPACT_KEEP_RECENT", "6"))

# ── Protected content classes (must NOT be lossy-summarised) ──────────────────
# These role+content patterns are extracted before compaction and preserved
# as structured state, not prose.
_PROTECTED_PREFIXES = (
    "[PREFERENCE]",
    "[SUBSCRIPTION]",
    "[COMMITMENT]",
    "[QUESTION]",
    "[CORRECTION]",
    "[PINNED]",
)


class ContextBuilder:
    def __init__(
        self,
        max_history_messages: int,
        max_history_chars: int,
        max_entities_in_context: int,
        max_field_chars: int,
    ):
        self.max_history_messages = max_history_messages
        self.max_history_chars = max_history_chars
        self.max_entities_in_context = max_entities_in_context
        self.max_field_chars = max_field_chars

    def truncate(self, value: Any, max_len: int) -> str:
        clean = str(value).strip()
        if len(clean) <= max_len:
            return clean
        return clean[: max_len - 1] + "…"

    def compact_history(self, history_data: list) -> str:
        if not history_data:
            return ""

        trimmed = history_data[-self.max_history_messages:]
        lines = []
        for message in trimmed:
            role = "User" if message.get("role") == "user" else "Hestia"
            content = self.truncate(message.get(
                "content", ""), self.max_history_chars)
            lines.append(f"{role}: {content}")

        return "--- PREVIOUS CONVERSATION ---\n" + "\n".join(lines) + "\n\n"

    def compact_entity(self, entity: dict) -> dict:
        compact = {}

        priority_keys = [
            "id",
            "entity_id",
            "url",
            "name",
            "title",
            "type",
            "category",
            "status",
            "score",
            "summary",
            "description",
        ]

        for key in priority_keys:
            if key in entity and entity[key] is not None:
                value = entity[key]
                compact[key] = self.truncate(
                    value, self.max_field_chars) if isinstance(value, str) else value

        primitive_count = 0
        for key, value in entity.items():
            if key in compact:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = self.truncate(
                    value, self.max_field_chars) if isinstance(value, str) else value
                primitive_count += 1
                if primitive_count >= 8:
                    break

        nested_count = 0
        for key, value in entity.items():
            if key in compact:
                continue
            if isinstance(value, dict):
                nested_obj = {}
                nested_field_count = 0
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, (str, int, float, bool)) or nested_value is None:
                        nested_obj[nested_key] = (
                            self.truncate(nested_value, self.max_field_chars)
                            if isinstance(nested_value, str)
                            else nested_value
                        )
                        nested_field_count += 1
                        if nested_field_count >= 8:
                            break
                if nested_obj:
                    compact[key] = nested_obj
                    nested_count += 1
                    if nested_count >= 2:
                        break

        return compact if compact else {"record": self.truncate(entity, self.max_field_chars)}

    def compact_entities_for_prompt(self, entities: list[dict]) -> str:
        if not entities:
            return "DATABASE_RESPONSE: No records found."
        compact_entities = [self.compact_entity(
            entity) for entity in entities[: self.max_entities_in_context]]
        return json.dumps(compact_entities, ensure_ascii=False, indent=2)

    def build_analysis_prompt(
        self,
        preference_facts: list[str],
        valid_domains: list[str],
        active_filters: dict,
        filters_gt: dict,
        filters_lt: dict,
        sort_by: str | None,
        sort_order: str,
        formatted_context: str,
        history_text: str,
        user_message: str,
    ) -> str:
        pref_text = "\n".join([f"- {fact}" for fact in preference_facts]
                              ) if preference_facts else "Nessuna preferenza."
        route_metadata = {
            "domains": valid_domains,
            "filters": active_filters,
            "filters_gt": filters_gt,
            "filters_lt": filters_lt,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }

        return (
            f"USER_PREFERENCES:\n{pref_text}\n\n"
            f"ROUTE_METADATA:\n{json.dumps(route_metadata, ensure_ascii=False)}\n\n"
            f"CONTEXT_DATA_RECORDS:\n{formatted_context}\n\n"
            f"{history_text}USER_QUESTION: {user_message}"
        )

    # ── Context compaction ────────────────────────────────────────────────────

    def needs_compaction(self, history_data: list) -> bool:
        """Return True when history is long enough to warrant background compaction."""
        return len(history_data) >= _COMPACT_TRIGGER_MESSAGES

    def extract_protected_messages(self, history_data: list) -> list[dict]:
        """Extract messages containing protected content (must not be lossy-summarised).

        Protected messages include anything tagged with a known prefix in their
        content (preferences, subscriptions, commitments, unresolved questions,
        corrections, pinned entities).
        """
        protected = []
        for msg in history_data:
            content = str(msg.get("content", ""))
            if any(content.startswith(pfx) for pfx in _PROTECTED_PREFIXES):
                protected.append(msg)
        return protected

    def build_compaction_prompt(self, history_to_compact: list) -> str:
        """Build the scribe prompt for summarising old history segments."""
        lines = []
        for msg in history_to_compact:
            role = "User" if msg.get("role") == "user" else "Hestia"
            lines.append(f"{role}: {msg.get('content', '')}")
        history_text = "\n".join(lines)

        return prompt_config.prompt(
            "memory_compactor_template",
            history_text=history_text,
        )

    def run_background_compaction(
        self,
        session_id: str,
        history_data: list,
        scribe_agent,
        hub_client,
    ) -> bool:
        """Summarise old history and persist the snapshot via Hub/Archive.

        Designed to run in a daemon thread (non-blocking for the chat path).
        Returns True if compaction was performed, False if skipped.

        Steps:
        1. Split history into: old segment (to compact) + recent (to keep as-is).
        2. Extract protected messages from old segment and keep verbatim.
        3. Run scribe LLM to summarise the non-protected old messages.
        4. Build a snapshot = [protected messages] + [summary message].
        5. Delete old history turns and replace with snapshot via Hub.
        """
        if not self.needs_compaction(history_data):
            return False

        # Partition history
        old_segment = history_data[:-_COMPACT_KEEP_RECENT]
        recent_segment = history_data[-_COMPACT_KEEP_RECENT:]

        if not old_segment:
            return False

        # Extract protected messages (reproduced verbatim in snapshot)
        protected = self.extract_protected_messages(old_segment)
        compactable = [m for m in old_segment if m not in protected]

        # Build summary via scribe
        summary_text = ""
        if compactable:
            compaction_prompt = self.build_compaction_prompt(compactable)
            try:
                summary_text = scribe_agent.ask(compaction_prompt).strip()
            except Exception as exc:
                logger.warning(
                    "event=compaction_scribe_call_failed Compaction scribe call failed: %s", exc)
                return False

        # Persist snapshot via Hub (replaces old turns with summary)
        try:
            # Clear full history for this session
            hub_client.delete(f"/chat/history/{session_id}")

            # Re-write: snapshot (protected + summary) + recent
            if protected:
                protected_text = "\n".join(
                    f"{m.get('role', '?')}: {m.get('content', '')}" for m in protected
                )
                hub_client.post("/chat/history", {
                    "session_id": session_id,
                    "role": "system",
                    "content": f"[PROTECTED_FACTS]\n{protected_text}",
                })

            if summary_text:
                hub_client.post("/chat/history", {
                    "session_id": session_id,
                    "role": "system",
                    "content": f"[COMPACTED_MEMORY]\n{summary_text}",
                })

            for msg in recent_segment:
                hub_client.post("/chat/history", {
                    "session_id": session_id,
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

            logger.info(
                "event=context_compacted_session_old_protected Context compacted | session=%s old=%d protected=%d summary_len=%d recent=%d",
                session_id, len(old_segment), len(protected), len(
                    summary_text), len(recent_segment),
            )
            return True

        except Exception as exc:
            logger.warning(
                "event=compaction_persistence_failed Compaction persistence failed: %s", exc)
            return False
