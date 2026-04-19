import json
import re
from typing import Any
from urllib.parse import urlparse


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
        if split_point == -1:
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
    text = str(html_text or "").strip()
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

    # If the LLM already output HTML (analyst prompt now instructs HTML output),
    # use the HTML-aware splitter directly — do NOT run format_for_telegram which
    # would escape the angle brackets and destroy the markup.
    if re.search(r'<(?:b|i|a[\s>]|code|pre|br)[\s/>]', text, re.IGNORECASE):
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
            # Flush any remaining non-link bullets
            if current_non_link_group:
                rendered_non_link = format_for_telegram(
                    "\n".join(current_non_link_group)).strip()
                if rendered_non_link:
                    messages.extend(split_long_message(rendered_non_link))
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

    cards: list[str] = []
    for signal in signals:
        event = str(signal.get("event", "")).strip().lower()
        data = signal.get("data") if isinstance(
            signal.get("data"), dict) else {}

        if event == "memory.preference.added":
            fact = str(data.get("fact", "")).strip()
            domain = str(data.get("domain", "general")).strip()
            cards.append(
                "🧠 <b>Nuova preferenza salvata</b>\n"
                f"• <b>Dominio:</b> {domain}\n"
                f"• <b>Dettaglio:</b> {fact}"
            )
            continue

        if event == "memory.preference.removed":
            pref_id = str(data.get("id", "-")).strip()
            domain = str(data.get("domain", "general")).strip() or "general"
            fact = str(data.get("fact", "")).strip()
            detail_line = f"• <b>Dettaglio:</b> {fact}" if fact else "• <b>Dettaglio:</b> n/d"
            cards.append(
                "🧠 <b>Preferenza disattivata</b>\n"
                f"• <b>Dominio:</b> {domain}\n"
                f"{detail_line}\n"
                f"• <b>Riferimento ID:</b> {pref_id}"
            )
            continue

        if event in {"subscription.added", "subscription.changed", "subscription.removed"}:
            sub_id = str(data.get("subscription_id", "-")).strip()
            domain = str(data.get("domain", "general")).strip()
            filters = data.get("filters") if isinstance(
                data.get("filters"), dict) else {}
            channels = data.get("channels") if isinstance(
                data.get("channels"), list) else []

            filter_lines = []
            for key, value in filters.items():
                filter_lines.append(
                    f"• <b>{str(key).replace('_', ' ').title()}:</b> {value}")
            if not filter_lines:
                filter_lines.append("• <b>Filtri:</b> nessuno")

            channel_label = "telegram"
            target_label = "-"
            if channels and isinstance(channels[0], dict):
                channel_label = str(channels[0].get("type", "telegram"))
                target_label = str(channels[0].get("target", "-")).strip()

            if event == "subscription.added":
                title = "🔔 <b>Nuova notifica attivata</b>"
            elif event == "subscription.changed":
                title = "🔔 <b>Notifica aggiornata</b>"
            else:
                title = "🔕 <b>Notifica disattivata</b>"

            summary_parts = [f"dominio {domain}"]
            if filters:
                human_filters = ", ".join(
                    [f"{str(key).replace('_', ' ')}={value}" for key,
                     value in filters.items()]
                )
                summary_parts.append(human_filters)
            summary_line = "• <b>Regola:</b> " + " | ".join(summary_parts)

            cards.append(
                f"{title}\n"
                f"{summary_line}\n"
                f"• <b>Dominio:</b> {domain}\n"
                f"• <b>Canale:</b> {channel_label}\n"
                f"• <b>Target:</b> {target_label}\n"
                f"• <b>Riferimento ID:</b> {sub_id}\n"
                + "\n".join(filter_lines)
            )
            continue

        content = str(signal.get("content", "")).strip()
        if content:
            cards.append(f"ℹ️ <b>Aggiornamento</b>\n{content}")

    return cards


def format_payload_raw(payload: Any) -> str:
    if isinstance(payload, (dict, list)):
        return f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    return str(payload)
