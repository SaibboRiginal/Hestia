import json
import re
import threading
import time
import uuid
from html import escape
from typing import Any
from urllib.parse import urlparse

import requests
from telebot.types import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup

from command_catalog import telegram_local_commands
from telegram_bot import core


TONE_PRESETS = [
    ("warm", "Caldo"),
    ("neutral", "Neutro"),
    ("direct", "Diretto"),
    ("formal", "Formale"),
]

COMMAND_ALIASES = {
    "scout_list": "scout_listings",
}


def _format_price(value: Any) -> str:
    if value is None:
        return ""
    try:
        amount = float(value)
        return f"€ {amount:,.0f}".replace(",", ".")
    except Exception:
        return str(value)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return escape(text) if text else default


def _pretty_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "T" in raw:
        date_part, _, time_part = raw.partition("T")
        time_part = time_part.replace("Z", "").split(".", 1)[0]
        if date_part and time_part:
            return f"{date_part} {time_part[:5]}"
    return raw[:16]


def _pretty_link_label(url: str) -> str:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").strip() or "annuncio"
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            return f"{domain} / {' / '.join(path_parts[:2])}"
        return domain
    except Exception:
        return "annuncio"


def _readable_filter_label(key: str) -> str:
    mapping = {
        "city": "Citta",
        "location": "Zona",
        "address": "Indirizzo",
        "price_max": "Prezzo max",
        "max_price": "Prezzo max",
        "budget_max": "Budget max",
        "price_min": "Prezzo min",
        "min_price": "Prezzo min",
        "surface_min": "Metratura min",
        "min_surface": "Metratura min",
        "surface_max": "Metratura max",
        "rooms_min": "Locali min",
        "min_rooms": "Locali min",
        "property_type": "Tipologia",
        "contract": "Contratto",
        "keywords": "Parole chiave",
    }
    normalized = str(key or "").strip().lower()
    if normalized in mapping:
        return mapping[normalized]
    return str(key or "").replace("_", " ").strip().title()


def _format_budget_short(value: Any) -> str:
    try:
        amount = float(value)
        if amount >= 1000:
            return f"<= {int(amount/1000)}k"
        return f"<= {int(amount)}"
    except Exception:
        text = str(value or "").strip()
        return text


def _build_subscription_picker_label(item: dict[str, Any], fallback_value: str) -> str:
    filters = item.get("filters") if isinstance(
        item.get("filters"), dict) else {}

    city = str(filters.get("city") or filters.get("location") or "").strip()
    property_type = str(filters.get("property_type") or "").strip()
    rooms = str(filters.get("rooms_min")
                or filters.get("min_rooms") or "").strip()
    max_price = filters.get("price_max")
    if max_price is None:
        max_price = filters.get("max_price")
    if max_price is None:
        max_price = filters.get("budget_max")

    parts: list[str] = []
    if city:
        parts.append(city)
    if property_type:
        parts.append(property_type)
    if rooms:
        parts.append(f"{rooms}+ locali")
    if max_price is not None and str(max_price).strip() != "":
        budget = _format_budget_short(max_price)
        if budget:
            parts.append(budget)

    if parts:
        return " | ".join(parts)

    readable_filters: list[str] = []
    for filter_key, filter_val in list(filters.items())[:2]:
        if filter_val is None or str(filter_val).strip() == "":
            continue
        readable_filters.append(
            f"{_readable_filter_label(str(filter_key))}: {str(filter_val).strip()}"
        )
    if readable_filters:
        return " | ".join(readable_filters)

    domain = _safe_text(item.get("domain"), "")
    event_type = _safe_text(item.get("event_type"), "")

    if domain == "real_estate":
        return "🏠 Notifica immobili (tutti i criteri)"
    if domain:
        return f"🔔 Notifica {domain}"

    return "🔔 Notifica generale"


def _format_surface(payload: dict[str, Any]) -> str:
    specs = payload.get("specs") if isinstance(
        payload.get("specs"), dict) else {}
    for key in ("surface_m2", "m2", "surface"):
        if key in specs and specs.get(key) is not None:
            return f"{specs.get(key)} m²"
        if key in payload and payload.get(key) is not None:
            return f"{payload.get(key)} m²"
    return ""


