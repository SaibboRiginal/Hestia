"""Chat settings — the six options of Impostazioni › Chat (docs/work/2026-10-23-telegram-da-zero §7), one message
edited in place.

``tone``, ``mode`` and ``custom_prompt`` are stored centrally (Themis ``oracle.chat.*``, shared with every client,
see ``personal_settings.py``); ``thinking_display`` and ``notice_mode`` are Telegram presentation; voice answers are
``voice_service``. Add an option: append a Setting, the panel shows it.

Callback data ``set:menu`` · ``set:param:<key>`` · ``set:v:<key>:<value>`` · ``set:reset`` · ``set:voce``.
"""
from __future__ import annotations

from dataclasses import dataclass
from hestia_common.i18n import t as tr  # fixed texts in the owner's language


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    options: tuple[tuple[str, str], ...]
    default: str
    help: str = ""


SETTINGS: tuple[Setting, ...] = (
    Setting("tone", "Tone", (("warm", "Warm"), ("neutral", "Neutral"), ("direct", "Direct"), ("formal", "Formal")),
            "warm", "How I answer you."),
    Setting("mode", "alt::Mode",
            (("auto", "Auto · I decide"), ("quick", "Quick · no tools"),
             ("thinking", "Thoughtful · I reason and use tools"), ("cot", "Step by step · slower")),
            "auto", "How much I reason before answering."),
    Setting("thinking_display", "Reasoning",
            (("hidden", "Hidden"), ("compact", "Compact · box closed"),
             ("detailed", "Detailed · box open"), ("live", "Live · the steps while I work")),
            "compact", "How you see the steps and tools I use."),
    Setting("notice_mode", "System messages",
            (("inline", "Under the answer"), ("important", "Only important ones"), ("hidden", "pl::Hidden")),
            "inline", "Saved memory, actions done, errors."),
)

BY_KEY = {s.key: s for s in SETTINGS}
# Rendering-only keys (tone, mode, custom_prompt are applied by the assistant itself).
UI_ONLY_KEYS = {"thinking_display", "notice_mode"}
LEGACY = {"notice_mode": {"separate": "inline"}}


def value(settings: dict, key: str) -> str:
    """Current value with schema default (legacy values mapped)."""
    raw = str((settings or {}).get(key) or "").strip().lower()
    raw = LEGACY.get(key, {}).get(raw, raw)
    s = BY_KEY.get(key)
    if not s:
        return raw
    return raw if raw in {o[0] for o in s.options} else s.default


def label_of(key: str, val: str) -> str:
    s = BY_KEY.get(key)
    return dict(s.options).get(val, val) if s else val


@dataclass
class NoticePolicy:
    mode: str = "inline"

    @classmethod
    def from_settings(cls, settings: dict) -> "NoticePolicy":
        return cls(mode=value(settings, "notice_mode"))

    def allows(self, packet: dict) -> bool:
        if self.mode == "hidden":
            return str(packet.get("level") or "") == "error"
        if self.mode == "important":
            kind = str(packet.get("kind") or "info")
            return str(packet.get("level") or "info") in {"warning", "error"} or kind.startswith("action.")
        return True


# ── the panel ────────────────────────────────────────────────────────────────

def _ui():
    from telegram_bot import core, ui
    return core, ui


def panel(chat_id, message_id=None) -> None:
    core, ui = _ui()
    from telegram_bot import nav
    from telegram_bot.services import voice_service
    st = core.get_session_settings(str(chat_id))
    lines = [f"{ui.esc(tr(s.label))}: <b>{ui.esc(tr(label_of(s.key, value(st, s.key))).split(' · ')[0])}</b>"
             for s in SETTINGS]
    lines.append(tr("Spoken answers: <b>{0}</b>", tr('yes') if voice_service.is_live(chat_id) else 'no'))
    custom = str(st.get("custom_prompt") or "").strip()
    lines.append(tr("Personal instructions: ") + (f"<i>{ui.esc(custom[:120])}{'…' if len(custom) > 120 else ''}</i>"
                                            if custom else tr("<i>none</i>")))
    buttons = [ui.button(s.label, f"set:param:{s.key}") for s in SETTINGS]
    buttons += [ui.button(tr("Voice replies"), "set:voce"), ui.button(tr("Personal instructions"), "set:param:custom_prompt")]
    rows = ui.grid(buttons)
    rows.append([ui.button(tr("f::Restore"), "set:reset"), ui.button(tr("‹ Settings"), "n:imp")])
    nav.place(chat_id, ui.card(tr("Chat"), lines, crumbs=[tr("Settings")]), ui.keyboard(rows), message_id)


