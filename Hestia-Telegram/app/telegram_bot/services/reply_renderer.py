"""Claude-like reply rendering for Telegram.

One Oracle stream → ONE answer message (split only when > 4096 chars):

    ┌ status message (reused) ──────────────────────────────┐
    │ ⏳ live status / 💭 live steps / streaming tokens ▍     │  while working
    │ ▸ 💭 Ragionamento · 3 passi   (expandable blockquote)  │  final
    │ answer…                                                │
    │ ┄                                                      │
    │ 💾 Ricordato: L'utente ha due figli                    │  notices (inline)
    └────────────────────────────────────────────────────────┘

All behaviour comes from chat_settings (thinking_display, stream_answer,
split_mode, notice_*). Notices are the standard Oracle `notice` packets.
"""
from __future__ import annotations

import logging
import re
import time
from html import escape

from telegram_bot import core
import message_format
from telegram_bot.services import chat_settings
from telegram_bot.services.chat_settings import NoticePolicy

logger = logging.getLogger("hestia_telegram.reply")

TG_LIMIT = 4000
EDIT_INTERVAL = 1.2          # Telegram tolerates ~1 edit/s per chat
MAX_STEP_LINES = 14


class ReplyRenderer:
    def __init__(self, chat_id: int, status_message_id: int, settings: dict):
        self.chat_id = chat_id
        self.msg_id = status_message_id
        self.settings = settings or {}
        self.thinking_mode = chat_settings.value(self.settings, "thinking_display")
        self.stream = chat_settings.value(self.settings, "stream_answer") == "on"
        self.split_mode = chat_settings.value(self.settings, "split_mode")
        self.policy = NoticePolicy.from_settings(self.settings)
        self.status_text = ""
        self.steps: list[str] = []
        self.tokens: list[str] = []
        self.notices: list[dict] = []
        self.tool_calls = 0
        self.answer_ids: list[int] = []      # message ids holding the final answer
        self.answer_last_html = ""
        self._last_edit = 0.0
        self._last_sent = ""
        self.finalized = False

    # ── live phase ─────────────────────────────────────────────────────────
    def on_status(self, text: str) -> None:
        self.status_text = str(text or "").strip()
        if not self.tokens:
            self._live_edit()

    def on_thinking(self, evt: dict) -> None:
        action = str(evt.get("action") or "")
        tool = str(evt.get("tool") or "")
        meta = evt.get("metadata") if isinstance(evt.get("metadata"), dict) else {}
        if action == "reasoning" and evt.get("content"):
            self.steps.append("💭 " + str(evt["content"]).strip().split("\n")[0][:180])
        elif action == "tool_call" and tool:
            self.tool_calls += 1
            self.steps.append(f"🛠 {tool}")
        elif action == "tool_result" and tool:
            n = meta.get("result_count")
            ok = "✓" if meta.get("ok") else "✗"
            self.steps.append(f"   {ok} {tool}" + (f" · {n} risultati" if n else "")
                              + (f" · {meta.get('duration_ms')} ms" if meta.get("duration_ms") else ""))
        if self.thinking_mode == "live" and not self.tokens:
            self._live_edit()

    def on_token(self, text: str) -> None:
        if not text:
            return
        self.tokens.append(str(text))
        if self.stream:
            partial = "".join(self.tokens)
            # partial HTML may be unbalanced → show it escaped, final render replaces it
            self._edit(escape(_strip_tags(partial))[-TG_LIMIT + 10:] + " ▍", parse_mode="HTML", throttle=True)

    def on_notice(self, packet: dict) -> None:
        if isinstance(packet, dict) and self.policy.allows(packet):
            self.notices.append(packet)

    # ── final phase ────────────────────────────────────────────────────────
    def on_final(self, reply: str) -> None:
        answer = str(reply or "").strip() or "".join(self.tokens).strip()
        if not answer:
            answer = "⚠️ Nessuna risposta ricevuta. Riprova (/retry)."
        html = message_format.render_answer_html(answer)
        parts = self._split(html)
        head = self._reasoning_block()
        if head:
            if len(head) + len(parts[0]) + 2 <= TG_LIMIT:
                parts[0] = f"{head}\n{parts[0]}"
            else:
                parts.insert(0, head)
        self._edit(parts[0], parse_mode="HTML", throttle=False, force=True)
        self.answer_ids = [self.msg_id]
        for part in parts[1:]:
            mid = self._send(part)
            if mid:
                self.answer_ids.append(mid)
        self.answer_last_html = parts[-1]
        self.finalized = True

    def finish(self) -> None:
        """After the stream ends: render collected notices per the user's mode."""
        if not self.finalized:
            self.on_final("".join(self.tokens))
        if not self.notices:
            return
        lines = [self._notice_line(n) for n in self.notices]
        if self.policy.mode == "separate":
            body = "\n".join(lines)
            self._send(f"<blockquote>{body}</blockquote>" if self.policy.style == "rich" else body)
            return
        # inline / important → footer under the answer (new message if it would not fit)
        footer = "\n".join(lines)
        combined = f"{self.answer_last_html}\n\n{footer}"
        last_id = self.answer_ids[-1] if self.answer_ids else None
        if last_id and len(combined) <= TG_LIMIT:
            self._edit(combined, parse_mode="HTML", throttle=False, force=True, message_id=last_id)
        else:
            self._send(footer)

    # ── helpers ────────────────────────────────────────────────────────────
    def _notice_line(self, n: dict) -> str:
        emoji = str(n.get("emoji") or "ℹ️")
        title = escape(str(n.get("title") or ""))
        detail = escape(str(n.get("detail") or ""))
        if self.policy.style == "rich":
            return f"{emoji} <b>{title}</b>" + (f"\n<i>{detail}</i>" if detail else "")
        return f"{emoji} <i>{title}{': ' + detail if detail else ''}</i>"

    def _reasoning_block(self) -> str:
        if self.thinking_mode == "hidden" or not self.steps:
            return ""
        steps = self.steps[-MAX_STEP_LINES:]
        more = len(self.steps) - len(steps)
        n_reason = sum(1 for s in self.steps if s.startswith("💭"))
        summary = f"{n_reason} passi" + (f" · {self.tool_calls} strumenti" if self.tool_calls else "")
        body = "\n".join(escape(s) for s in steps)
        if more:
            body = f"… (+{more})\n" + body
        tag = "<blockquote>" if self.thinking_mode == "detailed" else "<blockquote expandable>"
        return f"{tag}💭 <b>Ragionamento</b> · {summary}\n{body}</blockquote>"

    def _live_edit(self) -> None:
        text = f"⏳ <i>{escape(self.status_text or 'Sto lavorando…')}</i>"
        if self.thinking_mode == "live" and self.steps:
            text += "\n" + "\n".join(escape(s) for s in self.steps[-4:])
        self._edit(text, parse_mode="HTML", throttle=True)

    def _split(self, html: str) -> list[str]:
        if self.split_mode == "paragraphs" and "<pre" not in html:
            parts: list[str] = []
            for para in re.split(r"\n\s*\n", html):
                if para.strip():
                    parts.extend(message_format.split_long_message(para.strip(), TG_LIMIT))
            if parts:
                return parts
        return message_format.split_long_message(html, TG_LIMIT) or [html]

    def _edit(self, text: str, parse_mode: str = "HTML", throttle: bool = True, force: bool = False,
              message_id: int | None = None) -> None:
        now = time.monotonic()
        if throttle and not force and now - self._last_edit < EDIT_INTERVAL:
            return
        target = message_id or self.msg_id
        if text == self._last_sent and target == self.msg_id:
            return                       # Telegram rejects identical edits
        try:
            core.bot.edit_message_text(text, chat_id=self.chat_id, message_id=target,
                                       parse_mode=parse_mode, disable_web_page_preview=True)
        except Exception as exc:
            err = str(exc).lower()
            if "not modified" in err:
                pass
            elif "parse entities" in err or "can't parse" in err:
                try:
                    core.bot.edit_message_text(_strip_tags(text), chat_id=self.chat_id, message_id=target,
                                               disable_web_page_preview=True)
                except Exception as exc2:
                    logger.debug("event=reply_edit_plain_failed error=%s", exc2)
            elif "too many requests" in err or "429" in err:
                logger.debug("event=reply_edit_rate_limited")
                if force:
                    time.sleep(1.5)
                    try:
                        core.bot.edit_message_text(text, chat_id=self.chat_id, message_id=target,
                                                   parse_mode=parse_mode, disable_web_page_preview=True)
                    except Exception:
                        pass
            else:
                logger.debug("event=reply_edit_failed error=%s", exc)
        self._last_edit = time.monotonic()
        if target == self.msg_id:
            self._last_sent = text

    def _send(self, text: str) -> int | None:
        try:
            m = core.bot.send_message(self.chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
            return getattr(m, "message_id", None)
        except Exception as exc:
            logger.debug("event=reply_send_html_failed error=%s", exc)
            try:
                m = core.bot.send_message(self.chat_id, _strip_tags(text), disable_web_page_preview=True)
                return getattr(m, "message_id", None)
            except Exception as exc2:
                logger.warning("event=reply_send_failed error=%s", exc2)
                return None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