def format_scout_listings(payload: Any, limit: int = 12) -> str | None:
    if not isinstance(payload, list):
        return None

    rows = [item for item in payload if isinstance(item, dict)]
    if not rows:
        return "Nessuna casa trovata."

    blocks: list[str] = []
    for item in rows[:limit]:
        title = str(item.get("title") or item.get("name")
                    or item.get("summary") or "Casa").strip()
        where = str(item.get("address") or item.get("location")
                    or item.get("city") or "").strip()
        price = _format_price(item.get("price"))
        m2 = _format_surface(item)
        link = str(item.get("url") or item.get("entity_id") or "").strip()

        parts: list[str] = []
        if link:
            parts.append(f"<a href=\"{link}\"><b>{title}</b></a>")
        else:
            parts.append(f"<b>{title}</b>")
        if where:
            parts.append(f"📍 {where}")
        details: list[str] = []
        if price:
            details.append(price)
        if m2:
            details.append(m2)
        if details:
            parts.append(" · ".join(details))
        blocks.append("\n".join(parts))

    header = f"🏠 <b>Case disponibili</b> ({len(rows)})"
    return header + "\n\n" + "\n\n".join(blocks)


def format_subscriptions_list(payload: Any) -> str | None:
    """Format subscription data as readable list"""
    if not isinstance(payload, list):
        return None

    items = [item for item in payload if isinstance(item, dict)]
    if not items:
        return "Nessuna notifica attiva."

    lines = [f"🔔 <b>Notifiche attive</b> ({len(items)})"]
    for idx, item in enumerate(items, 1):
        filters = item.get("filters") if isinstance(
            item.get("filters"), dict) else {}

        title_parts = []
        if filters:
            city = _safe_text(filters.get("city") or filters.get("location"))
            prop_type = _safe_text(filters.get("property_type"))
            if city:
                title_parts.append(city)
            if prop_type:
                title_parts.append(prop_type)

        if title_parts:
            title = " - ".join(title_parts)
        else:
            domain = _safe_text(item.get("domain"), "")
            if domain == "real_estate":
                title = "Tutte le case"
            else:
                title = "Notifica generale"

        lines.append(f"<b>{idx}. {title}</b>")

        if filters:
            filter_parts: list[str] = []
            for filter_key, filter_val in list(filters.items())[:4]:
                if filter_val is not None and str(filter_val).strip() != "":
                    if filter_key not in ("city", "location", "property_type"):
                        key_label = _safe_text(
                            _readable_filter_label(filter_key))
                        filter_parts.append(
                            f"{key_label}: {_safe_text(filter_val)}")
            if filter_parts:
                lines.append(f"  {', '.join(filter_parts)}")
        lines.append("")

    return "\n".join(lines)


def format_active_preferences(payload: Any) -> str | None:
    if not isinstance(payload, list):
        return None

    rows = [item for item in payload if isinstance(item, dict)]
    if not rows:
        return "Nessuna preferenza attiva."

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        domain = str(item.get("domain") or "general").strip() or "general"
        grouped.setdefault(domain, []).append(item)

    lines: list[str] = [f"🧠 <b>Preferenze attive</b> ({len(rows)})"]
    for domain in sorted(grouped.keys()):
        lines.append(f"\n<b>{_safe_text(domain.title())}</b>")
        for pref in grouped[domain]:
            fact = _safe_text(pref.get("fact"), "(vuota)")
            weight = pref.get("weight")
            weight_text = ""
            if weight is not None and weight != 1.0:
                try:
                    weight_text = f" (peso {float(weight):.1f})"
                except Exception:
                    pass
            lines.append(f"• {fact}{weight_text}")

    return "\n".join(lines)


def format_recent_alerts(payload: Any, limit: int = 15) -> str | None:
    if not isinstance(payload, list):
        return None

    rows = [item for item in payload if isinstance(item, dict)]
    if not rows:
        return "Nessun avviso recente."

    blocks: list[str] = []
    for item in rows[:limit]:
        title = str(item.get("entity_title") or item.get("title")
                    or item.get("entity_id") or "Avviso").strip()
        address = str(item.get("entity_address")
                      or item.get("address") or "").strip()
        price_val = item.get("entity_price") or item.get("price")
        price = _format_price(price_val)
        url = str(item.get("entity_url") or item.get(
            "entity_id") or "").strip()
        when = _pretty_date(item.get("created_at"))

        if title.startswith("http"):
            if url:
                title = _pretty_link_label(url)
            else:
                title = "Nuova proprietà"
        safe_title = _safe_text(title, "Nuova proprietà")

        parts: list[str] = []
        if url:
            parts.append(f"<a href=\"{escape(url)}\"><b>{safe_title}</b></a>")
        else:
            parts.append(f"<b>{safe_title}</b>")
        detail_tokens: list[str] = []
        if address:
            detail_tokens.append(f"📍 {_safe_text(address)}")
        if price:
            detail_tokens.append(_safe_text(price))
        if when:
            detail_tokens.append(_safe_text(when))
        if detail_tokens:
            parts.append(" · ".join(detail_tokens))
        blocks.append("\n".join(parts))

    header = f"📬 <b>Avvisi recenti</b> ({len(rows)})"
    return header + "\n\n" + "\n\n".join(blocks)


