"""Memory LLM output parsers — pure functions, no I/O, no side effects.

Parse raw JSON strings produced by the scribe agent into validated
action lists ready for Archive persistence.
"""
from __future__ import annotations

import hashlib
import json
import os

from core.services.memory_intent import is_fact_grounded_in_message


def parse_preference_actions(
    raw_output: str,
    domains: list[str],
    active_prefs: list[dict],
    user_message: str = "",
    allow_deprecate: bool = False,
) -> list[dict]:
    """Parse and validate preference ADD / DEPRECATE actions from LLM JSON output.

    Returns a list of validated action dicts ready to be applied to Archive.
    """
    if not raw_output or ("NONE" in raw_output.upper()
                          and '"ADD"' not in raw_output.upper()
                          and '"DEPRECATE"' not in raw_output.upper()):
        return []

    start = raw_output.find("[")
    end = raw_output.rfind("]")
    if start == -1 or end == -1:
        return []

    try:
        parsed = json.loads(raw_output[start:end + 1])
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

    validated: list[dict] = []
    seen: set = set()

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
            if not is_fact_grounded_in_message(fact, user_message):
                continue
            fact_key = fact.lower()
            if fact_key in existing_facts:
                continue
            domain = str(item.get("domain", "general")
                         ).strip().lower() or "general"
            if domain not in allowed_domains:
                domain = "general"
            key = ("ADD", fact_key, domain)
            if key in seen:
                continue
            seen.add(key)
            validated.append({"action": "ADD", "fact": fact, "domain": domain})
            continue

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
        key = ("DEPRECATE", pref_id)
        if key in seen:
            continue
        seen.add(key)
        validated.append({"action": "DEPRECATE", "id": pref_id})

    return validated


def parse_subscription_actions(
    raw_output: str,
    domains: list[str],
    owner: str,
    default_target: str,
) -> list[dict]:
    """Parse and validate subscription ADD / DEPRECATE actions from LLM JSON output."""
    if not raw_output or ("NONE" in raw_output.upper() and "[" not in raw_output):
        return []

    start = raw_output.find("[")
    end = raw_output.rfind("]")
    if start == -1 or end == -1:
        return []

    try:
        parsed = json.loads(raw_output[start:end + 1])
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    allowed_domains = {str(d).strip().lower()
                       for d in domains if str(d).strip()}
    allowed_domains.add("general")
    allowed_event_types = {"entity.upserted"}
    force_telegram_target = os.getenv(
        "ORACLE_FORCE_TELEGRAM_TARGET", "1").strip().lower() not in {"0", "false", "no"}
    fallback_target = default_target or os.getenv(
        "ORACLE_NOTIFY_DEFAULT_TARGET", owner)

    validated: list[dict] = []
    seen: set = set()

    for item in parsed:
        if not isinstance(item, dict):
            continue

        action = str(item.get("action", "ADD")).strip().upper()

        if action == "DEPRECATE":
            sub_id = str(item.get("subscription_id",
                         item.get("id", ""))).strip()
            if not sub_id:
                continue
            key = ("DEPRECATE", sub_id)
            if key in seen:
                continue
            seen.add(key)
            validated.append(
                {"action": "DEPRECATE", "subscription_id": sub_id, "owner": owner})
            continue

        domain = str(item.get("domain", "general")).strip().lower()
        if domain not in allowed_domains:
            domain = "general"

        event_type = str(
            item.get("event_type", "entity.upserted")).strip().lower()
        if event_type not in allowed_event_types:
            event_type = "entity.upserted"

        filters = item.get("filters") if isinstance(
            item.get("filters"), dict) else {}
        raw_channels = item.get("channels") if isinstance(
            item.get("channels"), list) else []
        if not raw_channels:
            raw_channels = [{"type": "telegram", "target": fallback_target}]

        channels: list[dict] = []
        for ch in raw_channels:
            if not isinstance(ch, dict):
                continue
            ch_type = "telegram"
            ch_target = str(ch.get("target", fallback_target)).strip()
            if force_telegram_target or not ch_target:
                ch_target = fallback_target
            if ch_target:
                channels.append({"type": ch_type, "target": ch_target})

        if not channels:
            continue

        signature_payload = json.dumps(
            {"owner": owner, "domain": domain, "event_type": event_type,
             "filters": filters, "channels": channels},
            sort_keys=True, ensure_ascii=False,
        )
        sub_id = hashlib.sha1(signature_payload.encode("utf-8")).hexdigest()
        if (sub_id,) in seen:
            continue
        seen.add((sub_id,))

        validated.append({
            "action": "UPSERT", "subscription_id": sub_id, "owner": owner,
            "domain": domain, "event_type": event_type,
            "filters": filters, "channels": channels, "is_active": True,
        })

    return validated
