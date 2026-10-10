"""Value validation against a module's declared definition (types from hestia_common.settings_client)."""
from __future__ import annotations

import re
from typing import Any

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DURATION = re.compile(r"^\d+(\.\d+)?\s*(ms|s|m|h|d)?$")
_TRUE = {"true", "1", "yes", "on", "si", "sì"}
_FALSE = {"false", "0", "no", "off"}


class SettingValueError(ValueError):
    pass


def _number(defn: dict, value: Any, cast) -> Any:
    if isinstance(value, bool):
        raise SettingValueError("numero atteso")
    try:
        number = cast(value)
    except (TypeError, ValueError):
        raise SettingValueError("numero atteso")
    if cast is int and isinstance(value, float) and value != int(value):
        raise SettingValueError("numero intero atteso")
    if defn.get("min") is not None and number < defn["min"]:
        raise SettingValueError(f"minimo {defn['min']}")
    if defn.get("max") is not None and number > defn["max"]:
        raise SettingValueError(f"massimo {defn['max']}")
    return number


def validate(defn: dict, value: Any) -> Any:
    """Return the value coerced to the declared type, or raise SettingValueError (Italian message)."""
    kind = defn.get("type", "string")
    if value is None:
        raise SettingValueError("valore mancante (per tornare al predefinito usa Ripristina)")
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise SettingValueError("sì/no atteso")
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
        raise SettingValueError("valore non ammesso: " + ", ".join(str(a) for a in allowed))
    if kind in {"string", "text", "model"}:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise SettingValueError("testo atteso")
        text = str(value)
        if kind != "text" and len(text) > 500:
            raise SettingValueError("testo troppo lungo")
        if kind == "text" and len(text) > 20000:
            raise SettingValueError("testo troppo lungo")
        return text
    if kind == "time":
        text = str(value).strip()
        if not _TIME.match(text):
            raise SettingValueError("orario HH:MM atteso")
        return text
    if kind == "duration":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if not _DURATION.match(text):
            raise SettingValueError("durata attesa (es. 30s, 5m, 2h)")
        return text
    if kind == "list":
        if not isinstance(value, list):
            raise SettingValueError("lista attesa")
        item = defn.get("item")
        return [validate(item, v) for v in value] if isinstance(item, dict) else value
    if kind == "object":
        if not isinstance(value, dict):
            raise SettingValueError("oggetto atteso")
        fields = defn.get("fields") or {}
        out = dict(value)
        for name, sub in fields.items():
            if name in value and value[name] is not None:
                try:
                    out[name] = validate(sub, value[name])
                except SettingValueError as exc:
                    raise SettingValueError(f"{sub.get('label') or name}: {exc}")
        return out
    raise SettingValueError(f"tipo sconosciuto {kind}")