def prompt_set_parameter_picker(chat_id: int):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🎙️ Tone", callback_data="set:param:tone"),
        InlineKeyboardButton(
            "📝 Custom Prompt", callback_data="set:param:custom_prompt"),
    )
    core.bot.send_message(
        chat_id,
        "Scegli il parametro da impostare:",
        reply_markup=keyboard,
    )


def prompt_tone_presets(chat_id: int):
    keyboard = InlineKeyboardMarkup(row_width=2)
    for tone_value, tone_label in TONE_PRESETS:
        keyboard.add(InlineKeyboardButton(
            tone_label, callback_data=f"set:tone:{tone_value}"))
    core.bot.send_message(
        chat_id, "Seleziona un preset di tone:", reply_markup=keyboard)


def _cancel_input_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(
        "❌ Annulla", callback_data="cancel_flow"))
    return keyboard


def start_text_input_flow(
    chat_id: int,
    command_name: str,
    command_meta: dict[str, Any],
    missing_arg: str,
    parsed_args: dict[str, Any] | None = None,
):
    existing = dict(parsed_args or {})
    core.PENDING_WORKFLOWS[str(chat_id)] = {
        "action": "command_text_input",
        "command_name": str(command_name or "").strip().lower(),
        "command": command_meta,
        "missing_arg": str(missing_arg or "").strip().lower(),
        "parsed_args": existing,
        "created_at": time.time(),
    }

    pretty_name = str(missing_arg or "valore").replace("_", " ").strip()
    core.bot.send_message(
        chat_id,
        f"✍️ Inserisci ora il valore per <b>{pretty_name}</b> nel prossimo messaggio.",
        parse_mode="HTML",
        reply_markup=_cancel_input_keyboard(),
    )


