import os
import json
import re
from html import escape as html_escape
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


_SIGNAL_STYLE_ALLOWED = {"minimal", "compact", "rich"}

_ALLOWED_TELEGRAM_HTML_TAGS = {"b", "i", "u", "s", "code", "pre", "a", "br"}
_TELEGRAM_HTML_TAG_ALIASES = {
    "strong": "b",
    "em": "i",
    "ins": "u",
    "strike": "s",
    "del": "s",
}


class _TelegramHTMLSanitizer(HTMLParser):
    """Normalize lightweight HTML to Telegram-compatible tags and nesting."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._stack: list[str] = []

    def _normalize_tag(self, tag: str) -> str:
        normalized = str(tag or "").strip().lower()
        return _TELEGRAM_HTML_TAG_ALIASES.get(normalized, normalized)

    def _push_start_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = ""
            for key, value in attrs:
                if str(key or "").strip().lower() != "href":
                    continue
                candidate = str(value or "").strip()
                if candidate.startswith("http://") or candidate.startswith("https://"):
                    href = candidate
                    break
            if not href:
                return
            self._parts.append(f'<a href="{html_escape(href, quote=True)}">')
            self._stack.append("a")
            return

        if tag == "br":
            self._parts.append("<br>")
            return

        self._parts.append(f"<{tag}>")
        self._stack.append(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = self._normalize_tag(tag)
        if normalized not in _ALLOWED_TELEGRAM_HTML_TAGS:
            return
        self._push_start_tag(normalized, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = self._normalize_tag(tag)
        if normalized == "br":
            self._parts.append("<br>")
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = self._normalize_tag(tag)
        if normalized not in _ALLOWED_TELEGRAM_HTML_TAGS or normalized == "br":
            return
        if normalized not in self._stack:
            return

        # Close any nested tags first so the final output has valid nesting.
        while self._stack:
            top = self._stack.pop()
            self._parts.append(f"</{top}>")
            if top == normalized:
                break

    def handle_data(self, data: str) -> None:
        self._parts.append(html_escape(data or "", quote=False))

    def close_and_render(self) -> str:
        self.close()
        while self._stack:
            self._parts.append(f"</{self._stack.pop()}>")
        return "".join(self._parts)


def normalize_telegram_html(text: str) -> str:
    """Return HTML that is safe for Telegram parse_mode=HTML."""
    raw = str(text or "")
    if not raw.strip():
        return ""

    sanitizer = _TelegramHTMLSanitizer()
    try:
        sanitizer.feed(raw)
        return sanitizer.close_and_render().strip()
    except Exception:
        # Safety net: minimal alias normalization if parser unexpectedly fails.
        fallback = raw.replace("<strong>", "<b>").replace("</strong>", "</b>")
        fallback = fallback.replace("<em>", "<i>").replace("</em>", "</i>")
        return fallback.strip()


def html_to_plain_text(text: str) -> str:
    """Convert HTML-ish content to plain text fallback for resilient delivery."""
    raw = str(text or "")
    if not raw.strip():
        return ""
    normalized = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    normalized = re.sub(r"</(p|div|li)>", "\n",
                        normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    normalized = unescape(normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_signal_style(value: str | None, fallback: str = "minimal") -> str:
    style = str(value or "").strip().lower()
    return style if style in _SIGNAL_STYLE_ALLOWED else fallback


def _parse_signal_style_overrides(raw: str) -> dict[str, str]:
    # Format: "memory=minimal,subscription=minimal,action=compact,default=minimal"
    out: dict[str, str] = {}
    for part in str(raw or "").split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        normalized_key = str(key).strip().lower()
        if not normalized_key:
            continue
        out[normalized_key] = _normalize_signal_style(
            str(value).strip().lower(), fallback="minimal"
        )
    return out


_TELEGRAM_SIGNAL_STYLE = _normalize_signal_style(
    os.getenv("TELEGRAM_SIGNAL_STYLE", "minimal"),
    fallback="minimal",
)
_TELEGRAM_SIGNAL_STYLE_BY_FAMILY = _parse_signal_style_overrides(
    os.getenv("TELEGRAM_SIGNAL_STYLE_BY_FAMILY", "")
)


def _signal_family(event: str) -> str:
    normalized = str(event or "").strip().lower()
    if normalized.startswith("memory."):
        return "memory"
    if normalized.startswith("subscription."):
        return "subscription"
    if normalized.startswith("action."):
        return "action"
    return "other"


def _resolve_signal_style(signal: dict[str, Any], event: str) -> str:
    family = _signal_family(event)
    override = _TELEGRAM_SIGNAL_STYLE_BY_FAMILY.get(family) or _TELEGRAM_SIGNAL_STYLE_BY_FAMILY.get(
        "default"
    )
    style = _normalize_signal_style(override, fallback=_TELEGRAM_SIGNAL_STYLE)

    # Optional per-signal client override (keeps payload canonical while client chooses rendering).
    ui = signal.get("ui") if isinstance(signal.get("ui"), dict) else {}
    telegram_ui = ui.get("telegram") if isinstance(
        ui.get("telegram"), dict) else {}
    forced = _normalize_signal_style(
        str(telegram_ui.get("style") or "").strip().lower(), fallback=style
    )
    return forced


def prettify_link_label(label: str, url: str) -> str:
    clean_label = (label or "").strip()
    if clean_label and len(clean_label) <= 80 and not clean_label.startswith("http"):
        return clean_label

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "").strip() or "link"
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            return f"{domain} / {' / '.join(path_parts[:2])}"
        return domain
    except Exception:
        return "Apri link"


def sanitize_telegram_html(text: str) -> str:
    """Strip or fix common LLM HTML mistakes that Telegram rejects.

    Telegram only supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href=\"...\">.
    Everything else (style attrs, self-closing tags, <br/>, <div>, etc.) is stripped.
    """
    # Remove inline style attributes (Telegram ignores them and they break parsing)
    text = re.sub(r'\s*style\s*=\s*"[^"]*"', '', text)
    text = re.sub(r"\s*style\s*=\s*'[^']*'", '', text)
    # Fix self-closing tags: <b/> → remove, <i/> → remove, etc.
    text = re.sub(r'<(b|i|u|s|code|pre)\s*/>', '', text, flags=re.IGNORECASE)
    # Remove <br/> and <br> (not valid in Telegram)
    text = re.sub(r'<br\s*/?>', '', text, flags=re.IGNORECASE)
    # Remove invalid tags: <div>, <span>, <p>, <h1>-<h6>, <ul>, <ol>, <li>
    for tag in ('div', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li'):
        text = re.sub(rf'<{tag}[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(rf'</{tag}>', '', text, flags=re.IGNORECASE)
    return text


def format_for_telegram(text: str) -> str:
    def convert_markdown_link(match: re.Match) -> str:
        label = match.group(1)
        url = match.group(2)
        pretty_label = prettify_link_label(label, url)
        return f'<a href="{url}">{pretty_label}</a>'

    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)',
                  convert_markdown_link, text)
    text = re.sub(r'^#+\s+(.*)', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    # Convert markdown bullet starters (both * and -) to bullet symbol
    text = re.sub(r'^[*\-]\s+', '• ', text, flags=re.MULTILINE)
    return text


def split_long_message(text: str, max_length: int = 4000) -> list[str]:
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_length:
        split_point = remaining.rfind("\n", 0, max_length)
        if split_point <= 0:
            # No newline found (or newline is at the very start — would not advance).
            # Fall back to a hard split at max_length so the loop always progresses.
            split_point = max_length
        chunk = remaining[:split_point]
        # If we're splitting inside an unclosed <pre> block, close it here and
        # reopen it in the next chunk so Telegram can parse entities correctly.
        open_pre = chunk.count("<pre>")
        close_pre = chunk.count("</pre>")
        if open_pre > close_pre:
            chunk = chunk + "</pre>"
            remaining = "<pre>" + remaining[split_point:]
        else:
            remaining = remaining[split_point:]
        chunks.append(chunk)

    if remaining:
        chunks.append(remaining)
    return chunks


def _split_html_link_bullets(html_text: str) -> list[str]:
    """Split HTML content so that each block containing a link becomes its own message.

    Handles both:
    - Bullet lists where each bullet has a link (one message per bullet-link)
    - Block-separated content (double newline) where blocks contain links
    """
    text = normalize_telegram_html(str(html_text or "")).strip()
    if not text:
        return []

    def has_link(segment: str) -> bool:
        return bool(re.search(r"<a\s+href=", segment, flags=re.IGNORECASE))

    # Split into blocks by double newline (property cards, paragraphs)
    blocks = re.split(r"\n\s*\n", text)

    # If there are multiple blocks and at least one has a link, split per block
    link_blocks = [b for b in blocks if has_link(b.strip())]
    if len(blocks) > 1 and link_blocks:
        messages: list[str] = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                continue
            messages.extend(split_long_message(stripped))
        return [m for m in messages if m.strip()]

    # Fallback: check for bullet-per-line splitting
    lines = [line.rstrip() for line in text.splitlines()]

    def is_bullet_line(line: str) -> bool:
        stripped = line.strip().lower()
        return bool(
            stripped.startswith(("•", "-", "*", "<li"))
            or stripped.startswith("&bull;")
        )

    bullet_link_lines = [
        line for line in lines if is_bullet_line(line) and has_link(line)]
    if not bullet_link_lines:
        return split_long_message(text)

    messages = []
    intro_lines = [line for line in lines if line not in bullet_link_lines]
    intro_text = "\n".join(
        [line for line in intro_lines if line.strip()]).strip()
    if intro_text:
        messages.extend(split_long_message(intro_text))

    for line in bullet_link_lines:
        rendered = line.strip()
        if rendered:
            messages.extend(split_long_message(rendered))

    return [m for m in messages if m.strip()]


def build_chat_messages(raw_markdown: str) -> list[str]:
    text = (raw_markdown or "").strip()
    if not text:
        return []

    # If the LLM already output HTML, use the HTML-aware splitter.
    # Also convert any leaked markdown (*italic*, **bold**, _italic_)
    # that may be mixed with HTML tags — the LLM doesn't always follow
    # the "no mixed formats" rule.
    if re.search(r'<(?:b|i|code|pre|br)[\s/>]|<a[\s>]', text, re.IGNORECASE):
        text = _convert_markdown_in_html(text)
        parts = _split_html_link_bullets(text)
        return parts if parts else split_long_message(text)

    # Legacy Markdown path (kept for backward compatibility / fallback models).
    # Protect code fence blocks from being split at paragraph (\n\n) boundaries.
    # Replace them with null-byte placeholders, split, then restore.
    _fence_re = re.compile(r'```.*?```', re.DOTALL)
    _fences: dict[str, str] = {}

    def _protect(m: re.Match) -> str:
        key = f"\x00FENCE{len(_fences)}\x00"
        _fences[key] = m.group(0)
        return key

    text_safe = _fence_re.sub(_protect, text)

    link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
    paragraphs = [
        part.strip()
        for part in re.split(r'\n\s*\n+', text_safe)
        if part and part.strip()
    ]

    messages: list[str] = []
    for paragraph in paragraphs:
        # Restore any fences in this paragraph before processing
        for key, fence in _fences.items():
            paragraph = paragraph.replace(key, fence)

        links = link_pattern.findall(paragraph)
        if not links:
            # Split bullet lists into individual messages
            _lines = [l.strip() for l in paragraph.splitlines() if l.strip()]
            _bullet_lines = [l for l in _lines if re.match(r"^[-*•]\s+", l)]
            if _bullet_lines and len(_bullet_lines) >= 2:
                _non_bullets = [l for l in _lines if l not in _bullet_lines]
                if _non_bullets:
                    intro = format_for_telegram("\n".join(_non_bullets)).strip()
                    if intro:
                        messages.extend(split_long_message(intro))
                for bl in _bullet_lines:
                    rendered = format_for_telegram(bl).strip()
                    if rendered:
                        messages.extend(split_long_message(rendered))
                continue
            rendered = format_for_telegram(paragraph).strip()
            if rendered:
                messages.extend(split_long_message(rendered))
            continue

        lines = [line.strip()
                 for line in paragraph.splitlines() if line.strip()]
        bullet_lines = [line for line in lines if re.match(r"^[-*•]\s+", line)]
        bullet_lines_with_links = [
            line for line in bullet_lines if link_pattern.search(line)
        ]

        if bullet_lines_with_links:
            intro_lines = [
                line for line in lines if line not in bullet_lines
            ]
            if intro_lines:
                intro_rendered = format_for_telegram(
                    "\n".join(intro_lines)).strip()
                if intro_rendered:
                    messages.extend(split_long_message(intro_rendered))

            # Process all bullet lines in original order to preserve sequence
            current_non_link_group: list[str] = []
            for bullet_line in bullet_lines:
                if bullet_line in bullet_lines_with_links:
                    # Flush any accumulated non-link bullets before this link bullet
                    if current_non_link_group:
                        rendered_non_link = format_for_telegram(
                            "\n".join(current_non_link_group)).strip()
                        if rendered_non_link:
                            messages.extend(
                                split_long_message(rendered_non_link))
                        current_non_link_group = []
                    rendered_bullet = format_for_telegram(bullet_line).strip()
                    if rendered_bullet:
                        messages.extend(split_long_message(rendered_bullet))
                else:
                    current_non_link_group.append(bullet_line)
            # Flush non-link bullets individually
            for non_link_bullet in current_non_link_group:
                rendered = format_for_telegram(non_link_bullet).strip()
                if rendered:
                    messages.extend(split_long_message(rendered))
            current_non_link_group.clear()
            continue

        paragraph_without_links = link_pattern.sub(
            lambda match: prettify_link_label(match.group(1), match.group(2)),
            paragraph,
        ).strip()
        if paragraph_without_links:
            rendered = format_for_telegram(paragraph_without_links).strip()
            if rendered:
                messages.extend(split_long_message(rendered))

        seen_urls = set()
        for label, url in links:
            normalized_url = str(url).strip()
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            pretty_label = prettify_link_label(label, normalized_url)
            messages.append(f'🔗 <a href="{normalized_url}">{pretty_label}</a>')

    return messages


def _convert_markdown_in_html(text: str) -> str:
    """Convert Markdown patterns inside HTML text WITHOUT escaping existing HTML tags.

    format_for_telegram() calls replace('<', '&lt;') which destroys valid
    <a href>, <b>, <i> tags. This function only applies markdown-to-HTML
    conversions while preserving existing HTML markup.
    """
    # Convert **bold** to <b>bold</b> (before single-* to avoid conflict)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Convert _italic_ to <i>italic</i>
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', text)
    # Convert *italic* to <i>italic</i> (single *, not at line start, not inside **)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # Convert line-start - or * bullets to • symbol
    text = re.sub(r'^[ \t]*[-*][ \t]+', '• ', text, flags=re.MULTILINE)
    return text


def build_delivery_messages(raw_text: str, parse_mode: str = "HTML") -> tuple[list[str], str | None]:
    """Build Telegram-ready messages and normalized parse mode for all outbound flows."""
    text = str(raw_text or "").strip()
    if not text:
        return [], None

    mode = str(parse_mode or "").strip().lower()

    if mode == "markdown":
        messages = build_chat_messages(text)
        if messages:
            return messages, "HTML"
        return [format_for_telegram(text)], "HTML"

    if mode == "html":
        # Sanitize invalid HTML (LLM mistakes like <b/>, style="", <br/>)
        text = sanitize_telegram_html(text)
        # Always convert leaked markdown in HTML text — the LLM often mixes
        # *italic*, **bold**, _italic_ with HTML tags despite the contract.
        # _convert_markdown_in_html is safe: it never escapes existing HTML.
        text = _convert_markdown_in_html(text)
        return _split_html_link_bullets(text), "HTML"

    return split_long_message(text), None


def strip_markdown(text: str) -> str:
    text = text.replace("**", "").replace("*", "•")
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = text.replace("`", "")
    return text


def build_signal_cards(signals: list[dict]) -> list[str]:
    if not signals:
        return []

    def _safe_inline(value: Any) -> str:
        text = format_for_telegram(str(value or "")).replace("\n", " ").strip()
        return re.sub(r"\s+", " ", text)

    cards: list[str] = []
    for signal in signals:
        event = str(signal.get("event", "")).strip().lower()
        data = signal.get("data") if isinstance(
            signal.get("data"), dict) else {}
        style = _resolve_signal_style(signal, event)

        if event == "memory.preference.added":
            fact = _safe_inline(data.get("fact", ""))
            domain = _safe_inline(data.get("domain", "general")) or "general"
            if fact:
                if style == "compact":
                    cards.append(
                        "🧠 Preferenza salvata\n"
                        f"<i>{fact}</i>"
                    )
                elif style == "rich":
                    cards.append(
                        "🧠 <b>Preferenza salvata</b>\n"
                        f"• <b>Dominio:</b> {domain}\n"
                        f"• <b>Dettaglio:</b> {fact}"
                    )
                else:
                    cards.append(f"🧠 Preferenza salvata: <i>{fact}</i>")
            else:
                cards.append("🧠 Preferenza salvata")
            continue

        if event == "memory.preference.removed":
            fact = _safe_inline(data.get("fact", ""))
            domain = _safe_inline(data.get("domain", "general")) or "general"
            if fact:
                if style == "compact":
                    cards.append(
                        "🧠 Preferenza disattivata\n"
                        f"<i>{fact}</i>"
                    )
                elif style == "rich":
                    cards.append(
                        "🧠 <b>Preferenza disattivata</b>\n"
                        f"• <b>Dominio:</b> {domain}\n"
                        f"• <b>Dettaglio:</b> {fact}"
                    )
                else:
                    cards.append(f"🧠 Preferenza disattivata: <i>{fact}</i>")
            else:
                cards.append("🧠 Preferenza disattivata")
            continue

        if event in {"subscription.added", "subscription.changed", "subscription.removed"}:
            domain = _safe_inline(data.get("domain", "general")) or "general"
            domain_suffix = "" if domain == "general" else f" ({domain})"
            filters = data.get("filters") if isinstance(
                data.get("filters"), dict) else {}
            filters_summary = _safe_inline(
                ", ".join(
                    f"{str(key).replace('_', ' ')}={value}"
                    for key, value in filters.items()
                )
            )
            if event == "subscription.added":
                if style == "compact" and filters_summary:
                    cards.append(
                        f"🔔 Notifica attivata{domain_suffix}\n"
                        f"<i>{filters_summary}</i>"
                    )
                else:
                    cards.append(f"🔔 Notifica attivata{domain_suffix}")
            elif event == "subscription.changed":
                if style == "compact" and filters_summary:
                    cards.append(
                        f"🔔 Notifica aggiornata{domain_suffix}\n"
                        f"<i>{filters_summary}</i>"
                    )
                else:
                    cards.append(f"🔔 Notifica aggiornata{domain_suffix}")
            else:
                cards.append(f"🔕 Notifica disattivata{domain_suffix}")
            continue

        if event == "action.executed":
            title = _safe_inline(data.get("title", ""))
            command = _safe_inline(data.get("command", ""))
            path = _safe_inline(data.get("path", ""))
            label = title or command or "azione"
            if style == "compact" and path:
                cards.append(
                    f"✅ Eseguito: <i>{label}</i>\n<code>{path}</code>")
            else:
                cards.append(f"✅ Eseguito: <i>{label}</i>")
            continue

        if event == "action.failed":
            title = _safe_inline(data.get("title", ""))
            command = _safe_inline(data.get("command", ""))
            error = _safe_inline(data.get("error", ""))
            label = title or command or "azione"
            if style in {"compact", "rich"} and error:
                cards.append(
                    f"❌ Non riuscito: <i>{label}</i>\n"
                    f"<i>{error[:220]}</i>"
                )
            else:
                cards.append(f"❌ Non riuscito: <i>{label}</i>")
            continue

        if event == "tool.summary":
            calls = data.get("calls") if isinstance(
                data.get("calls"), list) else []
            if not calls:
                continue
            if style == "minimal":
                tool_names = ", ".join(
                    str(c.get("tool", "?")).replace(".search", "").replace("_", " ")
                    for c in calls[:6]
                )
                cards.append(f"🔧 <b>Strumenti usati:</b> {tool_names}")
                continue
            # compact / rich: one bullet per tool call
            lines: list[str] = ["🔧 <b>Riepilogo strumenti</b>"]
            for c in calls[:8]:
                tool = str(c.get("tool", "?")).replace(".search", "")
                ok = bool(c.get("ok"))
                count = c.get("result_count")
                duration = c.get("duration_ms")
                icon = "✅" if ok else "❌"
                detail_parts: list[str] = [icon, f"<code>{tool}</code>"]
                if count is not None:
                    detail_parts.append(f"({count} risultati)")
                if duration is not None:
                    detail_parts.append(f"{duration}ms")
                lines.append(" ".join(detail_parts))
            cards.append("\n".join(lines))
            continue

        if style in {"compact", "rich"}:
            content = _safe_inline(signal.get("content", ""))
            if content:
                cards.append(f"<i>{content}</i>")

    return cards


def format_payload_raw(payload: Any) -> str:
    if isinstance(payload, (dict, list)):
        return f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    return str(payload)
