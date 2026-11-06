"""Guided setup «Voce» (docs/work/2026-10-30-setup-un-click §4.2): the same shape as the models screen.

Echo owns the speech providers, so the screen asks Echo only:
- ``catalog(blocks, language)``: for each direction (``ascolto`` = listening, ``voce`` = speaking) the providers
  that can do it, local first, each with what it offers (Whisper sizes, Kokoro/Piper voices, a cloud service's
  models and voices once its key is there) and the step the chain uses now;
- ``check(blocks, name, language)``: «Prova» without spending anything: a cloud service's model or voice list read
  with its key proves the key;
- ``plan(chains, listen, speak)``: the chosen step first in the ``ascolto`` / ``voce`` chains, the other steps kept
  after it as fallbacks (pure, for the tests); ``apply`` writes it through Themis.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import requests

from .blocks import CHAINS_KEY, DEFAULT_CHAINS, DIRECTIONS
from .standards import STANDARDS

logger = logging.getLogger("hestia_echo.voice_setup")

LOCAL_TYPES = {"whisper_local", "piper", "kokoro"}
# Shown first and preselected when nothing is chosen yet.
PREFERRED = {"ascolto": ("whisper_local", "small"), "voce": ("kokoro", "")}
WHISPER_NOTES = {"tiny": "Il più leggero, sbaglia di più.", "base": "Leggero.",
                 "small": "Buon equilibrio: consigliato.", "medium": "Più preciso, più lento.",
                 "large-v3": "Il più preciso, serve una buona scheda video."}


def _items(rows: list[dict]) -> list[dict]:
    return [{"id": str(r.get("id")), "label": str(r.get("label") or r.get("id"))} for r in rows if r.get("id")]


def catalog(blocks, language: str = "it") -> dict[str, Any]:
    """``{ascolto: {providers[], current}, voce: {providers[], current}}``. A provider row: ``{name, label, type,
    local, needs_key, key, state, models[], voices[]}`` (models/voices only when usable: a cloud service needs its key)."""
    chains = blocks.chains()
    out: dict[str, Any] = {}
    for direction in DIRECTIONS:
        rows = []
        for p in blocks.providers().values():
            std = STANDARDS[p["type"]]
            if direction not in std.directions:
                continue
            state = blocks.provider_state(p)
            ready = state in ("ready", "not_installed", "downloading") if p["type"] in LOCAL_TYPES else state == "ready"
            models = _items(std.models(p)) if ready and direction == "ascolto" else []
            voices = _items(std.voices(p, language)) if ready and direction == "voce" else []
            if p["type"] == "whisper_local":
                models = [{**m, "note": WHISPER_NOTES.get(m["id"], "")} for m in models]
            rows.append({"name": p["name"], "label": p["label"], "type": p["type"], "local": p["type"] in LOCAL_TYPES,
                         "needs_key": bool(std.needs_key) or state == "no_key", "key": bool(p["key"]),
                         "state": state, "models": models, "voices": voices})
        rows.sort(key=lambda r: (not r["local"], r["type"] != PREFERRED[direction][0]))
        chain = chains.get(direction) or {"steps": []}
        current = (chain.get("steps") or [{}])[0] if chain.get("steps") else {}
        out[direction] = {"providers": rows, "current": {"provider": current.get("provider", ""),
                                                         "model": current.get("model", ""),
                                                         "voice": current.get("voice", "")}}
    return out


def check(blocks, name: str, language: str = "it") -> dict[str, Any]:
    """«Prova» for a cloud speech service: its list read with the key (no audio made, nothing spent)."""
    p = blocks.providers().get(name)
    if p is None:
        return {"ok": False, "detail": "Questo servizio non è configurato."}
    std = STANDARDS[p["type"]]
    if p["type"] in LOCAL_TYPES:
        return {"ok": True, "detail": "Funziona sul tuo computer.", "models": _items(std.models(p)),
                "voices": _items(std.voices(p, language))}
    if blocks.provider_state(p) == "no_key" or (std.needs_key and not p["key"]):
        return {"ok": False, "detail": "Manca la chiave."}
    url = std.url(p).rstrip("/")
    try:
        if p["type"] == "openai":
            resp = requests.get(f"{url}/models", headers={"Authorization": f"Bearer {p['key']}"} if p["key"] else {},
                                timeout=10)
        elif p["type"] == "google":
            resp = requests.get("https://texttospeech.googleapis.com/v1/voices", params={"key": p["key"]}, timeout=10)
        elif p["type"] == "elevenlabs":
            resp = requests.get(f"{url}/voices", headers={"xi-api-key": p["key"]}, timeout=10)
        else:
            resp = None
    except Exception as exc:
        logger.info("[🔄] event=voice_setup_check_failed provider=%s error=%s", name, str(exc)[:160])
        return {"ok": False, "detail": "Non risponde: controlla la connessione."}
    if resp is not None:
        if resp.status_code in (400, 401, 403):
            return {"ok": False, "detail": "La chiave non è valida."}
        if not resp.ok and resp.status_code != 429:
            return {"ok": False, "detail": f"Non risponde (errore {resp.status_code})."}
    logger.info("event=voice_setup_check_ok provider=%s", name)
    return {"ok": True, "detail": "La chiave funziona.", "models": _items(std.models(p)),
            "voices": _items(std.voices(p, language))}


def plan(chains: dict[str, dict], listen: dict | None, speak: dict | None) -> dict[str, dict]:
    """New ``echo.chains``: the chosen step first in ``ascolto`` / ``voce``; the other steps stay after it as
    fallbacks (a provider appears once). Pure function."""
    out = {name: dict(c) for name, c in (chains or DEFAULT_CHAINS).items()}
    for direction, choice in (("ascolto", listen), ("voce", speak)):
        if not choice or not choice.get("provider"):
            continue
        step = {"provider": choice["provider"], "model": str(choice.get("model") or ""),
                "voice": str(choice.get("voice") or ""), "options": {}}
        base = out.get(direction) or DEFAULT_CHAINS[direction]
        rest = [dict(s) for s in base.get("steps") or [] if s.get("provider") != step["provider"]]
        out[direction] = {"label": base.get("label") or direction.capitalize(), "direction": direction,
                          "steps": [step] + rest}
    return out


def apply(blocks, put: Callable[..., Any], listen: dict | None, speak: dict | None) -> dict[str, Any]:
    chains = plan(blocks.chains(), listen, speak)
    if not put(CHAINS_KEY, chains, actor="user", reason="Setup guidato: voce"):
        return {"ok": False, "detail": "Le impostazioni non hanno accettato la scelta."}
    logger.info("event=voice_setup_applied listen=%s speak=%s", (listen or {}).get("provider", "-"),
                (speak or {}).get("provider", "-"))
    return {"ok": True, "chains": chains}
