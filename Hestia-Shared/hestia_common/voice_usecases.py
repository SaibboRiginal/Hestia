"""Voice uses a caller declares to Echo (dossier ``docs/work/2026-10-20-modulo-voce`` §4.C).

Same shape as ``oracle_usecases``: a module that asks Echo to listen (speech → text) or speak (text → speech)
declares each kind of task as a use, with its direction and a suggested chain (``ascolto``, ``ascolto-preciso``,
``voce``, ``voce-naturale``…). The declaration rides in the module's Hub registration
(``capabilities.voice_usecases``, re-sent by the keepalive). Marko picks chain and mode of every use in one place
(plugin «Voce» → Usi); the caller never names a provider, a model or a voice.

    from hestia_common.voice_usecases import usecase as voice_usecase, capabilities as voice_capabilities

    VOICE_USECASES = [voice_usecase("telegram.vocale", "Telegram · vocali", direction="ascolto")]
    payload["capabilities"].update(voice_capabilities(VOICE_USECASES))
"""
from __future__ import annotations

import re

DIRECTIONS = ("ascolto", "voce")
MODES = ("segui", "interna", "esterna")
_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_.-]+$")


def usecase(id: str, label: str, *, direction: str, chain: str = "", help: str = "", mode: str = "segui") -> dict:
    """One use: id ``<module>.<task>``, Italian label, direction ``ascolto`` | ``voce``, suggested chain
    (empty = the default chain of the direction) and mode."""
    if not _ID.match(id):
        raise ValueError(f"voice use id {id!r} must be '<module>.<task>' (lowercase)")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction {direction!r} must be one of {DIRECTIONS}")
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} must be one of {MODES}")
    return {"id": id, "label": label, "direction": direction, "chain": chain or direction, "help": help,
            "mode": mode}


def capabilities(usecases: list[dict]) -> dict:
    """Keys to merge into ``capabilities`` of the Hub registration."""
    return {"voice_usecases": list(usecases)}
