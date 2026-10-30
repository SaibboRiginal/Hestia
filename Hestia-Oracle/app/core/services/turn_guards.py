"""Turn guards: fixed rules in code around the write tools of one chat turn, whatever the model decides.

The prompt asks the model to behave; a small model (or a big one on a bad day) does not always do it. These rules
do not depend on the model (bench with real and small models, 2026-10-30, docs/work/2026-10-30-ai-vera-gemini):

1. A question or a request for advice changes nothing: write tools are refused (settings_propose and
   forge_develop excepted: they only propose, the user confirms).
2. One thing, one place: once a module stored what the user said, memory.save does not copy it (unless the user
   said «ricorda»).
3. Deleting or cancelling needs the user's own words for it (cancella, elimina, togli, annulla…).
4. forge_develop starts only when the user asked to build something or said yes to the proposal.
5. At most ``MAX_WRITES`` writes per turn: more is a runaway loop, the model asks first.

A refused call returns ``(False, "BLOCCATO: …")``: the model reads why and answers the user. The tool log marks
it ``refused``: no «Non riuscito» notice to the user, nothing was tried. On a question a write tool called with no
values passes: on read-or-write tools (cibo_dieta) that is a read.
"""
from __future__ import annotations

import logging
import re

from core.services.memory_intent import asks_to_remember, has_deprecate_intent, has_write_intent

logger = logging.getLogger(f"hestia_oracle.{__name__}")

MAX_WRITES = 6
PROPOSE_ONLY = frozenset({"settings_propose", "forge_develop", "ask_user"})
MEMORY_TOOLS = frozenset({"memory.save", "memory.forget"})

_ADVICE = re.compile(r"\b(consigli|consiglia|suggerisci|suggerimento|cosa ne pensi|che ne dici)\w*", re.IGNORECASE)
_DESTRUCTIVE_NAME = re.compile(r"(delete|elimina|remove|rimuovi|cancel|annulla|disiscriviti|scollega|forget)",
                               re.IGNORECASE)
_DESTRUCTIVE_ASK = re.compile(r"\b(cancell|elimin|togli|rimuov|annull|disdic|scollega|smetti|basta|dimentic|"
                              r"delete|remove|cancel)\w*", re.IGNORECASE)
_BUILD_ASK = re.compile(r"\b(sviluppa|implementa|programma|costruisci|crea(?:mi)? (?:un|una) (?:comando|modulo|"
                        r"funzione|strumento|plugin)|aggiungi (?:a|in) hestia|forge)\w*", re.IGNORECASE)
_YES = re.compile(r"^\s*(s[iì]|ok|okay|va bene|vai|procedi|fallo|confermo|certo|d'accordo|perfetto)\b[\s!.]*",
                  re.IGNORECASE)


def is_question_or_advice(message: str) -> bool:
    """A question or a request for advice, with no word asking to change something."""
    text = str(message or "").strip()
    if not text or has_write_intent(text):
        return False
    return text.endswith("?") or bool(_ADVICE.search(text))


def _has_values(params: dict | None) -> bool:
    return any(v not in (None, "", [], {}) for v in (params or {}).values())


class TurnGuards:
    """State of one turn; ``check(tool)`` → None (go on) or the reason the call is refused."""

    def __init__(self, user_message: str):
        self.message = str(user_message or "")
        self.question = is_question_or_advice(self.message)
        self.remember = asks_to_remember(self.message)
        self.delete_ok = bool(_DESTRUCTIVE_ASK.search(self.message)) or has_deprecate_intent(self.message)
        self.build_ok = bool(_BUILD_ASK.search(self.message)) or bool(_YES.match(self.message))
        self.module_writes = 0
        self.writes = 0

    def check(self, tool, params: dict | None = None) -> str | None:
        name = str(getattr(tool, "name", "") or "")
        if not getattr(tool, "writes", False) and name != "forge_develop":
            return None
        if name == "forge_develop" and not self.build_ok:
            return ("BLOCCATO: prima chiedi all'utente se vuole davvero sviluppare questa funzione (ask_user, "
                    "confirm) e chiama forge_develop solo dopo il sì.")
        if name in PROPOSE_ONLY:
            return None
        if self.question and _has_values(params):   # a write tool with no values only reads (cibo_dieta)
            return ("BLOCCATO: l'utente ha fatto una domanda o chiesto un consiglio, non ha chiesto di salvare o "
                    "cambiare nulla. Rispondi senza scrivere.")
        if _DESTRUCTIVE_NAME.search(name) and name != "memory.forget" and not self.delete_ok:
            return "BLOCCATO: l'utente non ha chiesto di cancellare o annullare nulla. Non farlo."
        if name == "memory.save" and self.module_writes and not self.remember:
            return ("GIÀ SALVATO dall'azione di questo turno: non copiarlo anche in memoria. Rispondi all'utente.")
        if self.writes >= MAX_WRITES:
            return (f"BLOCCATO: già {MAX_WRITES} modifiche in questo turno. Fermati e chiedi all'utente se "
                    "continuare.")
        return None

    def done(self, tool, ok: bool) -> None:
        name = str(getattr(tool, "name", "") or "")
        if not ok or not getattr(tool, "writes", False):
            return
        self.writes += 1
        if name not in MEMORY_TOOLS:
            self.module_writes += 1

    def wrap(self, tools: list) -> None:
        """Put the guard in front of every tool handler of the turn."""
        for t in tools:
            t.handler = self._guarded(t, t.handler)

    def _guarded(self, tool, handler):
        def run(**kw):
            reason = self.check(tool, kw)
            if reason:
                logger.info("[🔄] event=turn_guard_refused tool=%s reason=%s", tool.name, reason[:60])
                if reason.startswith("GIÀ"):   # nothing to do, not a failure: no «Fatto», no «non riuscito»
                    return True, {"already_known": True, "note": reason}
                return False, reason
            ok, out = handler(**kw)
            self.done(tool, bool(ok))
            return ok, out
        return run

