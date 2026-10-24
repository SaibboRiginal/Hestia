"""Who started a request, written by the system and never taken from the content (Cindy idea 6).

Every message the owner did not type by hand carries an origin set by the caller's code in the routed headers
(``X-Hestia-Origin``), never by a model or a body field. Oracle maps it to the **level** of the turn:

- ``utente``   — the owner wrote it (Telegram, WebUI, an external AI he connected): everything, with the usual
                 confirmation gate;
- ``routine``  — a routine the owner wrote («Le mie routine» in the agenda): acts only inside its instruction,
                 nothing destructive;
- ``autonomo`` — the assistant by itself (reflection, presence, mail doorbells, module jobs): only reads, proposes
                 (Themis/Hermes) and notifies; a write comes back as «serve che lo chieda Marko».

Header value: ``<kind>:<ref>`` with kind ``utente`` · ``routine`` · ``autonomo`` · ``esterno`` (an external AI
access, counts as the owner). ``X-Hestia-Origin-Label`` is an optional short human label («Routine del lunedì»).
No header: a client name (telegram, webui) means the owner, nothing means autonomous (fail closed).
"""
from __future__ import annotations

from typing import Any, Mapping

HEADER = "X-Hestia-Origin"
LABEL_HEADER = "X-Hestia-Origin-Label"
LEVELS = ("utente", "routine", "autonomo")
_KIND_LEVEL = {"utente": "utente", "esterno": "utente", "routine": "routine", "autonomo": "autonomo",
               "modulo": "autonomo"}
USER_CLIENTS = {"telegram", "webui", "ui", "web", "mcp", "voice", "cli"}


def headers(kind: str, ref: str = "", label: str = "") -> dict[str, str]:
    """Headers a caller puts in the Hub envelope: ``headers("routine", "lunedi-annunci", "Annunci del lunedì")``."""
    out = {HEADER: f"{kind}:{ref}" if ref else kind}
    if label:
        out[LABEL_HEADER] = label[:80]
    return out


def _get(hdrs: Mapping[str, Any] | None, name: str) -> str:
    if not hdrs:
        return ""
    for k, v in hdrs.items():
        if str(k).lower() == name.lower():
            return str(v or "").strip()
    return ""


def parse(hdrs: Mapping[str, Any] | None = None, client: str = "") -> dict[str, str]:
    """``{kind, ref, level, label}`` of a request from its headers (and the client name it declared)."""
    raw = _get(hdrs, HEADER)
    label = _get(hdrs, LABEL_HEADER)[:80]
    if raw:
        kind, _, ref = raw.partition(":")
        kind = kind.strip().lower()
        level = _KIND_LEVEL.get(kind, "autonomo")
        return {"kind": kind if kind in _KIND_LEVEL else "autonomo", "ref": ref.strip()[:120], "level": level,
                "label": label or default_label(kind, ref.strip())}
    client = str(client or _get(hdrs, "X-Hestia-Client")).strip().lower()
    if client in USER_CLIENTS:
        return {"kind": "utente", "ref": client, "level": "utente", "label": ""}
    return {"kind": "autonomo", "ref": client, "level": "autonomo", "label": label or default_label("autonomo", client)}


def default_label(kind: str, ref: str = "") -> str:
    """Short user-facing label (never a module name: R5)."""
    if kind == "routine":
        return "Da una tua routine"
    if kind == "esterno":
        return "Da un'altra AI collegata"
    if kind in ("autonomo", "modulo"):
        return "Iniziativa dell'assistente"
    return ""


def prompt_line(origin: Mapping[str, str]) -> str:
    """One caveman line for the model about who started this turn (empty for the owner typing)."""
    level = origin.get("level", "utente")
    if level == "utente" and origin.get("kind") != "esterno":
        return ""
    if level == "routine":
        return (f"[Origine] routine dell'utente ({origin.get('label') or origin.get('ref')}), non scritta ora da lui. "
                "Agisci solo dentro l'istruzione della routine; niente cancellazioni.")
    if level == "autonomo":
        return ("[Origine] iniziativa automatica, non un messaggio dell'utente. Puoi solo leggere, proporre e "
                "avvisare; per cambiare dati serve che lo chieda l'utente.")
    return f"[Origine] {origin.get('label') or 'altra AI collegata'} per conto dell'utente."


def blocks_write(origin: Mapping[str, str], *, method: str = "POST", name: str = "") -> str:
    """Why a write is not allowed at this level ("" = allowed). Proposals and notices are always allowed."""
    level = origin.get("level", "autonomo")
    lname = str(name or "").lower()
    if any(w in lname for w in ("propose", "proposta", "proponi", "suggest", "notify", "ask_user")):
        return ""
    if level == "autonomo":
        return "Iniziativa automatica: per cambiare dati serve che lo chieda Marko. Proponilo invece di farlo."
    destructive = str(method or "").upper() == "DELETE" or any(
        w in lname for w in ("delete", "remove", "elimina", "cancella", "rimuovi", "purge", "restore", "rollback"))
    if level == "routine" and destructive:
        return "Una routine non cancella né ripristina dati: chiedilo a Marko."
    return ""
