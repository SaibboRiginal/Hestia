"""Providers, chains, uses — the blocks of Echo, same shape as Oracle a blocchi (dossier §4).

- **Providers** (``echo.providers``): ``{name: {type, label, url, options}}``; the key only in env
  ``ECHO_KEY_<NAME>`` (upper-case, ``-`` → ``_``).
- **Chains** (``echo.chains``): ``{name: {label, direction, steps: [{provider, model, voice, options}]}}``; a step
  out of quota is skipped by every chain until its reset; other errors move to the next step for this call only.
- **Uses**: Echo's own + the ones callers declare in their Hub registration (``capabilities.voice_usecases``);
  Marko's overrides in ``echo.usecases`` (``{use: {chain, mode}}``).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

from .standards import STANDARDS, EngineError

logger = logging.getLogger("hestia_echo.blocks")

PROVIDERS_KEY = "echo.providers"
CHAINS_KEY = "echo.chains"
USECASES_KEY = "echo.usecases"
COOLDOWN_KEY = "echo.chains.cooldown"
MODE_KEY = "echo.mode"
EXTERNAL_KEY = "echo.external.provider"
EXTERNAL_MODEL_KEY = "echo.external.model"
FALLBACK_KEY = "echo.external.fallback"

DIRECTIONS = ("ascolto", "voce")

DEFAULT_PROVIDERS: dict[str, dict] = {
    "whisper-locale": {"type": "whisper_local", "label": "Whisper (locale)", "url": "", "options": {}},
    "kokoro": {"type": "kokoro", "label": "Kokoro (locale)", "url": "", "options": {}},
    "piper": {"type": "piper", "label": "Piper (locale)", "url": "", "options": {}},
    "groq": {"type": "openai", "label": "Groq", "url": "https://api.groq.com/openai/v1", "options": {}},
    "openai": {"type": "openai", "label": "OpenAI", "url": "https://api.openai.com/v1", "options": {}},
    "google": {"type": "google", "label": "Google Cloud", "url": "", "options": {}},
    "elevenlabs": {"type": "elevenlabs", "label": "ElevenLabs", "url": "", "options": {}},
}


def _step(provider: str, model: str = "", voice: str = "", **options) -> dict:
    return {"provider": provider, "model": model, "voice": voice, "options": options}


DEFAULT_CHAINS: dict[str, dict] = {
    "ascolto": {"label": "Ascolto", "direction": "ascolto", "steps": [
        _step("whisper-locale", "small"), _step("groq", "whisper-large-v3-turbo")]},
    "ascolto-preciso": {"label": "Ascolto preciso", "direction": "ascolto", "steps": [
        _step("groq", "whisper-large-v3"), _step("whisper-locale", "medium")]},
    "voce": {"label": "Voce", "direction": "voce", "steps": [
        _step("kokoro", voice="if_sara"), _step("piper", voice="it_IT-paola-medium")]},
    "voce-naturale": {"label": "Voce naturale", "direction": "voce", "steps": [
        _step("kokoro", voice="if_sara"), _step("google", voice="it-IT-Neural2-A"),
        _step("piper", voice="it_IT-paola-medium")]},
}

# Echo's own uses (the plugin's test box); callers declare theirs.
ECHO_USECASES = {
    "echo.prova.ascolto": {"label": "Prova · ascolto", "direction": "ascolto", "chain": "ascolto",
                           "help": "Il microfono della pagina Voce."},
    "echo.prova.voce": {"label": "Prova · voce", "direction": "voce", "chain": "voce",
                        "help": "Il tasto «parla» della pagina Voce."},
}


class ChainExhausted(RuntimeError):
    """Every step failed, is out of quota or has no key."""


def key_env(name: str) -> str:
    return "ECHO_KEY_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


class Blocks:
    def __init__(self, get: Callable[[str, Any], Any], registry: Callable[[], list[dict]] | None = None):
        self.get = get
        self._registry = registry or (lambda: [])
        self._lock = threading.Lock()
        self._exhausted: dict[tuple[str, str], float] = {}
        self._unavailable_logged: dict[tuple[str, str], str] = {}
        self._seen: dict[str, str] = {}          # undeclared use → direction
        self._reg_cache: tuple[float, list[dict]] = (0.0, [])

    # ── providers ────────────────────────────────────────────────────────────
    def providers(self) -> dict[str, dict]:
        raw = self.get(PROVIDERS_KEY, None)
        raw = raw if isinstance(raw, dict) and raw else DEFAULT_PROVIDERS
        out = {}
        for name, p in raw.items():
            if not isinstance(p, dict) or str(p.get("type") or "") not in STANDARDS:
                continue
            out[str(name)] = {"name": str(name), "type": str(p["type"]), "label": str(p.get("label") or name),
                              "url": str(p.get("url") or ""), "options": dict(p.get("options") or {}),
                              "key": os.getenv(key_env(str(name)), "").strip()}
        return out

    def provider_state(self, provider: dict) -> str:
        return STANDARDS[provider["type"]].state(provider)

    def describe_providers(self, language: str = "it") -> list[dict]:
        rows = []
        for p in self.providers().values():
            std = STANDARDS[p["type"]]
            state = self.provider_state(p)
            rows.append({"name": p["name"], "type": p["type"], "label": p["label"], "url": p["url"] or std.default_url,
                         "options": p["options"], "directions": list(std.directions), "key_env": key_env(p["name"]),
                         "key": bool(p["key"]), "needs_key": std.needs_key, "state": state,
                         "quota": self.exhausted_for(p["name"]),
                         "models": std.models(p) if state == "ready" else [],
                         "voices": std.voices(p, language) if state == "ready" and "voce" in std.directions else []})
        return rows

    # ── chains ───────────────────────────────────────────────────────────────
    def chains(self) -> dict[str, dict]:
        raw = self.get(CHAINS_KEY, None)
        raw = raw if isinstance(raw, dict) and raw else DEFAULT_CHAINS
        out = {}
        for name, c in raw.items():
            if not isinstance(c, dict) or c.get("direction") not in DIRECTIONS:
                continue
            steps = [{"provider": str(s.get("provider")), "model": str(s.get("model") or ""),
                      "voice": str(s.get("voice") or ""), "options": dict(s.get("options") or {})}
                     for s in c.get("steps") or [] if isinstance(s, dict) and s.get("provider")]
            out[str(name)] = {"label": str(c.get("label") or name), "direction": c["direction"], "steps": steps}
        return out

    def describe_chains(self) -> dict[str, dict]:
        provs = self.providers()
        out = {}
        for name, c in self.chains().items():
            steps = []
            for s in c["steps"]:
                p = provs.get(s["provider"])
                state = "missing" if p is None else self.provider_state(p)
                if p is not None and c["direction"] not in STANDARDS[p["type"]].directions:
                    state = "wrong_direction"
                until = self.exhausted_until(s["provider"], s["model"] or s["voice"])
                if state == "ready" and until:
                    state = "quota"
                steps.append({**s, "state": state,
                              "until": datetime.fromtimestamp(until).isoformat(timespec="minutes") if until else None})
            out[name] = {**c, "steps": steps}
        return out

    # ── quota state (memory: a restart costs at most one extra 429 per pair) ──
    def mark_exhausted(self, provider: str, model: str, exc: BaseException) -> None:
        retry = getattr(exc, "retry_after", None)
        until = time.time() + (retry if retry else 60 * float(self.get(COOLDOWN_KEY, 60) or 60))
        with self._lock:
            self._exhausted[(provider, model)] = until
        logger.warning("[🔄] event=voice_chain_step_exhausted provider=%s model=%s until=%s", provider, model,
                       datetime.fromtimestamp(until).isoformat(timespec="minutes"))

    def exhausted_until(self, provider: str, model: str) -> float:
        with self._lock:
            until = self._exhausted.get((provider, model), 0.0)
            if until and until <= time.time():
                self._exhausted.pop((provider, model), None)
                return 0.0
            return until

    def exhausted_for(self, provider: str) -> dict[str, str]:
        now = time.time()
        with self._lock:
            return {m: datetime.fromtimestamp(t).isoformat(timespec="minutes")
                    for (p, m), t in self._exhausted.items() if p == provider and t > now}

    def clear_exhausted(self, provider: str = "") -> None:
        with self._lock:
            for k in [k for k in self._exhausted if not provider or k[0] == provider]:
                del self._exhausted[k]

    # ── uses ─────────────────────────────────────────────────────────────────
    def _registry_usecases(self) -> list[dict]:
        at, rows = self._reg_cache
        if time.time() - at < 60:
            return rows
        try:
            found = []
            for svc in self._registry():
                module = str(svc.get("service_name") or svc.get("name") or "").strip().lower()
                for item in ((svc.get("capabilities") or {}).get("voice_usecases") or []):
                    if isinstance(item, dict) and item.get("id") and item.get("direction") in DIRECTIONS:
                        found.append({"id": str(item["id"]).lower(), "module": module,
                                      "label": str(item.get("label") or item["id"]), "direction": item["direction"],
                                      "chain": str(item.get("chain") or item["direction"]),
                                      "mode": str(item.get("mode") or "segui"), "help": str(item.get("help") or "")})
            self._reg_cache = (time.time(), found)
            return found
        except Exception as exc:
            logger.debug("event=voice_usecases_registry_failed error=%s", exc)
            self._reg_cache = (time.time() - 50, rows)
            return rows

    def declared_usecases(self) -> dict[str, dict]:
        out = {uc: {"id": uc, "module": "echo", "mode": "segui", **d} for uc, d in ECHO_USECASES.items()}
        for row in self._registry_usecases():
            out.setdefault(row["id"], row)
        with self._lock:
            seen = dict(self._seen)
        for uc, direction in seen.items():
            out.setdefault(uc, {"id": uc, "module": uc.split(".", 1)[0], "label": uc, "direction": direction,
                                "chain": direction, "mode": "segui", "undeclared": True,
                                "help": "Non dichiarato: usa la catena predefinita della direzione."})
        return out

    def describe_usecases(self) -> list[dict]:
        overrides = self.get(USECASES_KEY, None)
        overrides = overrides if isinstance(overrides, dict) else {}
        rows = []
        for uc, d in sorted(self.declared_usecases().items()):
            o = overrides.get(uc) if isinstance(overrides.get(uc), dict) else {}
            rows.append({**d, "suggested_chain": d["chain"], "chain": o.get("chain") or d["chain"],
                         "mode": o.get("mode") or d.get("mode") or "segui", "overridden": bool(o)})
        return rows

    def usecase_config(self, uc: str, direction: str) -> dict:
        uc = (uc or f"echo.prova.{direction}").strip().lower()
        decl = self.declared_usecases().get(uc)
        if decl is None:
            with self._lock:
                self._seen[uc] = direction
            decl = {"chain": direction, "mode": "segui"}
        overrides = self.get(USECASES_KEY, None)
        o = (overrides or {}).get(uc) if isinstance(overrides, dict) else None
        o = o if isinstance(o, dict) else {}
        chains = self.chains()
        chain = str(o.get("chain") or decl.get("chain") or direction)
        if chain not in chains or chains[chain]["direction"] != direction:
            chain = direction if direction in chains else next(
                (n for n, c in chains.items() if c["direction"] == direction), "")
        mode = str(o.get("mode") or decl.get("mode") or "segui")
        if mode == "segui":
            mode = str(self.get(MODE_KEY, "interna") or "interna")
        return {"id": uc, "chain": chain, "mode": mode}

    # ── running ──────────────────────────────────────────────────────────────
    def external_step(self, direction: str) -> tuple[dict, dict] | None:
        """``(provider, step)`` of the external engine for ``esterna`` (None = not usable for this direction)."""
        name = str(self.get(EXTERNAL_KEY, "") or "")
        p = self.providers().get(name)
        if not p or direction not in STANDARDS[p["type"]].directions or self.provider_state(p) != "ready":
            return None
        model = str(self.get(EXTERNAL_MODEL_KEY, "") or "")
        return p, {"provider": name, "model": model if direction == "ascolto" else "",
                   "voice": model if direction == "voce" else "", "options": {}}

    def run(self, uc: str, direction: str, call: Callable[[dict, dict], Any]) -> tuple[Any, dict]:
        """Run ``call(provider, step)`` on the use's chain (or the external engine). Returns ``(result, info)``
        with ``info = {use_case, chain, mode, step, provider, model, voice, fallback}``."""
        cfg = self.usecase_config(uc, direction)
        errors: list[str] = []
        if cfg["mode"] == "esterna":
            ext = self.external_step(direction)
            if ext is not None:
                p, s = ext
                try:
                    return call(p, s), {"use_case": cfg["id"], "chain": "", "mode": "esterna", "step": 0,
                                        "provider": p["name"], "model": s["model"], "voice": s["voice"],
                                        "fallback": False}
                except Exception as exc:
                    errors.append(f"{p['name']}: {exc}")
                    logger.warning("[🔄] event=voice_external_failed provider=%s error=%s", p["name"], str(exc)[:200])
            else:
                errors.append("motore esterno non pronto")
            if str(self.get(FALLBACK_KEY, "interna") or "interna") != "interna":
                raise ChainExhausted("; ".join(errors))
        chain = self.chains().get(cfg["chain"])
        if not chain:
            raise ChainExhausted(f"nessuna catena di {direction}")
        provs = self.providers()
        for i, s in enumerate(chain["steps"]):
            p = provs.get(s["provider"])
            what = s["model"] or s["voice"]
            reason = ("fornitore mancante" if p is None else
                      "direzione sbagliata" if direction not in STANDARDS[p["type"]].directions else
                      self.provider_state(p) if self.provider_state(p) != "ready" else
                      "quota" if self.exhausted_until(s["provider"], what) else "")
            if reason:
                self._log_unavailable(s["provider"], what, reason)
                errors.append(f"{s['provider']}: {reason}")
                continue
            try:
                result = call(p, s)
            except Exception as exc:
                if isinstance(exc, EngineError) and exc.status_code == 429:
                    self.mark_exhausted(s["provider"], what, exc)
                logger.warning("[🔄] event=voice_step_failed use_case=%s chain=%s step=%d provider=%s error=%s",
                               cfg["id"], cfg["chain"], i, s["provider"], str(exc)[:200])
                errors.append(f"{s['provider']}: {str(exc)[:120]}")
                continue
            return result, {"use_case": cfg["id"], "chain": cfg["chain"], "mode": "interna", "step": i,
                            "provider": s["provider"], "model": s["model"], "voice": s["voice"],
                            "fallback": i > 0 or cfg["mode"] == "esterna"}
        logger.error("event=voice_chain_exhausted use_case=%s chain=%s errors=%s", cfg["id"], cfg["chain"], errors)
        raise ChainExhausted("; ".join(errors) or "catena vuota")

    def _log_unavailable(self, provider: str, model: str, reason: str) -> None:
        key = (provider, model)
        if self._unavailable_logged.get(key) != reason:
            self._unavailable_logged[key] = reason
            logger.info("event=voice_chain_step_unavailable provider=%s model=%s reason=%s", provider, model, reason)
