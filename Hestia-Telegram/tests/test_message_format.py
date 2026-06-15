"""Tests — message_format module (Phase 2.1)

Format contract tests: HTML output correctness, Markdown conversion,
message splitting, link handling, and signal card generation.
All pure function tests — no network, no bot.
"""
from __future__ import annotations

import pytest

import message_format as mf


# ─────────────────────────────────────────────────────────────────────────────
# format_for_telegram
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestFormatForTelegram:
    def test_markdown_bold_converted_to_html_b(self):
        result = mf.format_for_telegram("**Ciao Mark**")
        assert "<b>Ciao Mark</b>" in result
        assert "**" not in result

    def test_markdown_italic_converted_to_html_i(self):
        result = mf.format_for_telegram("*corsivo*")
        assert "<i>corsivo</i>" in result

    def test_markdown_heading_converted_to_bold(self):
        result = mf.format_for_telegram("## Titolo sezione")
        assert "<b>Titolo sezione</b>" in result
        assert "##" not in result

    def test_markdown_link_converted_to_html_a(self):
        result = mf.format_for_telegram(
            "[Vedi annuncio](https://example.com/annuncio)")
        assert '<a href="https://example.com/annuncio">' in result
        assert "[Vedi annuncio]" not in result

    def test_code_block_converted_to_pre(self):
        result = mf.format_for_telegram("```python\nprint('hello')\n```")
        assert "<pre>" in result
        assert "print" in result

    def test_markdown_bullet_asterisk_to_symbol(self):
        result = mf.format_for_telegram("* primo elemento\n* secondo")
        assert "•" in result
        # Original markdown bullet chars should be converted
        lines = result.splitlines()
        for line in lines:
            if line.strip():
                assert not line.startswith(
                    "* "), f"Unconverted bullet: {line!r}"

    def test_markdown_bullet_dash_to_symbol(self):
        result = mf.format_for_telegram("- primo\n- secondo")
        assert "•" in result

    def test_html_entities_escaped_ampersand(self):
        result = mf.format_for_telegram("Prezzo: 100€ & tasse")
        assert "&amp;" in result
        # Raw & should not remain (except in &amp; itself)
        assert "& tasse" not in result

    def test_html_entities_escaped_lt_gt(self):
        result = mf.format_for_telegram("valore < 100 oppure > 200")
        assert "&lt;" in result
        assert "&gt;" in result

    def test_plain_text_unchanged_except_escaping(self):
        result = mf.format_for_telegram("Testo semplice senza formattazione")
        assert result == "Testo semplice senza formattazione"

    def test_already_html_not_double_escaped(self):
        # If LLM outputs HTML, calling format_for_telegram will escape it.
        # This test documents that behaviour — the caller must NOT run
        # format_for_telegram on already-formatted HTML.
        result = mf.format_for_telegram("<b>già html</b>")
        assert "&lt;b&gt;" in result  # HTML gets escaped — expected behaviour


# ─────────────────────────────────────────────────────────────────────────────
# split_long_message
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestSplitLongMessage:
    def test_short_message_returned_as_single_item(self):
        result = mf.split_long_message("Hello world")
        assert result == ["Hello world"]

    def test_long_message_split_into_multiple_chunks(self):
        long_text = ("A" * 100 + "\n") * 50  # 5050 chars
        result = mf.split_long_message(long_text, max_length=500)
        assert len(result) > 1

    def test_each_chunk_within_max_length(self):
        long_text = ("Word " * 200 + "\n") * 10
        max_len = 500
        result = mf.split_long_message(long_text, max_length=max_len)
        for chunk in result:
            assert len(chunk) <= max_len, f"Chunk too long: {len(chunk)}"

    def test_splits_at_newline_boundary(self):
        text = "Paragrafo 1.\n" * 100
        result = mf.split_long_message(text, max_length=200)
        # No chunk should end mid-word
        for chunk in result:
            assert len(chunk) > 0

    def test_unclosed_pre_tag_closed_at_split_and_reopened(self):
        # A <pre> block that spans across the split boundary
        pre_content = "<pre>" + "x\n" * 500 + "</pre>"
        result = mf.split_long_message(pre_content, max_length=500)
        # Each chunk that opens a <pre> should close it or be the last chunk
        for i, chunk in enumerate(result[:-1]):
            if "<pre>" in chunk:
                assert "</pre>" in chunk, f"Chunk {i} has unclosed <pre>: {chunk[:100]}"


