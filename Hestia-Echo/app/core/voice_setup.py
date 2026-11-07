"""Guided setup «Voce» (docs/work/2026-10-30-setup-un-click §4.2): the same shape as the models screen.

Echo owns the speech providers, so the screen asks Echo only:
- ``catalog(blocks, language, hosts)``: for each direction (``ascolto`` = listening, ``voce`` = speaking) the providers
  that can do it, local first, each with what it offers (Whisper sizes, Kokoro/Piper voices, a cloud service's
  models and voices once its key is there) and the step the chain uses now; plus the speech programs found at home
  (Speaches/LocalAI with the OpenAI API, Home Assistant's Wyoming servers) on this computer and on the other
  computers the user names, like the models screen finds Ollama or LM Studio;
- ``check(blocks, name, language)``: «Prova» without spending anything: a cloud service's model or voice list read
  with its key proves the key;
- ``plan(chains, listen, speak)``: the chosen steps first, in order, in the ``ascolto`` / ``voce`` chains (one local
  engine, then any cloud services as fallbacks), the other steps kept after them (pure, for the tests); ``apply``
  writes it through Themis.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from .blocks import CHAINS_KEY, DEFAULT_CHAINS, DEFAULT_PROVIDERS, DIRECTIONS, PROVIDERS_KEY
from .standards import STANDARDS

logger = logging.getLogger("hestia_echo.voice_setup")

LOCAL_TYPES = {"whisper_local", "piper", "kokoro"}
# Shown first and preselected when nothing is chosen yet.
PREFERRED = {"ascolto": ("whisper_local", "small"), "voce": ("kokoro", "")}
# One line per engine, so the user knows what to pick (Marko: «che ne so se scegliere Kokoro o Piper?»).
ENGINE_NOTES = {
    "whisper_local": "Capisce quello che dici sul tuo computer, gratis e privato. Più grande = più preciso e più lento.",
    "kokoro": "La voce più naturale, quasi umana. Circa 350 MB, va bene anche senza scheda video. Consigliata.",
    "piper": "Leggerissima e istantanea (circa 60 MB a voce), anche su computer vecchi; suona più da sintetizzatore.",
    "wyoming": "Il server voce di Home Assistant che hai in casa.",
    "openai": "Un programma vocale che hai in casa (Chatterbox, Speaches, LocalAI…).",
}
WHISPER_NOTES = {"tiny": "Il più leggero, sbaglia di più.", "base": "Leggero.",
                 "small": "Buon equilibrio: consigliato.", "medium": "Più preciso, più lento.",
                 "large-v3": "Il più preciso, serve una buona scheda video."}


# Speech programs that may run at home, on their usual port. Seen from the container, this computer is
# ``host.docker.internal`` (compose ``extra_hosts``).
THIS_COMPUTER = "host.docker.internal"
# ``site``/``note``/``dirs``: a free program the setup offers to install when it is not found (Marko 2026-11-07:
# «mettiamo tutte le voci locali»). ``model``: its speech model when it has no ``/v1/models`` list.
SPEECH_PROGRAMS = [
    {"name": "chatterbox", "label": "Chatterbox", "port": 8004, "type": "openai", "model": "chatterbox",
     "site": "https://github.com/devnen/Chatterbox-TTS-Server", "dirs": ("voce",),
     "note": "La voce più naturale, in 23 lingue (italiano compreso). Usa la scheda video, va anche senza ma lenta."},
    {"name": "kokoro-fastapi", "label": "Kokoro (programma)", "port": 8880, "type": "openai", "model": "kokoro",
     "site": "https://github.com/remsky/Kokoro-FastAPI", "dirs": ("voce",),
     "note": "Kokoro come programma a parte, più veloce con la scheda video."},
    {"name": "speaches", "label": "Speaches", "port": 8000, "type": "openai",
     "site": "https://github.com/speaches-ai/speaches", "dirs": ("ascolto", "voce"),
     "note": "Ascolto e voce in un programma solo (Whisper, Kokoro, Piper)."},
    {"name": "localai", "label": "LocalAI", "port": 8080, "type": "openai"},
    {"name": "wyoming-whisper", "label": "Whisper di Home Assistant", "port": 10300, "type": "wyoming"},
    {"name": "wyoming-piper", "label": "Piper di Home Assistant", "port": 10200, "type": "wyoming"},
]
_LISTEN_WORDS = ("whisper", "transcrib", "stt", "parakeet", "asr")
_SPEAK_WORDS = ("tts", "kokoro", "piper", "speech", "voice", "xtts", "melo")
HOST_RE = re.compile(r"[A-Za-z0-9.-]{1,120}")


def home_hosts(hosts: str | list[str] | None) -> list[str]:
    """This computer, then the other computers of the home network the user named (at most 4), checked."""
    raw = hosts.split(",") if isinstance(hosts, str) else list(hosts or [])
    out = [THIS_COMPUTER]
    for h in raw:
        h = str(h).strip().removeprefix("http://").removeprefix("https://").split("/")[0].split(":")[0]
        if h and HOST_RE.fullmatch(h) and h not in out:
            out.append(h)
    return out[:5]


def is_home(url: str) -> bool:
    """An address inside the house (this computer, a private address, a .local/.lan name): local, not cloud."""
    host = (urlsplit(url if "://" in url else "tcp://" + url).hostname or "").lower()
    if not host:
        return False
    if host in ("localhost", THIS_COMPUTER) or host.endswith((".local", ".lan", ".home")) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def _probe_openai(base: str, model: str = "") -> dict[str, list[dict]] | None:
    """An OpenAI-compatible server's speech models (None when nothing answers or it only has chat models).
    ``model``: a speech-only program without a model list (Chatterbox): it counts when its voice list answers."""
    try:
        resp = requests.get(f"{base}/models", timeout=1.5)
        ids = [str(m.get("id")) for m in (resp.json() or {}).get("data") or [] if isinstance(m, dict) and m.get("id")] \
            if resp.ok else None
    except Exception:
        ids = None
    if not ids and model:
        try:
            ids = [model] if requests.get(f"{base}/audio/voices", timeout=1.5).ok else None
        except Exception:
            ids = None
    if ids is None:
        return None
    listen = [i for i in ids if any(w in i.lower() for w in _LISTEN_WORDS)]
    speak = [i for i in ids if any(w in i.lower() for w in _SPEAK_WORDS)]
    if not listen and not speak:
        return None                      # a server for chat models (vLLM, llama.cpp…): the models screen shows it
    voices: list[dict] = []
    try:
        got = requests.get(f"{base}/audio/voices", timeout=1.5)
        rows = got.json() if got.ok else []
        rows = rows.get("voices") or rows.get("data") or [] if isinstance(rows, dict) else rows
        for v in rows or []:
            vid = v.get("voice_id") or v.get("id") or v.get("name") if isinstance(v, dict) else v
            if vid:
                voices.append({"id": str(vid), "label": str(v.get("name") or vid) if isinstance(v, dict) else str(vid)})
    except Exception:
        pass
    return {"ascolto": [{"id": i, "label": i} for i in listen],
            "voce": [{"id": i, "label": i} for i in speak], "voices": voices}


def _probe_wyoming(host: str, port: int) -> dict[str, list[dict]] | None:
    """A Wyoming server (Home Assistant's whisper/piper): ``describe`` → what it can do."""
    try:
        with socket.create_connection((host, port), timeout=1.5) as sock:
            sock.settimeout(1.5)
            sock.sendall(json.dumps({"type": "describe", "data": {}}).encode() + b"\n")
            f = sock.makefile("rb")
            line = f.readline()
            header = json.loads(line) if line else {}
            data = header.get("data") or {}
            if header.get("data_length"):
                data.update(json.loads(f.read(int(header["data_length"]))))
    except Exception:
        return None
    if header.get("type") != "info":
        return None
    listen = [{"id": str(m.get("name")), "label": str(m.get("name"))}
              for p in data.get("asr") or [] for m in p.get("models") or [] if m.get("name")]
    voices = [{"id": str(v.get("name")), "label": str(v.get("name"))}
              for p in data.get("tts") or [] for v in p.get("voices") or [] if v.get("name")]
    if not listen and not voices and not (data.get("asr") or data.get("tts")):
        return None
    return {"ascolto": listen or ([{"id": "", "label": "Predefinito"}] if data.get("asr") else []),
            "voce": [], "voices": voices or ([{"id": "", "label": "Predefinita"}] if data.get("tts") else [])}


def found_programs(blocks, hosts: str | list[str] | None = None) -> list[dict]:
    """The speech programs that answer at home, not yet a block (a block at the same address is listed already)."""
    known = {(p.get("url") or "").rstrip("/") for p in blocks.providers().values()}
    probes = [(spec, host) for host in home_hosts(hosts) for spec in SPEECH_PROGRAMS]

    def ask(probe):
        spec, host = probe
        if spec["type"] == "wyoming":
            return f"tcp://{host}:{spec['port']}", _probe_wyoming(host, spec["port"])
        base = f"http://{host}:{spec['port']}/v1"
        return base, _probe_openai(base, spec.get("model", ""))
    with ThreadPoolExecutor(max_workers=min(16, len(probes))) as pool:
        answers = list(pool.map(ask, probes))
    out = []
    for (spec, host), (url, got) in zip(probes, answers):
        if got is None or url in known:
            continue
        if spec.get("model") and spec["model"] not in {v["id"] for v in got["voce"]}:
            got["voce"].append({"id": spec["model"], "label": spec["model"]})
        here = host == THIS_COMPUTER
        out.append({"name": spec["name"] if here else f"{spec['name']}-{re.sub(r'[^a-z0-9]+', '-', host.lower()).strip('-')}",
                    "label": spec["label"] if here else f"{spec['label']} · {host}", "type": spec["type"], "url": url,
                    "where": "questo computer" if here else host, **got})
    return out


def _items(rows: list[dict]) -> list[dict]:
    return [{"id": str(r.get("id")), "label": str(r.get("label") or r.get("id"))} for r in rows if r.get("id")]


def catalog(blocks, language: str = "it", hosts: str | list[str] | None = None) -> dict[str, Any]:
    """``{ascolto: {providers[], current, steps}, voce: {…}}``. A provider row: ``{name, label, type, local, note,
    needs_key, key, state, models[], voices[], found?, url?}`` (models/voices only when usable: a cloud service needs
    its key). ``local`` = Echo's own engines and every program at home (a private address); ``found`` = a program
    that answered at home and becomes a block when chosen (its ``url`` comes back with the step)."""
    chains = blocks.chains()
    found = found_programs(blocks, hosts)
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
            home = p["type"] in LOCAL_TYPES or (p["type"] in ("openai", "wyoming") and is_home(p.get("url") or ""))
            rows.append({"name": p["name"], "label": p["label"], "type": p["type"], "local": home,
                         "note": ENGINE_NOTES.get(p["type"], "") if home else "",
                         "needs_key": bool(std.needs_key) or state == "no_key", "key": bool(p["key"]),
                         "state": state, "models": models, "voices": voices})
        for f in found:
            models, voices = (f["ascolto"], []) if direction == "ascolto" else (f["voce"], f["voices"] or f["voce"])
            if not models and not voices:
                continue
            rows.append({"name": f["name"], "label": f["label"], "type": f["type"], "local": True, "found": True,
                         "url": f["url"], "note": f"{ENGINE_NOTES[f['type']]} Trovato su {f['where']}.",
                         "needs_key": False, "key": False, "state": "ready", "models": models, "voices": voices})
        rows.sort(key=lambda r: (not r["local"], r["type"] != PREFERRED[direction][0]))
        chain = chains.get(direction) or {"steps": []}
        steps = [{"provider": s.get("provider", ""), "model": s.get("model", ""), "voice": s.get("voice", "")}
                 for s in chain.get("steps") or [] if s.get("provider")]
        # ``current`` = the first step (kept for older pages), ``steps`` = the whole chain in order.
        have = [f["name"] for f in found] + [p["name"] for p in blocks.providers().values()]
        programs = [{"name": sp["name"], "label": sp["label"], "site": sp["site"], "note": sp["note"]}
                    for sp in SPEECH_PROGRAMS if sp.get("site") and direction in sp["dirs"]
                    and not any(h == sp["name"] or h.startswith(sp["name"] + "-") for h in have)]
        out[direction] = {"providers": rows, "current": steps[0] if steps else {"provider": "", "model": "", "voice": ""},
                          "steps": steps, "programs": programs}
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
    models, voices = _items(std.models(p)), _items(std.voices(p, language))
    # Preselected once the key works, so nothing is asked: the first model and the first voice it lists.
    return {"ok": True, "detail": "La chiave funziona.", "models": models, "voices": voices,
            "recommended": {"ascolto": [m["id"] for m in models[:1]], "voce": [v["id"] for v in voices[:1]]}}


def _steps(choice: dict | list | None) -> list[dict]:
    """The setup's choice for one direction: one step or several in order (a local engine, then cloud services)."""
    rows = [choice] if isinstance(choice, dict) else list(choice or [])
    out, seen = [], set()
    for c in rows:
        if not isinstance(c, dict) or not c.get("provider"):
            continue
        step = {"provider": str(c["provider"]), "model": str(c.get("model") or ""), "voice": str(c.get("voice") or ""),
                "options": {}}
        if c.get("url"):                 # a program found at home, not a block yet: kept aside for ``apply``
            step["_new"] = {"url": str(c["url"]), "type": str(c.get("type") or ""), "label": str(c.get("label") or "")}
        key = (step["provider"], step["model"], step["voice"])
        if key not in seen:
            seen.add(key)
            out.append(step)
    return out


def plan(chains: dict[str, dict], listen: dict | list | None, speak: dict | list | None) -> dict[str, dict]:
    """New ``echo.chains``: the chosen steps first, in order, in ``ascolto`` / ``voce``; the other steps of providers
    not chosen stay after them as fallbacks. Pure function."""
    out = {name: dict(c) for name, c in (chains or DEFAULT_CHAINS).items()}
    for direction, choice in (("ascolto", listen), ("voce", speak)):
        chosen = _steps(choice)
        if not chosen:
            continue
        chosen = [{k: v for k, v in s.items() if k != "_new"} for s in chosen]
        names = {s["provider"] for s in chosen}
        base = out.get(direction) or DEFAULT_CHAINS[direction]
        rest = [dict(s) for s in base.get("steps") or [] if s.get("provider") not in names]
        out[direction] = {"label": base.get("label") or direction.capitalize(), "direction": direction,
                          "steps": chosen + rest}
    return out


def _add_found(blocks, put: Callable[..., Any], steps: list[dict]) -> bool:
    """Programs found at home and chosen become blocks (``openai`` with their address, or ``wyoming``)."""
    new = {s["provider"]: s["_new"] for s in steps if s.get("_new") and s["provider"] not in blocks.providers()}
    new = {n: d for n, d in new.items() if d["type"] in ("openai", "wyoming") and is_home(d["url"])}
    if not new:
        return True
    current = blocks.get(PROVIDERS_KEY, None)
    provs = {k: dict(v) for k, v in (current if isinstance(current, dict) and current else DEFAULT_PROVIDERS).items()}
    for name, d in new.items():
        provs[name] = {"type": d["type"], "label": d["label"] or name, "url": d["url"], "options": {}}
    ok = put(PROVIDERS_KEY, provs, actor="user", reason="Setup guidato: programma vocale in casa")
    logger.info("event=voice_setup_programs_added names=%s ok=%s", ",".join(new), bool(ok))
    return bool(ok)


def apply(blocks, put: Callable[..., Any], listen: dict | list | None, speak: dict | list | None) -> dict[str, Any]:
    if not _add_found(blocks, put, _steps(listen) + _steps(speak)):
        return {"ok": False, "detail": "Le impostazioni non hanno accettato il programma vocale."}
    chains = plan(blocks.chains(), listen, speak)
    if not put(CHAINS_KEY, chains, actor="user", reason="Setup guidato: voce"):
        return {"ok": False, "detail": "Le impostazioni non hanno accettato la scelta."}
    logger.info("event=voice_setup_applied listen=%s speak=%s", ",".join(s["provider"] for s in _steps(listen)) or "-",
                ",".join(s["provider"] for s in _steps(speak)) or "-")
    return {"ok": True, "chains": chains}
