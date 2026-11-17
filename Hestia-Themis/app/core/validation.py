"""Value validation against a module's declared definition (types from hestia_common.settings_client)."""
from __future__ import annotations

import re
from typing import Any
from hestia_common.i18n import is_yes, t as tr  # fixed texts in the owner's language

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DURATION = re.compile(r"^\d+(\.\d+)?\s*(ms|s|m|h|d)?$")
_TRUE = {"on"}          # plus is_yes(): 1, true and the yes words of every language
_FALSE = {"false", "0", "no", "off"}


class SettingValueError(ValueError):
    pass


def _number(defn: dict, value: Any, cast) -> Any:
    if isinstance(value, bool):
        raise SettingValueError(tr("number expected"))
    try:
        number = cast(value)
    except (TypeError, ValueError):
        raise SettingValueError(tr("number expected"))
    if cast is int and isinstance(value, float) and value != int(value):
        raise SettingValueError(tr("whole number expected"))
    if defn.get("min") is not None and number < defn["min"]:
        raise SettingValueError(tr("minimum {0}", defn['min']))
    if defn.get("max") is not None and number > defn["max"]:
        raise SettingValueError(tr("maximum {0}", defn['max']))
    return number


def validate(defn: dict, value: Any) -> Any:
    """Return the value coerced to the declared type, or raise SettingValueError (Italian message)."""
    kind = defn.get("type", "string")
    if value is None:
        raise SettingValueError(tr("missing value (to go back to the default use Restore)"))
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE or is_yes(text):
            return True
        if text in _FALSE:
            return False
        raise SettingValueError(tr("yes/no expected"))
    if kind == "int":
        return _number(defn, value, int)
    if kind == "float":
        return _number(defn, value, float)
    if kind == "enum":
        allowed = [o.get("value") for o in defn.get("options") or []]
        if value in allowed:
            return value
        text = str(value)
        for option in allowed:
            if str(option) == text:
                return option
        raise SettingValueError(tr("value not allowed: ") + ", ".join(str(a) for a in allowed))
    if kind in {"string", "text", "model"}:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise SettingValueError(tr("text expected"))
        text = str(value)
        if kind != "text" and len(text) > 500:
            raise SettingValueError(tr("text too long"))
        if kind == "text" and len(text) > 20000:
            raise SettingValueError(tr("text too long"))
        return text
    if kind == "time":
        text = str(value).strip()
        if not _TIME.match(text):
            raise SettingValueError(tr("time HH:MM expected"))
        return text
    if kind == "duration":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if not _DURATION.match(text):
            raise SettingValueError(tr("duration expected (e.g. 30s, 5m, 2h)"))
        return text
    if kind == "list":
        if not isinstance(value, list):
            raise SettingValueError(tr("list expected"))
        item = defn.get("item")
        return [validate(item, v) for v in value] if isinstance(item, dict) else value
    if kind == "object":
        if not isinstance(value, dict):
            raise SettingValueError(tr("object expected"))
        fields = defn.get("fields") or {}
        out = dict(value)
        for name, sub in fields.items():
            if name in value and value[name] is not None:
                try:
                    out[name] = validate(sub, value[name])
                except SettingValueError as exc:
                    raise SettingValueError(f"{sub.get('label') or name}: {exc}")
        return out
    raise SettingValueError(tr("unknown type {0}", kind))
