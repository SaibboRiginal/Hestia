"""Pure formatting functions — no HTTP calls, no bot interactions.

All functions receive plain Python data and return HTML strings or tuples.
"""
from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlparse

import requests

from telegram_bot import core

# ── Primitive helpers ─────────────────────────────────────────────────────────


def _format_price(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"€ {float(value):,.0f}".replace(",", ".")
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
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            return f"{domain} / {' / '.join(path_parts[:2])}"
        return domain
    except Exception:
        return "annuncio"


def _readable_filter_label(key: str) -> str:
    mapping = {
        "city": "Citta", "location": "Zona", "address": "Indirizzo",
        "price_max": "Prezzo max", "max_price": "Prezzo max", "budget_max": "Budget max",
        "price_min": "Prezzo min", "min_price": "Prezzo min",
        "surface_min": "Metratura min", "min_surface": "Metratura min",
        "surface_max": "Metratura max", "rooms_min": "Locali min",
        "min_rooms": "Locali min", "property_type": "Tipologia",
        "contract": "Contratto", "keywords": "Parole chiave",
    }
    normalized = str(key or "").strip().lower()
    return mapping.get(normalized, str(key or "").replace("_", " ").strip().title())


def _format_budget_short(value: Any) -> str:
    try:
        amount = float(value)
        return f"<= {int(amount/1000)}k" if amount >= 1000 else f"<= {int(amount)}"
    except Exception:
        return str(value or "").strip()


def _build_subscription_picker_label(item: dict[str, Any], fallback_value: str) -> str:
    filters = item.get("filters") if isinstance(
        item.get("filters"), dict) else {}
    city = str(filters.get("city") or filters.get("location") or "").strip()
    property_type = str(filters.get("property_type") or "").strip()
    rooms = str(filters.get("rooms_min")
                or filters.get("min_rooms") or "").strip()
    max_price = filters.get("price_max") or filters.get(
        "max_price") or filters.get("budget_max")

    parts: list[str] = []
    if city:
        parts.append(city)
    if property_type:
        parts.append(property_type)
    if rooms:
        parts.append(f"{rooms}+ locali")
    if max_price is not None and str(max_price).strip():
        budget = _format_budget_short(max_price)
        if budget:
            parts.append(budget)

    if parts:
        return " | ".join(parts)

    readable: list[str] = []
    for k, v in list(filters.items())[:2]:
        if v is None or not str(v).strip():
            continue
        readable.append(f"{_readable_filter_label(str(k))}: {str(v).strip()}")
    if readable:
        return " | ".join(readable)

    domain = _safe_text(item.get("domain"), "")
    if domain == "real_estate":
        return "🏠 Notifica immobili (tutti i criteri)"
    if domain:
        return f"🔔 Notifica {domain}"
    return "🔔 Notifica generale"


def _format_surface(payload: dict[str, Any]) -> str:
    specs = payload.get("specs") if isinstance(
        payload.get("specs"), dict) else {}
    for key in ("surface_m2", "m2", "surface"):
        if specs.get(key) is not None:
            return f"{specs[key]} m²"
        if payload.get(key) is not None:
            return f"{payload[key]} m²"
    return ""


# ── Domain formatters ─────────────────────────────────────────────────────────

def format_scout_listings(payload: Any, limit: int = 12) -> str | None:
    """Render real-estate listing items as HTML."""
    if not isinstance(payload, list):
        return None
    rows = [item for item in payload if isinstance(item, dict)]
    if not rows:
        return "Nessuna casa trovata."

    blocks: list[str] = []
    for item in rows[:limit]:
        title = str(item.get("title") or item.get("name")
                    or item.get("summary") or "Casa").strip()
        where = str(item.get("address") or item.get(
            "location") or item.get("city") or "").strip()
        price = _format_price(item.get("price"))
        m2 = _format_surface(item)
        link = str(item.get("url") or item.get("entity_id") or "").strip()

        parts: list[str] = []
        if link:
            parts.append(f'<a href="{link}"><b>{title}</b></a>')
        else:
            parts.append(f"<b>{title}</b>")
        if where:
            parts.append(f"📍 {where}")
        details = [x for x in [price, m2] if x]
        if details:
            parts.append(" · ".join(details))
        blocks.append("\n".join(parts))

    return f"🏠 <b>Case disponibili</b> ({len(rows)})\n\n" + "\n\n".join(blocks)


def format_subscriptions_list(payload: Any) -> str | None:
    """Render active subscriptions as HTML."""
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
            title = "Tutte le case" if domain == "real_estate" else "Notifica generale"

        lines.append(f"<b>{idx}. {title}</b>")
        if filters:
            parts = [
                f"{_safe_text(_readable_filter_label(k))}: {_safe_text(v)}"
                for k, v in list(filters.items())[:4]
                if k not in ("city", "location", "property_type") and v is not None and str(v).strip()
            ]
            if parts:
                lines.append(f"  {', '.join(parts)}")
        lines.append("")

    return "\n".join(lines)


def format_active_preferences(payload: Any) -> str | None:
    """Render active user preferences grouped by domain as HTML."""
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
    for domain in sorted(grouped):
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
    """Render recent dispatch alert entries as HTML."""
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
        price = _format_price(item.get("entity_price") or item.get("price"))
        url = str(item.get("entity_url") or item.get(
            "entity_id") or "").strip()
        when = _pretty_date(item.get("created_at"))

        if title.startswith("http"):
            title = _pretty_link_label(url) if url else "Nuova proprietà"
        safe_title = _safe_text(title, "Nuova proprietà")

        parts: list[str] = []
        if url:
            parts.append(f'<a href="{escape(url)}"><b>{safe_title}</b></a>')
        else:
            parts.append(f"<b>{safe_title}</b>")
        tokens = [x for x in [f"📍 {_safe_text(address)}" if address else "", _safe_text(
            price), _safe_text(when)] if x]
        if tokens:
            parts.append(" · ".join(tokens))
        blocks.append("\n".join(parts))

    return f"📬 <b>Avvisi recenti</b> ({len(rows)})\n\n" + "\n\n".join(blocks)


def format_documents_list(docs: list) -> tuple[str, Any]:
    """Render archived document list as HTML + inline keyboard."""
    import json as _json
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    if not docs:
        return "📭 Nessun documento archiviato.", InlineKeyboardMarkup()

    lines = [f"📎 <b>Documenti archiviati</b> ({len(docs)})"]
    keyboard_rows: list[list[InlineKeyboardButton]] = []

    for doc in docs:
        doc_id = doc.get("document_id", "?")
        title = _safe_text(doc.get("title") or doc.get(
            "filename") or "Documento senza titolo")
        is_permanent = bool(doc.get("is_permanent", False))
        perm_icon = "📌" if is_permanent else "📎"
        created = _pretty_date(doc.get("created_at", ""))
        domain = _safe_text(doc.get("domain") or "documents")
        access_count = int(doc.get("access_count") or 0)
        last_accessed = _pretty_date(doc.get("last_accessed_at") or "")

        tag_str = ""
        tags_raw = doc.get("tags")
        if tags_raw:
            try:
                tag_list = _json.loads(tags_raw) if isinstance(
                    tags_raw, str) else tags_raw
                if isinstance(tag_list, list) and tag_list:
                    tag_str = " · " + " ".join(f"#{t}" for t in tag_list[:5])
            except Exception:
                pass

        lines.append(f"\n{perm_icon} <b>{title}</b>{tag_str}")
        meta_parts = []
        if created:
            meta_parts.append(created)
        if domain and domain != "documents":
            meta_parts.append(f"🏷 {domain}")
        if access_count:
            last = f", ultimo {last_accessed}" if last_accessed else ""
            meta_parts.append(f"🔍 {access_count}×{last}")
        if meta_parts:
            lines.append(f"   <i>{' · '.join(meta_parts)}</i>")

        keyboard_rows.append([
            InlineKeyboardButton(
                "📌 Fisso" if is_permanent else "📌 Pin", callback_data=f"doc_pin:{doc_id}"),
            InlineKeyboardButton(
                "🗑️ Elimina", callback_data=f"doc_del:{doc_id}"),
        ])

    return "\n".join(lines), InlineKeyboardMarkup(keyboard_rows)


# ── Oracle-assisted formatting ─────────────────────────────────────────────────

def strip_formatter_intro(text: str) -> str:
    """Remove LLM greeting lines from a formatted response."""
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    intro_prefixes = ("ciao", "salve", "ecco", "qui", "sure", "here", "certo")
    cleaned: list[str] = []
    intro_skipped = False
    for line in lines:
        stripped = line.strip()
        if not intro_skipped and stripped and stripped.lower().startswith(intro_prefixes):
            intro_skipped = True
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip() or str(text or "").strip()


def format_command_payload_with_oracle(command_name: str, payload: Any, response_prompt: str = "") -> str | None:
    """Ask Oracle to format *payload* into natural language."""
    request_payload = {
        "command": command_name,
        "payload": payload,
        "response_prompt": response_prompt,
        "client_instructions": core.TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS,
        "thinking": False,
        "locale": core.TELEGRAM_LOCALE,
    }
    try:
        response = requests.post(
            core.ORACLE_FORMAT_API_URL, json=request_payload, timeout=30)
        if response.status_code != 200:
            return None
        text = str((response.json() or {}).get("text", "")).strip()
        return strip_formatter_intro(text) if text else None
    except Exception:
        return None


def render_direct_command_output(
    command_name: str,
    payload: Any,
    response_mode: str = "raw_json",
    response_prompt: str = "",
) -> tuple[str, str]:
    """Select and apply the best formatter for a command response.

    Returns ``(text, parse_mode)`` where parse_mode is one of
    ``"HTML"``, ``"Markdown"``, or ``"plain"``.

    Oracle rendering always takes priority when mode is ``oracle_natural``.
    Hardcoded domain formatters are used as fallback when Oracle is unavailable,
    or as the primary renderer for ``raw_json`` mode.
    """
    mode = str(response_mode or "raw_json").strip().lower()
    normalized = str(command_name or "").strip().lower()

    # ── Oracle rendering (highest priority) ──────────────────────────────────
    if mode == "oracle_natural":
        formatted = format_command_payload_with_oracle(
            command_name, payload, response_prompt)
        if formatted:
            return formatted, "HTML"
        # Oracle unavailable — fall through to hardcoded formatters below

    # ── Hardcoded domain formatters (fallback or raw_json mode) ──────────────
    if normalized == "scout_listings":
        out = format_scout_listings(payload)
        if out:
            return out, "HTML"

    if normalized == "notifiche_attive":
        out = format_subscriptions_list(payload)
        if out:
            return out, "HTML"

    if normalized == "avvisi_recenti":
        out = format_recent_alerts(payload)
        if out:
            return out, "HTML"

    if normalized == "preferenze_attive":
        out = format_active_preferences(payload)
        if out:
            return out, "HTML"

    if mode == "text":
        return str(payload), "plain"

    return core.format_payload_raw(payload), "Markdown"
