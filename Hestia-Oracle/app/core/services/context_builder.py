import json
from typing import Any


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
