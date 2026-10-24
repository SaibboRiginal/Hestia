"""Telegram visual grammar (docs/work/2026-10-23-telegram-da-zero §3) — every message is built from these.

Rules: bold title, plain body, italic for secondary info and outcomes, ``•`` items, ``·`` separator inside a line.
At most one marker per message, on its title line: a tone dot (notifications, outcomes, errors) or the area emoji
(area buttons, result titles). No other emoji, no module names, no ids, no exceptions in user texts.
"""
from __future__ import annotations

import re
import unicodedata
from html import escape
from typing import Any, Iterable

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# The same ``tone`` the WebUI colours its icons with.
TONE_DOT = {"danger": "🔴", "error": "🔴", "warning": "🟠", "success": "🟢", "ok": "🟢", "info": "🔵"}
LEVEL_TONE = {"error": "danger", "critical": "danger", "warning": "warning", "success": "success", "info": "info"}

LABEL_MAX = 24          # longest button text (cut on a word with «…»)
PAIR_MAX = 18           # longer than this: the button gets its own row
LIST_PAGE = 8           # items per page in lists of actions / results

BACK = "‹ Indietro"
HOME = "Home"
CANCEL = "Annulla"
CONFIRM = "Conferma"
SKIP = "Salta"
MORE = "Altre ›"
CLOSE = "Chiudi"


def tone_dot(tone: str | None) -> str:
    return TONE_DOT.get(str(tone or "").lower(), "")


def _is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    if ch in "‍️︎⃣":
        return True
    if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or 0x1F1E6 <= cp <= 0x1F1FF:
        return True
    if 0x2190 <= cp <= 0x21FF or 0x2300 <= cp <= 0x23FF or 0x25A0 <= cp <= 0x25FF:
        return ch not in "‹›•·—"
    return unicodedata.category(ch) == "So"


def strip_emoji(text: Any) -> str:
    """Leading/trailing emoji (and stray ones) out of a title or label: the safety net for module texts."""
    raw = str(text or "")
    out = "".join(ch for ch in raw if not _is_emoji_char(ch))
    return re.sub(r"\s{2,}", " ", out).strip(" -·:")


def label(text: Any, limit: int = LABEL_MAX) -> str:
    """Button text: no emoji, cut on a word with «…»."""
    clean = strip_emoji(text) or str(text or "").strip()
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (cut or clean[: limit - 1]) + "…"


def esc(text: Any) -> str:
    return escape(str(text if text is not None else ""), quote=False)


def title_line(text: str, *, marker: str = "", tone: str | None = None, crumbs: Iterable[str] = ()) -> str:
    """``🔵 <b>Title</b>`` or ``🏋️ <b>Aree › Allenamento</b>``."""
    parts = [p for p in [*crumbs, text] if p]
    body = " › ".join(esc(strip_emoji(p) or p) for p in parts)
    mark = tone_dot(tone) or marker
    return f"{mark} <b>{body}</b>".strip()


def card(title: str, lines: Iterable[str] = (), *, subtitle: str = "", marker: str = "", tone: str | None = None,
         crumbs: Iterable[str] = (), detail: str = "", footer: str = "") -> str:
    """One message body. ``lines`` are already HTML (use :func:`item` / :func:`esc`)."""
    out = [title_line(title, marker=marker, tone=tone, crumbs=crumbs)] if title else []
    if subtitle:
        out.append(f"<i>{esc(subtitle)}</i>")
    body = [ln for ln in lines if ln]
    if body:
        out.append("\n".join(body))
    if detail:
        out.append(f"<blockquote expandable>{detail}</blockquote>")
    if footer:
        out.append(f"<i>{esc(footer)}</i>")
    return "\n".join(out)


def item(title: str, meta: Iterable[str] = (), url: str = "") -> str:
    """``• Title · meta · meta`` (title linked when there is a url)."""
    name = esc(strip_emoji(title) or title)
    if url and re.match(r"^https?://", str(url)):
        name = f'<a href="{escape(str(url), quote=True)}">{name}</a>'
    extra = [esc(m) for m in meta if str(m or "").strip()]
    return "• " + " · ".join([name, *extra])


def outcome(text: str, tone: str = "success") -> str:
    return f"{tone_dot(tone)} <b>{esc(text)}</b>".strip()


def note(text: str) -> str:
    return f"<i>{esc(text)}</i>"


def error(what: str, hint: str = "Riprova tra poco.") -> str:
    """Never the exception: what failed in words + what to do."""
    return f"{TONE_DOT['danger']} <b>{esc(what)}</b>" + (f"\n{esc(hint)}" if hint else "")


# ── keyboards ────────────────────────────────────────────────────────────────

def button(text: str, data: str = "", *, url: str = "", copy: str = "", web_app: str = "", style: str = "",
           icon: str = "", disabled: bool = False, limit: int = LABEL_MAX) -> InlineKeyboardButton:
    """``style``: Telegram button colour — ``primary`` (blue: the main action), ``success`` (green: confirm, done),
    ``danger`` (red: delete, stop). ``icon``: a custom emoji id (works when the owner has Telegram Premium).
    ``disabled``: a status line that does nothing (e.g. «Fatto · da WebUI»)."""
    shown = label(text, limit)
    extra: dict[str, Any] = {}
    if style in ("primary", "success", "danger"):
        extra["style"] = style
    if icon:
        extra["icon_custom_emoji_id"] = str(icon)
    if disabled:
        from telebot.types import DisabledButton
        return InlineKeyboardButton(shown, disabled=DisabledButton(), **extra)
    if url:
        return InlineKeyboardButton(shown, url=url, **extra)
    if web_app:
        from telebot.types import WebAppInfo
        return InlineKeyboardButton(shown, web_app=WebAppInfo(web_app), **extra)
    if copy:
        from telebot.types import CopyTextButton
        return InlineKeyboardButton(shown, copy_text=CopyTextButton(copy[:256]), **extra)
    return InlineKeyboardButton(shown, callback_data=data[:64], **extra)


def keyboard(rows: Iterable[Iterable[InlineKeyboardButton]]) -> InlineKeyboardMarkup | None:
    clean = [list(r) for r in rows if r]
    clean = [r for r in clean if r]
    return InlineKeyboardMarkup(keyboard=clean) if clean else None


def grid(buttons: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
    """Two per row (three for very short labels), never a long label squeezed."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in buttons:
        if len(b.text) > PAIR_MAX:
            if row:
                rows.append(row)
                row = []
            rows.append([b])
            continue
        row.append(b)
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def plain(html: str) -> str:
    """HTML card → plain text (fallback when Telegram refuses an entity)."""
    text = re.sub(r"<br\s*/?>", "\n", str(html or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
