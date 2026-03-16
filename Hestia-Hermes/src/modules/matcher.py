from typing import Any


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_payload_value(payload: dict[str, Any], key: str):
    if "." not in key:
        return payload.get(key)

    current: Any = payload
    for segment in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def subscription_matches(subscription: dict[str, Any], event_payload: dict[str, Any]) -> bool:
    filters = subscription.get("filters") or {}
    if not isinstance(filters, dict):
        return True

    for key, expected in filters.items():
        actual = _get_payload_value(event_payload, key)

        if key.startswith("max_"):
            field = key.replace("max_", "", 1)
            actual = _get_payload_value(event_payload, field)
            actual_num = _safe_float(actual)
            expected_num = _safe_float(expected)
            if actual_num is None or expected_num is None or actual_num > expected_num:
                return False
            continue

        if key.startswith("min_"):
            field = key.replace("min_", "", 1)
            actual = _get_payload_value(event_payload, field)
            actual_num = _safe_float(actual)
            expected_num = _safe_float(expected)
            if actual_num is None or expected_num is None or actual_num < expected_num:
                return False
            continue

        if isinstance(expected, str):
            if str(actual or "").strip().lower() != expected.strip().lower():
                return False
            continue

        if actual != expected:
            return False

    return True