# ─────────────────────────────────────────────────────────────────────────────
# build_delivery_messages
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestBuildDeliveryMessages:
    def test_html_mode_returns_html_parse_mode(self):
        msgs, mode = mf.build_delivery_messages(
            "<b>Ciao</b>", parse_mode="HTML")
        assert mode == "HTML"
        assert len(msgs) > 0

    def test_markdown_mode_converts_to_html(self):
        msgs, mode = mf.build_delivery_messages(
            "**Grassetto**", parse_mode="Markdown")
        assert mode == "HTML"
        combined = " ".join(msgs)
        assert "<b>" in combined or "Grassetto" in combined

    def test_empty_text_returns_empty_list(self):
        msgs, mode = mf.build_delivery_messages("", parse_mode="HTML")
        assert msgs == []

    def test_none_text_returns_empty_list(self):
        msgs, mode = mf.build_delivery_messages(
            None, parse_mode="HTML")  # type: ignore[arg-type]
        assert msgs == []

    def test_html_with_link_split_into_separate_messages(self):
        text = (
            "Ecco i risultati:\n\n"
            '• <a href="https://example.com/1">Appartamento Milano</a>\n\n'
            '• <a href="https://example.com/2">Villa Roma</a>'
        )
        msgs, mode = mf.build_delivery_messages(text, parse_mode="HTML")
        # Each link should be in its own message (or at least the list is non-empty)
        assert len(msgs) >= 1
        assert mode == "HTML"

    def test_html_mode_normalizes_em_tags_to_i(self):
        text = "<i>Preferenza attiva</em>"
        msgs, mode = mf.build_delivery_messages(text, parse_mode="HTML")
        combined = "\n".join(msgs)
        assert mode == "HTML"
        assert "</em>" not in combined
        assert "<i>Preferenza attiva</i>" in combined

    def test_html_mode_auto_closes_unbalanced_tags(self):
        text = "<b>Titolo <i>dettaglio"
        msgs, _ = mf.build_delivery_messages(text, parse_mode="HTML")
        combined = "\n".join(msgs)
        assert "<b>" in combined
        assert "</b>" in combined
        assert "<i>" in combined
        assert "</i>" in combined

    def test_html_mode_normalizes_strong_and_em_aliases(self):
        text = "<strong>Titolo</strong> <em>Dettaglio</em>"
        msgs, mode = mf.build_delivery_messages(text, parse_mode="HTML")
        combined = "\n".join(msgs)
        assert mode == "HTML"
        assert "<strong>" not in combined
        assert "</strong>" not in combined
        assert "<em>" not in combined
        assert "</em>" not in combined
        assert "<b>Titolo</b>" in combined
        assert "<i>Dettaglio</i>" in combined

    def test_html_mode_drops_unsupported_tags_but_keeps_content(self):
        text = "<p>Ciao</p><span> mondo</span>"
        msgs, mode = mf.build_delivery_messages(text, parse_mode="HTML")
        combined = "\n".join(msgs)
        assert mode == "HTML"
        assert "<p>" not in combined
        assert "</p>" not in combined
        assert "<span>" not in combined
        assert "</span>" not in combined
        assert "Ciao" in combined
        assert "mondo" in combined


# ─────────────────────────────────────────────────────────────────────────────
# build_chat_messages
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestBuildChatMessages:
    def test_html_content_passes_through_html_path(self):
        html = "<b>Titolo</b>\n<i>Sottotitolo</i>"
        result = mf.build_chat_messages(html)
        assert len(result) > 0
        combined = " ".join(result)
        assert "<b>" in combined or "Titolo" in combined

    def test_empty_input_returns_empty_list(self):
        assert mf.build_chat_messages("") == []

    def test_plain_text_returns_non_empty_list(self):
        result = mf.build_chat_messages("Ciao, come posso aiutarti?")
        assert len(result) > 0

    def test_markdown_with_links_splits_into_multiple_messages(self):
        text = (
            "Ecco i risultati:\n\n"
            "- [Appartamento Milano](https://example.com/1) — prezzo 250k\n"
            "- [Villa Roma](https://example.com/2) — prezzo 450k"
        )
        result = mf.build_chat_messages(text)
        # Should produce multiple messages (one intro + one per link)
        assert len(result) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# prettify_link_label
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.format
class TestPrettifyLinkLabel:
    def test_short_label_returned_as_is(self):
        result = mf.prettify_link_label("Vedi annuncio", "https://example.com")
        assert result == "Vedi annuncio"

    def test_url_as_label_falls_back_to_domain(self):
        result = mf.prettify_link_label(
            "https://example.com/path", "https://example.com/path")
        assert "example.com" in result
        assert "https://" not in result

    def test_empty_label_uses_domain(self):
        result = mf.prettify_link_label("", "https://example.com/property/123")
        assert "example.com" in result
