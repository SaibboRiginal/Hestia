"""Chat settings schema — ONE place that defines every per-chat option.

The /settings menu, the defaults used by the reply renderer and what is
(not) sent to Oracle as client instructions all come from here. Add an option:
append a Setting; the menu shows it automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    options: tuple[tuple[str, str], ...]
    default: str
    help: str = ""
    group: str = "chat"
    ui_only: bool = True          # False → forwarded to Oracle (affects the answer)


ON_OFF = (("on", "Attivo"), ("off", "Disattivo"))

SETTINGS: tuple[Setting, ...] = (
    # ── Answer ────────────────────────────────────────────────────────────
    Setting("tone", "🎙️ Tono", (("warm", "Caldo"), ("neutral", "Neutro"), ("direct", "Diretto"), ("formal", "Formale")),
            "warm", "Come ti risponde Hestia.", "risposta", ui_only=False),
    Setting("thinking_display", "💭 Ragionamento",
            (("hidden", "Nascosto"), ("compact", "Compatto · riquadro chiuso"),
             ("detailed", "Dettagliato · riquadro aperto"), ("live", "Dal vivo · passi mentre lavora")),
            "compact", "Come vedi i passi e gli strumenti usati.", "risposta"),
    Setting("stream_answer", "⚡ Risposta in streaming", ON_OFF, "on",
            "La risposta compare mentre viene scritta (quando il modello la invia a pezzi).", "risposta"),
    Setting("split_mode", "✂️ Messaggi lunghi",
            (("single", "Un solo messaggio (spezza solo se troppo lungo)"), ("paragraphs", "Un messaggio per paragrafo")),
            "single", "", "risposta"),
    # ── System notices (standard packets) ─────────────────────────────────
    Setting("notice_mode", "🔔 Messaggi di sistema",
            (("inline", "Sotto la risposta"), ("separate", "Messaggio separato"),
             ("important", "Solo importanti (azioni ed errori)"), ("hidden", "Nascosti")),
            "inline", "Memoria salvata, azioni eseguite, errori…", "sistema"),
    Setting("notice_style", "🎨 Stile messaggi di sistema",
            (("compact", "Compatto · icona + testo"), ("rich", "Dettagliato · titolo + dettaglio")),
            "compact", "", "sistema"),
    Setting("notice_memory", "💾 Avvisi memoria", ON_OFF, "on", "Quando ricordo o dimentico qualcosa.", "sistema"),
    Setting("notice_actions", "✅ Avvisi azioni", ON_OFF, "on", "Quando eseguo (o non riesco a eseguire) un'azione.", "sistema"),
    Setting("notice_subscriptions", "🔔 Avvisi notifiche", ON_OFF, "on", "Quando attivo o modifico un avviso.", "sistema"),
    Setting("notice_other", "ℹ️ Altri avvisi", ON_OFF, "on", "Documenti, agenda, sviluppo, info.", "sistema"),
)

BY_KEY = {s.key: s for s in SETTINGS}
GROUP_LABELS = {"risposta": "Risposta", "sistema": "Messaggi di sistema"}
# Keys never sent to Oracle (pure client rendering). custom_prompt IS sent.
UI_ONLY_KEYS = {s.key for s in SETTINGS if s.ui_only}

_TONE_SENTENCE = {
    "warm": "Tono: caldo e amichevole.",
    "neutral": "",
    "direct": "Tono: diretto, essenziale, niente preamboli.",
    "formal": "Tono: formale.",
}


def value(settings: dict, key: str) -> str:
    """Current value with schema default (legacy values mapped)."""
    raw = str((settings or {}).get(key) or "").strip().lower()
    s = BY_KEY.get(key)
    if not s:
        return raw
    return raw if raw in {o[0] for o in s.options} else s.default


def label_of(key: str, val: str) -> str:
    s = BY_KEY.get(key)
    return dict(s.options).get(val, val) if s else val


def oracle_instructions(settings: dict) -> list[str]:
    """Only answer-affecting settings, as natural sentences (no raw key: value noise)."""
    out: list[str] = []
    tone = _TONE_SENTENCE.get(value(settings, "tone"), "")
    if tone:
        out.append(tone)
    custom = str((settings or {}).get("custom_prompt") or "").strip()
    if custom:
        out.append(f"Istruzioni dell'utente: {custom}")
    return out


@dataclass
class NoticePolicy:
    mode: str = "inline"
    style: str = "compact"
    kinds: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: dict) -> "NoticePolicy":
        return cls(
            mode=value(settings, "notice_mode"), style=value(settings, "notice_style"),
            kinds={k: value(settings, k) == "on" for k in
                   ("notice_memory", "notice_actions", "notice_subscriptions", "notice_other")},
        )

    def allows(self, packet: dict) -> bool:
        if self.mode == "hidden":
            return False
        kind = str(packet.get("kind") or "info")
        level = str(packet.get("level") or "info")
        group = ("notice_memory" if kind.startswith("memory.") else
                 "notice_actions" if kind.startswith("action.") else
                 "notice_subscriptions" if kind.startswith("subscription.") else "notice_other")
        if not self.kinds.get(group, True) and level != "error":
            return False
        if self.mode == "important":
            return level in {"warning", "error"} or kind.startswith("action.")
        return True