def option_view(chat_id, key: str, message_id=None) -> None:
    core, ui = _ui()
    from telegram_bot import nav
    s = BY_KEY[key]
    current = value(core.get_session_settings(str(chat_id)), key)
    rows = [[ui.button(("• " if v == current else "") + tr(lbl), f"set:v:{key}:{v}", limit=40)] for v, lbl in s.options]
    rows.append([ui.button(tr(ui.BACK), "set:menu")])
    nav.place(chat_id, ui.card(s.label, [ui.note(s.help)] if s.help else [], crumbs=[tr("Settings"), tr("Chat")]),
              ui.keyboard(rows), message_id)


def ask_custom_prompt(chat_id, message_id=None) -> None:
    core, ui = _ui()
    from telegram_bot import nav, store
    store.set_flow(chat_id, {"kind": "chat_setting", "key": "custom_prompt", "message_id": message_id})
    rows = [[ui.button(tr("Remove the instructions"), "set:v:custom_prompt:-")], [ui.button(ui.CANCEL, "set:menu")]]
    nav.place(chat_id, ui.card(tr("Personal instructions"), [
        tr("Write here in the chat how you want me to answer you."), ui.note(tr("E.g. be informal and get straight to the point."))],
        crumbs=[tr("Settings"), tr("Chat")]), ui.keyboard(rows), message_id)


def on_text(chat_id, text: str) -> bool:
    from telegram_bot import store
    flow = store.get_flow(chat_id)
    if not flow or flow.get("kind") != "chat_setting":
        return False
    store.clear_flow(chat_id)
    core, _ = _ui()
    new = text.strip()
    core.set_session_setting(str(chat_id), "custom_prompt", "" if new in ("-", "—") else new)
    panel(chat_id, flow.get("message_id"))
    return True


def handle(call) -> None:
    core, ui = _ui()
    chat_id, mid = call.message.chat.id, call.message.message_id
    parts = str(call.data or "").split(":")
    action = parts[1] if len(parts) > 1 else "menu"
    note = ""
    if action in ("tone", "thinking_display") and len(parts) >= 3:      # buttons of older messages
        parts, action = ["set", "v", action, parts[2]], "v"
    if action == "param" and len(parts) >= 3:
        if parts[2] == "custom_prompt":
            ask_custom_prompt(chat_id, mid)
        elif parts[2] in BY_KEY:
            option_view(chat_id, parts[2], mid)
        else:
            panel(chat_id, mid)
    elif action == "v" and len(parts) >= 4:
        key, val = parts[2], ":".join(parts[3:])
        if key == "custom_prompt":
            core.set_session_setting(str(chat_id), key, "")
            from telegram_bot import store
            store.clear_flow(chat_id)
            note = tr("Instructions removed")
        elif key in BY_KEY and val in dict(BY_KEY[key].options):
            core.set_session_setting(str(chat_id), key, val)
            note = label_of(key, val).split(" · ")[0]
        panel(chat_id, mid)
    elif action == "voce":
        from telegram_bot.services import voice_service
        voice_service.set_live(chat_id, not voice_service.is_live(chat_id))
        panel(chat_id, mid)
    elif action == "reset":
        core.reset_session_settings(str(chat_id))
        note = tr("Default settings")
        panel(chat_id, mid)
    else:
        panel(chat_id, mid)
    try:
        core.bot.answer_callback_query(call.id, note or None)
    except Exception:  # noqa: BLE001
        pass