def parse_command_arguments(raw_text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for token in str(raw_text or "").strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if not normalized_key:
            continue
        if normalized_value.isdigit():
            parsed[normalized_key] = int(normalized_value)
        else:
            parsed[normalized_key] = normalized_value
    return parsed


def extract_required_args(arguments_help: str) -> list[str]:
    if not arguments_help:
        return []
    return [match.group(1).strip().lower() for match in re.finditer(r"([a-zA-Z0-9_]+)\s*=", arguments_help)]


def resolve_template(value: Any, session_id: str, chat_id: int, parsed_args: dict[str, Any]) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "$session_id":
            return session_id
        if stripped == "$chat_id":
            return str(chat_id)
        if stripped.startswith("$arg."):
            arg_key = stripped.replace("$arg.", "", 1).strip().lower()
            return parsed_args.get(arg_key)

        def replace_match(match: re.Match) -> str:
            token = match.group(1)
            if token == "session_id":
                return session_id
            if token == "chat_id":
                return str(chat_id)
            if token.startswith("arg."):
                key = token.replace("arg.", "", 1).strip().lower()
                return str(parsed_args.get(key, ""))
            return ""

        return re.sub(r"\$(session_id|chat_id|arg\.[a-zA-Z0-9_]+)", replace_match, value)

    if isinstance(value, dict):
        resolved = {}
        for key, item in value.items():
            computed = resolve_template(item, session_id, chat_id, parsed_args)
            item_is_arg_template = isinstance(
                item, str) and item.strip().startswith("$arg.")
            if item_is_arg_template and (computed is None or computed == ""):
                continue
            if computed is not None:
                resolved[key] = computed
        return resolved

    if isinstance(value, list):
        resolved_list = []
        for item in value:
            computed = resolve_template(item, session_id, chat_id, parsed_args)
            item_is_arg_template = isinstance(
                item, str) and item.strip().startswith("$arg.")
            if item_is_arg_template and (computed is None or computed == ""):
                continue
            if computed is not None:
                resolved_list.append(computed)
        return resolved_list

    return value


def route_service_command(service: str, path: str, method: str, query: dict[str, Any], body: dict[str, Any]) -> tuple[bool, Any]:
    normalized_path = str(path or "").lstrip("/")
    try:
        response = requests.post(
            f"{core.HUB_API_URL}/route/{service}/{normalized_path}",
            json={
                "method": str(method or "GET").upper(),
                "headers": {},
                "query": query or {},
                "body": body if body else None,
                "timeout_seconds": 10,
            },
            timeout=12,
        )
        if response.status_code != 200:
            print(
                f"[-] Route failed: service={service} method={method} path={normalized_path} status={response.status_code} body={response.text}")
            return False, response.text

        routed = response.json() or {}
        status_code = int(routed.get("status_code", 500))
        payload = routed.get("payload")
        if status_code >= 400:
            print(
                f"[-] Routed error: service={service} method={method} path={normalized_path} status={status_code} payload={payload}")
            return False, payload
        return True, payload
    except Exception as error:
        print(
            f"[-] Route exception: service={service} method={method} path={normalized_path} error={error}")
        return False, str(error)


def route_command_from_metadata(command_meta: dict[str, Any], chat_id: int, parsed_args: dict[str, Any]) -> tuple[bool, Any]:
    query_template = command_meta.get("query_template") if isinstance(
        command_meta.get("query_template"), dict) else {}
    body_template = command_meta.get("body_template") if isinstance(
        command_meta.get("body_template"), dict) else {}

    session_id = core.get_session(str(chat_id))
    query = resolve_template(query_template, session_id, chat_id, parsed_args)
    if not isinstance(query, dict):
        query = {}
    query.update(parsed_args)

    body = resolve_template(body_template, session_id, chat_id, parsed_args)
    if not isinstance(body, dict):
        body = {}

    path_value = resolve_template(str(command_meta.get(
        "path", "")).strip(), session_id, chat_id, parsed_args)
    return route_service_command(
        service=str(command_meta.get("service", "")).strip(),
        path=str(path_value or "").strip(),
        method=str(command_meta.get("method", "GET")).upper(),
        query=query,
        body=body,
    )


def open_arg_picker(chat_id: int, command_name: str, command: dict[str, Any], missing_arg: str):
    arg_picker = command.get("arg_picker") if isinstance(
        command.get("arg_picker"), dict) else {}
    source = arg_picker.get("source") if isinstance(
        arg_picker.get("source"), dict) else {}
    picker_arg = str(arg_picker.get("arg", "")).strip().lower()
    if not source or picker_arg != missing_arg:
        start_text_input_flow(
            chat_id=chat_id,
            command_name=command_name,
            command_meta=command,
            missing_arg=missing_arg,
            parsed_args={},
        )
        return

    ok, payload = route_command_from_metadata(source, chat_id, {})
    if not ok or not isinstance(payload, list) or not payload:
        start_text_input_flow(
            chat_id=chat_id,
            command_name=command_name,
            command_meta=command,
            missing_arg=missing_arg,
            parsed_args={},
        )
        return

    value_field = str(arg_picker.get(
        "value_field", missing_arg)).strip() or missing_arg
    label_fields = arg_picker.get("label_fields") if isinstance(
        arg_picker.get("label_fields"), list) else []

    keyboard = InlineKeyboardMarkup()
    count = 0
    for item in payload[:10]:
        if not isinstance(item, dict):
            continue
        value = str(item.get(value_field, "")).strip()
        if not value:
            continue

        label_text = ""
        if missing_arg == "subscription_id":
            label_text = _build_subscription_picker_label(item, value)
        else:
            label_parts = []
            for field in label_fields:
                field_name = str(field).strip()
                if not field_name:
                    continue
                if field_name in item:
                    field_value = item.get(field_name)
                    if field_value and str(field_value).strip():
                        label_parts.append(str(field_value).strip())
            if label_parts:
                label_text = " | ".join(label_parts[:3])
            else:
                label_text = f"Opzione {count + 1}"

        token = uuid.uuid4().hex[:12]
        core.ARG_PICKER_TOKENS[token] = {
            "command_name": command_name,
            "arg": missing_arg,
            "value": value,
        }
        keyboard.add(InlineKeyboardButton(
            str(label_text or value)[:60], callback_data=f"pickarg:{token}"))
        count += 1

    if count == 0:
        core.bot.send_message(chat_id, "ℹ️ Nessuna opzione valida trovata.")
        return

    pretty_arg_name = "notifica" if missing_arg == "subscription_id" else missing_arg
    core.bot.send_message(
        chat_id, f"Seleziona {pretty_arg_name}:", reply_markup=keyboard)


def strip_formatter_intro(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    intro_prefixes = ("ciao", "salve", "ecco", "qui", "sure", "here", "certo")

    cleaned: list[str] = []
    intro_skipped = False
    for line in lines:
        stripped = line.strip()
        if not intro_skipped and stripped:
            lowered = stripped.lower()
            if lowered.startswith(intro_prefixes):
                intro_skipped = True
                continue
        cleaned.append(line)

    output = "\n".join(cleaned).strip()
    return output or str(text or "").strip()


def format_command_payload_with_oracle(command_name: str, payload: Any, response_prompt: str = "") -> str | None:
    request_payload = {
        "command": command_name,
        "payload": payload,
        "response_prompt": response_prompt,
        "client_instructions": core.TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS,
    }
    try:
        response = requests.post(
            core.ORACLE_FORMAT_API_URL, json=request_payload, timeout=12)
        if response.status_code != 200:
            return None
        text = str((response.json() or {}).get("text", "")).strip()
        if not text:
            return None
        return strip_formatter_intro(text)
    except Exception:
        return None


def render_direct_command_output(command_name: str, payload: Any, response_mode: str = "raw_json", response_prompt: str = "") -> tuple[str, str]:
    mode = str(response_mode or "raw_json").strip().lower()
    normalized_command = str(command_name or "").strip().lower()

    # Dedicated formatters — always preferred over Oracle for structured data
    if normalized_command == "scout_listings":
        formatted_listings = format_scout_listings(payload)
        if formatted_listings:
            return formatted_listings, "HTML"

    if normalized_command == "notifiche_attive":
        formatted_subs = format_subscriptions_list(payload)
        if formatted_subs:
            return formatted_subs, "HTML"

    if normalized_command == "avvisi_recenti":
        formatted_alerts = format_recent_alerts(payload)
        if formatted_alerts:
            return formatted_alerts, "HTML"

    if normalized_command == "preferenze_attive":
        formatted_preferences = format_active_preferences(payload)
        if formatted_preferences:
            return formatted_preferences, "HTML"

    # Default Oracle natural formatting
    if mode == "oracle_natural":
        formatted = format_command_payload_with_oracle(
            command_name=command_name, payload=payload, response_prompt=response_prompt)
        if formatted:
            return formatted, "Markdown"
        return core.format_payload_raw(payload), "Markdown"

    if mode == "text":
        return str(payload), "plain"

    return core.format_payload_raw(payload), "Markdown"


def discover_commands_from_hub() -> dict[str, dict[str, Any]]:
    try:
        response = requests.get(
            f"{core.HUB_API_URL}/discovery/commands", params={"client": "telegram"}, timeout=6)
        if response.status_code != 200:
            return {}
        commands = response.json().get("commands", []) or []
        discovered: dict[str, dict[str, Any]] = {}
        for item in commands:
            if not isinstance(item, dict):
                continue
            command_name = str(item.get("command", "")).strip().lower()
            if not command_name:
                continue
            discovered[command_name] = item
        return discovered
    except Exception:
        return {}


def fetch_registry_revision() -> int | None:
    try:
        response = requests.get(
            f"{core.HUB_API_URL}/registry/revision", timeout=5)
        if response.status_code != 200:
            return None
        payload = response.json() or {}
        return int(payload.get("revision", 0))
    except Exception:
        return None


def refresh_command_registry(force: bool = False) -> bool:
    revision = fetch_registry_revision()
    if revision is None and not force:
        return False
    if not force and revision is not None and revision == core.COMMAND_REGISTRY_REVISION:
        return False

    discovered = discover_commands_from_hub()
    with core.COMMAND_REGISTRY_LOCK:
        core.COMMAND_REGISTRY = discovered
        if revision is not None:
            core.COMMAND_REGISTRY_REVISION = revision
    setup_commands()
    return True


def watch_command_registry_loop():
    interval = max(5, core.TELEGRAM_COMMAND_REFRESH_SECONDS)
    while True:
        try:
            refresh_command_registry(force=False)
        except Exception:
            pass
        time.sleep(interval)


def register_telegram_service() -> bool:
    payload = {
        "name": "telegram",
        "base_url": core.TELEGRAM_BASE_URL,
        "health_endpoint": "/health",
        "service_type": "integration",
        "service_version": "1.0.0",
        "tags": ["integration", "messaging", "chat"],
        "capabilities": {
            "interface": "telegram",
            "hub_events_webhook": "/api/events/registry-changed",
        },
    }
    try:
        response = requests.post(
            f"{core.HUB_API_URL}/registry/register", json=payload, timeout=6)
        return response.status_code == 200
    except Exception:
        return False


def get_local_command_items(surface: str = "menu") -> list[tuple[str, dict[str, Any]]]:
    visible: list[tuple[str, dict[str, Any]]] = []
    local_items = sorted(core.LOCAL_COMMANDS.items(), key=lambda item: item[0])

    for command_name, command_payload in local_items:
        if not bool(command_payload.get("telegram_visible", True)):
            continue
        if surface == "menu" and command_payload.get("telegram_menu_visible") is False:
            continue
        if surface == "help" and command_payload.get("telegram_help_visible") is False:
            continue
        visible.append((command_name, command_payload))

    return visible


def get_visible_command_items(surface: str = "menu") -> list[tuple[str, dict[str, Any]]]:
    visible_map: dict[str, dict[str, Any]] = {}

    for command_name, command_payload in get_local_command_items(surface=surface):
        visible_map[command_name] = command_payload

    with core.COMMAND_REGISTRY_LOCK:
        command_items = sorted(
            core.COMMAND_REGISTRY.items(), key=lambda item: item[0])

    for command_name, command_payload in command_items:
        if command_name in core.TELEGRAM_HIDDEN_DYNAMIC_COMMANDS:
            continue
        service_name = str(command_payload.get("service", "")).strip().lower()
        response_mode = str(command_payload.get(
            "response_mode", "raw_json")).strip().lower()
        explicitly_visible = bool(
            command_payload.get("telegram_visible", False))
        if service_name in core.TELEGRAM_HIDDEN_COMMAND_SERVICES and not explicitly_visible:
            continue
        if response_mode == "raw_json" and not explicitly_visible:
            continue
        if surface == "menu" and command_payload.get("telegram_menu_visible") is False:
            continue
        if surface == "help" and command_payload.get("telegram_help_visible") is False:
            continue
        if command_name not in visible_map:
            visible_map[command_name] = command_payload

    return sorted(visible_map.items(), key=lambda item: item[0])


def build_commands_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons: list[InlineKeyboardButton] = []

    for command_name, command_payload in get_visible_command_items(surface="menu"):
        title = str(command_payload.get("title", command_name)
                    ).strip() or command_name
        buttons.append(InlineKeyboardButton(
            title[:62], callback_data=f"run:{command_name}"))

    for index in range(0, len(buttons), 2):
        if index + 1 < len(buttons):
            keyboard.row(buttons[index], buttons[index + 1])
        else:
            keyboard.row(buttons[index])

    return keyboard


def setup_commands():
    """Register commands with Telegram's native menu - ignores telegram_menu_visible"""
    commands = []

    # Get all commands for Telegram native menu (ignoring telegram_menu_visible filter)
    visible_map: dict[str, dict[str, Any]] = {}

    # Add local commands (only check telegram_visible, not telegram_menu_visible)
    for command_name, command_payload in sorted(core.LOCAL_COMMANDS.items(), key=lambda item: item[0]):
        if bool(command_payload.get("telegram_visible", True)):
            visible_map[command_name] = command_payload

    # Add dynamic commands from registry
    with core.COMMAND_REGISTRY_LOCK:
        command_items = sorted(
            core.COMMAND_REGISTRY.items(), key=lambda item: item[0])

    for command_name, command_payload in command_items:
        if command_name in core.TELEGRAM_HIDDEN_DYNAMIC_COMMANDS:
            continue
        service_name = str(command_payload.get("service", "")).strip().lower()
        response_mode = str(command_payload.get(
            "response_mode", "raw_json")).strip().lower()
        explicitly_visible = bool(
            command_payload.get("telegram_visible", False))

        if service_name in core.TELEGRAM_HIDDEN_COMMAND_SERVICES and not explicitly_visible:
            continue
        if response_mode == "raw_json" and not explicitly_visible:
            continue

        if command_name not in visible_map:
            visible_map[command_name] = command_payload

    # Build command list for Telegram
    for command_name, command_payload in sorted(visible_map.items(), key=lambda item: item[0]):
        title = str(command_payload.get(
            "title", command_payload.get("description", command_name))).strip()
        commands.append(BotCommand(command_name, title[:256]))

    core.bot.set_my_commands(commands)
    if core.ALLOWED_USER_ID and str(core.ALLOWED_USER_ID).isdigit():
        try:
            core.bot.set_my_commands(commands, scope=BotCommandScopeChat(
                chat_id=int(str(core.ALLOWED_USER_ID))))
        except Exception:
            pass
    print(
        f"[*] Telegram Command Menu updated successfully ({len(commands)} commands).")


def prompt_clear_confirmation(chat_id: int):
    old_session_id = core.get_session(str(chat_id))
    token = uuid.uuid4().hex[:12]
    core.PENDING_CONFIRMATIONS[token] = {
        "action": "clear",
        "chat_id": str(chat_id),
        "session_id": old_session_id,
    }

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("✅ Conferma", callback_data=f"confirm:{token}"),
        InlineKeyboardButton("❌ Annulla", callback_data=f"cancel:{token}"),
    )
    core.bot.send_message(
        chat_id, "Vuoi davvero cancellare la memoria di questa chat?", reply_markup=keyboard)


def execute_local_command(command_name: str, chat_id: int, raw_args_text: str):
    normalized = str(command_name or "").strip().lower()
    args_text = str(raw_args_text or "").strip()

    if normalized == "start":
        refresh_command_registry(force=False)
        core.bot.send_message(
            chat_id,
            "🏛️ <b>Hestia pronta</b>\nScegli un comando dai pulsanti qui sotto.",
            parse_mode="HTML",
            reply_markup=build_commands_keyboard(),
        )
        return

    if normalized == "help":
        refresh_command_registry(force=False)
        lines = ["📘 <b>Guida comandi</b>", "Comandi principali disponibili:"]
        for cmd_name, cmd_payload in get_visible_command_items(surface="help"):
            title = str(cmd_payload.get("title", cmd_name)).strip() or cmd_name
            arguments_help = str(cmd_payload.get("arguments_help", "")).strip()
            usage = f"/{cmd_name}"
            if arguments_help:
                usage += f" {arguments_help}"
            lines.append(f"• <b>{usage}</b> — {title}")
        core.bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
        return

    if normalized == "clear":
        prompt_clear_confirmation(chat_id)
        return

    if normalized == "set":
        if not args_text:
            prompt_set_parameter_picker(chat_id)
            return
        # Backward compatible path, but primary UX is next-message input flow.
        if "=" in args_text:
            key, _, value = args_text.partition("=")
            if not key.strip() or not value.strip():
                core.bot.send_message(
                    chat_id, "Uso: /set <parametro> (poi inserisci il valore nel prossimo messaggio)")
                return
            normalized_key = re.sub(r"[^a-z0-9_]", "", key.strip().lower())
            if len(normalized_key) < 2:
                core.bot.send_message(chat_id, "Parametro non valido.")
                return
            core.set_session_setting(
                str(chat_id), normalized_key, value.strip())
            core.bot.send_message(
                chat_id, f"✅ Impostazione sessione aggiornata: {normalized_key}={value.strip()}")
            return

        normalized_key = re.sub(r"[^a-z0-9_]", "", args_text.strip().lower())
        if len(normalized_key) < 2:
            core.bot.send_message(chat_id, "Parametro non valido.")
            return

        core.PENDING_WORKFLOWS[str(chat_id)] = {
            "action": "set_parameter_value",
            "parameter": normalized_key,
            "created_at": time.time(),
        }
        core.bot.send_message(
            chat_id,
            f"✍️ Scrivi ora il valore per <b>{normalized_key}</b> nel prossimo messaggio.",
            parse_mode="HTML",
            reply_markup=_cancel_input_keyboard(),
        )
        return

    if normalized == "settings":
        settings = core.get_session_settings(str(chat_id))
        if not settings:
            core.bot.send_message(
                chat_id, "Nessuna impostazione sessione attiva.")
            return
        lines = ["<b>Impostazioni sessione</b>"]
        for key, value in settings.items():
            lines.append(f"• <b>{key}</b>: {value}")
        core.bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
        return

    if normalized == "reset_settings":
        core.reset_session_settings(str(chat_id))
        core.bot.send_message(chat_id, "🧹 Impostazioni sessione resettate.")
        return

    if normalized == "notifica_add":
        core.PENDING_WORKFLOWS[str(chat_id)] = {
            "action": "notification_add",
            "created_at": time.time(),
        }
        core.bot.send_message(
            chat_id,
            "Dimmi che notifica vuoi creare (dominio, evento, filtri). Il prossimo messaggio verrà eseguito come comando rapido notifica, non come chat normale.",
            reply_markup=_cancel_input_keyboard(),
        )
        return

    if normalized == "notifica_get":
        execute_direct_command("notifiche_attive", chat_id, "")
        return

    if normalized == "notifica_remove":
        execute_direct_command("notifica_disattiva", chat_id, args_text)
        return


def execute_direct_command(command_name: str, chat_id: int, raw_args_text: str):
    normalized_command = str(command_name or "").strip().lower()
    if normalized_command in COMMAND_ALIASES:
        normalized_command = COMMAND_ALIASES[normalized_command]

    local_command = core.LOCAL_COMMANDS.get(normalized_command)
    if local_command:
        execute_local_command(normalized_command, chat_id, raw_args_text)
        return

    with core.COMMAND_REGISTRY_LOCK:
        command = core.COMMAND_REGISTRY.get(normalized_command)
    if not command:
        print(
            f"[-] Command not available: requested={command_name} normalized={normalized_command}")
        core.bot.send_message(chat_id, "Comando non disponibile.")
        return

    if str(command.get("response_mode", "")).strip().lower() == "telegram_local":
        execute_local_command(normalized_command, chat_id, raw_args_text)
        return

    parsed_args = parse_command_arguments(raw_args_text)
    required_args = extract_required_args(
        str(command.get("arguments_help", "")).strip())
    missing_required = [arg for arg in required_args if arg not in parsed_args]
    if missing_required:
        missing_arg = missing_required[0]
        arg_picker = command.get("arg_picker") if isinstance(
            command.get("arg_picker"), dict) else {}
        picker_arg = str(arg_picker.get("arg", "")).strip().lower()

        if arg_picker and picker_arg == missing_arg:
            open_arg_picker(chat_id, command_name, command, missing_arg)
        else:
            start_text_input_flow(
                chat_id=chat_id,
                command_name=normalized_command,
                command_meta=command,
                missing_arg=missing_arg,
                parsed_args=parsed_args,
            )
        return

    # Special case: notifica_disattiva requires confirmation
    if normalized_command == "notifica_disattiva":
        subscription_id = parsed_args.get("subscription_id")
        if not subscription_id:
            core.bot.send_message(chat_id, "⚠️ ID notifica non valido.")
            return

        token = uuid.uuid4().hex[:12]
        core.PENDING_CONFIRMATIONS[token] = {
            "action": "notifica_disattiva",
            "chat_id": str(chat_id),
            "subscription_id": subscription_id,
            "command": command,
            "parsed_args": parsed_args,
        }

        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                "✅ Disattiva", callback_data=f"confirm_cmd:{token}"),
            InlineKeyboardButton(
                "❌ Annulla", callback_data=f"cancel_cmd:{token}"),
        )

        short_id = str(subscription_id)[:8]
        core.bot.send_message(
            chat_id,
            f"⚠️ Sei sicuro di voler disattivare la notifica selezionata (<code>{short_id}</code>)?",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    ok, payload = route_command_from_metadata(command, chat_id, parsed_args)
    if not ok:
        print(f"[CMD] Command /{normalized_command} failed: {payload}")
        core.bot.send_message(
            chat_id, f"⚠️ Errore comando /{normalized_command}: {payload}")
        return

    response_mode = str(command.get(
        "response_mode", "raw_json")).strip().lower()
    response_prompt = str(command.get("response_prompt", "")).strip()
    print(
        f"[CMD] Rendering /{normalized_command} response_mode={response_mode}")
    output, parse_mode = render_direct_command_output(
        normalized_command, payload, response_mode, response_prompt)
    print(
        f"[CMD] Output for /{normalized_command}: {len(output)} chars, parse_mode={parse_mode}")

    core.send_user_message(chat_id, output, parse_mode=parse_mode)
