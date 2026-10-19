"""Model chains and use cases — *which* models, in order, and *what for* (dossier ``2026-10-19-oracle-a-blocchi``).

A **chain** is a named, reusable ordered list of ``provider/model`` steps, like CSS ``font-family``
(setting ``oracle.chains``): a call tries the first usable step; a step out of quota (429,
``RESOURCE_EXHAUSTED``, usage limit…) is marked *exhausted until* its reset and skipped by **every** chain until
then; other errors (timeout, 5xx) move to the next step for this call only.

A **use case** is what a call is for: Oracle's own (``oracle.generale``, ``oracle.ragionamento``…) and the ones
each module declares in its Hub registration (``capabilities.llm_usecases``, see
``hestia_common.oracle_usecases``), e.g. ``scout.annunci``. Each points to a chain; Marko's overrides are the
setting ``oracle.usecases`` (``{use_case: {chain, mode, thinking}}``). An undeclared use case runs like
``oracle.generale`` and is listed too.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Iterator

logger = logging.getLogger("hestia_oracle.llm_chains")

# ── Defaults ─────────────────────────────────────────────────────────────────

def _step(provider: str, model: str, **extra) -> dict:
    return {"provider": provider, "model": model, **extra}


DEFAULT_CHAINS: dict[str, dict] = {
    "veloce": {"label": "Veloce", "steps": [
        _step("ollama", "gemma4:e4b"), _step("gemini", "gemini-2.5-flash-lite"),
        _step("gemini", "gemini-2.0-flash-lite")]},
    "potente": {"label": "Potente", "steps": [
        _step("ollama", "gemma4:e4b"), _step("gemini", "gemini-2.5-flash"),
        _step("gemini", "gemini-2.5-flash-lite")]},
    "codice": {"label": "Codice", "steps": [
        _step("ollama", "gemma4:e4b"), _step("gemini", "gemini-2.5-flash"), _step("gemini", "gemini-2.0-flash")]},
    # One step only: vectors of different models are not comparable (memory and document search would break).
    "embedding": {"label": "Embedding", "steps": [_step("ollama", "qwen3-embedding:0.6b")]},
    "visione": {"label": "Visione", "steps": [
        _step("ollama", "gemma4:e4b"), _step("gemini", "gemini-2.5-flash")]},
}
EMBEDDING_CHAIN = "embedding"

# Oracle's own use cases: id → (label, chain, thinking, help). Internal slot names (AgentBundle) in SLOTS.
ORACLE_USECASES: dict[str, tuple[str, str, str, str]] = {
    "oracle.generale": ("Uso generale", "veloce", "auto",
                        "Chat, classificazione, scelta degli strumenti, memoria."),
    "oracle.ragionamento": ("Ragionamento", "potente", "true", "Analisi lunghe e ragionamenti complessi."),
    "oracle.codice": ("Codice", "codice", "auto", "Generazione e correzione di codice nella chat."),
    "oracle.documenti": ("Documenti e immagini", "visione", "false", "Lettura di documenti, immagini e audio."),
    "oracle.embedding": ("Embedding (ricerca)", "embedding", "false",
                         "Vettori per memoria e documenti. Cambiarlo rende diversi i vettori già salvati."),
}
SLOTS = {"generic": "oracle.generale", "reasoning": "oracle.ragionamento", "code": "oracle.codice",
         "documents": "oracle.documenti", "embedding": "oracle.embedding"}
GENERAL = "oracle.generale"
MODES = [("segui", "Come il Cervello"), ("interna", "Interna"), ("esterna", "Esterna")]

# ── Quota state (memory: a restart costs at most one extra 429 per pair) ────────

_lock = threading.Lock()
_exhausted: dict[tuple[str, str], float] = {}          # (provider, model) → epoch when usable again
_seen_usecases: dict[str, float] = {}                   # undeclared use cases seen in calls → last seen
_answered: contextvars.ContextVar[dict | None] = contextvars.ContextVar("llm_chain_answered", default=None)

_QUOTA_WORDS = ("resource_exhausted", "quota", "rate limit", "rate_limit", "ratelimit", "usage limit",
                "too many requests", "limit reached", "credit balance")


class ChainExhausted(RuntimeError):
    """Every step of a chain failed or is out of quota."""


def _status(exc: BaseException) -> int:
    for obj in (exc, getattr(exc, "response", None)):
        for attr in ("status_code", "code", "status"):
            value = getattr(obj, attr, None) if obj is not None else None
            if isinstance(value, int):
                return value
    return 0


def is_quota_error(exc: BaseException) -> bool:
    """Out of quota / rate limited (any provider): skip the pair until its reset."""
    if _status(exc) == 429:
        return True
    text = str(exc).lower()
    return any(word in text for word in _QUOTA_WORDS)


def _midnight_pacific(now: float) -> float:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        local = datetime.fromtimestamp(now, tz)
        nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        return nxt.timestamp()
    except Exception:
        return now + 3600


def reset_at(exc: BaseException, now: float | None = None) -> float:
    """When an exhausted pair can be tried again: the provider's hint, else the cooldown setting.
    Gemini daily quotas reset at midnight Pacific time."""
    from core.services import oracle_settings
    now = time.time() if now is None else now
    text = str(exc)
    if re.search(r"per ?day|perday|daily", text, re.IGNORECASE):
        return _midnight_pacific(now)
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            return now + max(1.0, float(retry_after))
    except (TypeError, ValueError, AttributeError):
        pass
    m = re.search(r"retry[_ ]?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", text, re.IGNORECASE) \
        or re.search(r"retry in (\d+(?:\.\d+)?)\s*s", text, re.IGNORECASE)
    if m:
        return now + max(1.0, float(m.group(1)))
    return now + 60 * oracle_settings.get_int(oracle_settings.CHAIN_COOLDOWN, 1)


def mark_exhausted(provider: str, model: str, exc: BaseException) -> float:
    until = reset_at(exc)
    with _lock:
        _exhausted[(provider, model)] = until
    logger.warning("[🔄] event=llm_chain_step_exhausted provider=%s model=%s until=%s error=%s",
                   provider, model, datetime.fromtimestamp(until).isoformat(timespec="minutes"), str(exc)[:200])
    return until


def exhausted_until(provider: str, model: str) -> float:
    with _lock:
        until = _exhausted.get((provider, model), 0.0)
        if until and until <= time.time():
            _exhausted.pop((provider, model), None)
            return 0.0
        return until


def exhausted_for(provider: str) -> dict[str, str]:
    """Models of *provider* out of quota now → ISO time they come back."""
    now = time.time()
    with _lock:
        return {m: datetime.fromtimestamp(t).isoformat(timespec="minutes")
                for (p, m), t in _exhausted.items() if p == provider and t > now}


def clear_exhausted() -> None:
    with _lock:
        _exhausted.clear()


def last_answered() -> dict | None:
    """Step that answered the last chain call in this context (use case, chain, index, provider, model)."""
    return _answered.get()


# ── Settings readers ─────────────────────────────────────────────────────────

def chains() -> dict[str, dict]:
    """Every chain ``{name: {label, steps: [{provider, model, thinking?}]}}`` (setting ``oracle.chains``)."""
    from core.services import oracle_settings
    value = oracle_settings.settings.get(oracle_settings.CHAINS_KEY)
    if not isinstance(value, dict) or not value:
        value = DEFAULT_CHAINS
    out: dict[str, dict] = {}
    for name, raw in value.items():
        if not isinstance(raw, dict):
            continue
        steps = [s for s in (raw.get("steps") or []) if isinstance(s, dict)
                 and str(s.get("provider") or "").strip() and str(s.get("model") or "").strip()]
        if name == EMBEDDING_CHAIN:
            steps = steps[:1]
        out[str(name)] = {"label": str(raw.get("label") or name), "steps": steps}
    return out


def declared_usecases() -> dict[str, dict]:
    """Oracle's use cases + the ones modules declare in their Hub registration (``llm_usecases``)."""
    out = {uc: {"id": uc, "module": "oracle", "label": label, "chain": chain, "thinking": thinking, "help": help_,
                "mode": "segui"}
           for uc, (label, chain, thinking, help_) in ORACLE_USECASES.items()}
    for row in _registry_usecases():
        out.setdefault(row["id"], row)
    with _lock:
        seen = list(_seen_usecases)
    for uc in seen:
        out.setdefault(uc, {"id": uc, "module": uc.split(".", 1)[0], "label": uc, "chain": "",
                            "thinking": "auto", "help": "Non dichiarato dal modulo: usa la catena di «Uso generale».",
                            "mode": "segui", "undeclared": True})
    return out


_registry_cache: tuple[float, list[dict]] = (0.0, [])
_REGISTRY_TTL = 60.0


def _registry_usecases() -> list[dict]:
    """Use cases declared by modules in Hub's registry (cached 60 s; Hub down → last known)."""
    global _registry_cache
    at, rows = _registry_cache
    if time.time() - at < _REGISTRY_TTL:
        return rows
    try:
        import os
        from core.services.hub_client import HubClient
        services = HubClient(os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")).hub_get(
            "registry/services", default=[], timeout=4)
        if isinstance(services, dict):
            services = services.get("services") or list(services.values())
        found: list[dict] = []
        for svc in services or []:
            if not isinstance(svc, dict):
                continue
            module = str(svc.get("service_name") or svc.get("name") or "").strip().lower()
            for item in ((svc.get("capabilities") or {}).get("llm_usecases") or []):
                if isinstance(item, dict) and str(item.get("id") or "").strip():
                    found.append({"id": str(item["id"]).strip().lower(), "module": module,
                                  "label": str(item.get("label") or item["id"]), "chain": str(item.get("chain") or ""),
                                  "thinking": str(item.get("thinking") or "auto"),
                                  "mode": str(item.get("mode") or "segui"), "help": str(item.get("help") or "")})
        _registry_cache = (time.time(), found)
        return found
    except Exception as exc:
        logger.debug("event=llm_usecases_registry_failed error=%s", exc)
        _registry_cache = (time.time() - _REGISTRY_TTL + 10, rows)   # retry in 10 s
        return rows


def note_usecase(uc: str) -> None:
    """Remember an undeclared use case seen in a call, so the Modelli page can list it."""
    with _lock:
        _seen_usecases[uc] = time.time()


def usecase_config(uc: str) -> dict:
    """Effective config of a use case: ``{id, chain, thinking, mode, declared}`` (overrides → declaration →
    «Uso generale»). An unknown chain name falls back to «Uso generale»'s chain."""
    from core.services import oracle_settings
    uc = str(uc or GENERAL).strip().lower()
    declared = declared_usecases()
    decl = declared.get(uc)
    if decl is None:
        note_usecase(uc)
    overrides = oracle_settings.settings.get(oracle_settings.USECASES_KEY)
    overrides = overrides if isinstance(overrides, dict) else {}
    general = {**declared[GENERAL], **(overrides.get(GENERAL) or {})}
    own = dict(overrides.get(uc) or {}) if isinstance(overrides.get(uc), dict) else {}
    base = decl if decl and decl.get("chain") else general
    chain = str(own.get("chain") or base.get("chain") or general["chain"])
    all_chains = chains()
    if chain not in all_chains:
        logger.warning("[🔄] event=llm_usecase_unknown_chain use_case=%s chain=%s fallback=%s",
                       uc, chain, general["chain"])
        chain = general["chain"]
    mode = str(own.get("mode") or (decl or {}).get("mode") or "segui")
    return {"id": uc, "chain": chain, "thinking": str(own.get("thinking") or (decl or general).get("thinking")
                                                      or "auto").lower(),
            "mode": mode if mode in {m for m, _ in MODES} else "segui", "declared": decl is not None}


def chain_steps(uc: str) -> list[dict]:
    cfg = usecase_config(uc)
    return chains().get(cfg["chain"], {}).get("steps", [])


# ── Thinking per step ──────────────────────────────────────────────────────────

_family_cache: dict[str, str] = {}


def _ollama_family(provider: str, model: str) -> str:
    key = f"{provider}/{model}"
    if key not in _family_cache:
        import requests
        from core.services import llm_providers
        try:
            resp = requests.post(f"{llm_providers.url(provider)}/api/show", json={"name": model}, timeout=5)
            resp.raise_for_status()
            details = (resp.json() or {}).get("details") or {}
            _family_cache[key] = str(details.get("family", "") or "").strip().lower()
        except Exception as exc:
            logger.debug("event=thinking_auto_detect_failed model=%s error=%s — assuming False", model, exc)
            return ""
    return _family_cache[key]


def step_thinking(step: dict, usecase_thinking: str) -> bool:
    """Thinking flag of one step: the step's own value, else the use case's (auto = detected for Ollama,
    on for Claude/OpenAI-compatible types, off for Gemini)."""
    from core.services import llm_providers, oracle_settings
    raw = str(step.get("thinking") or usecase_thinking or "auto").strip().lower()
    if raw in ("true", "false"):
        return raw == "true"
    ptype = llm_providers.type_of(step["provider"])
    if ptype == "ollama":
        family = _ollama_family(step["provider"], step["model"])
        return bool(family) and family in set(oracle_settings.get_list(oracle_settings.THINKING_FAMILIES,
                                                                      lower=True))
    return ptype not in ("gemini", "")


# ── Chain agent ────────────────────────────────────────────────────────────────

class ChainAgent:
    """Same interface as ``UniversalAgent`` for one use case: every call walks the use case's chain.
    Settings are read at call time (live): changing a chain or a use case needs no restart."""

    def __init__(self, use_case: str, role_prompt: str = "", label: str = ""):
        self.use_case = use_case
        self.role_prompt = role_prompt
        self.label = label or use_case
        self._agents: dict[tuple, Any] = {}
        self._alock = threading.Lock()

    # ── steps ────────────────────────────────────────────────────────────
    def _agent(self, step: dict, thinking: bool):
        from agents.universal_agent import UniversalAgent
        key = (step["provider"], step["model"], thinking, self.role_prompt)
        with self._alock:
            agent = self._agents.get(key)
            if agent is None:
                agent = UniversalAgent(role_prompt=self.role_prompt, provider=step["provider"],
                                       model_name=step["model"], thinking=thinking, label=self.label)
                self._agents[key] = agent
            return agent

    def steps(self) -> list[tuple[int, dict, Any]]:
        """(index, step, agent) of the usable steps now: provider configured/available, not exhausted."""
        cfg = usecase_config(self.use_case)
        out = []
        for i, step in enumerate(chains().get(cfg["chain"], {}).get("steps", [])):
            if exhausted_until(step["provider"], step["model"]):
                continue
            from core.services import llm_providers
            ok, detail = llm_providers.available(step["provider"])
            if not ok:
                logger.debug("event=llm_chain_step_unavailable use_case=%s provider=%s detail=%s",
                             self.use_case, step["provider"], detail)
                continue
            out.append((i, step, self._agent(step, step_thinking(step, cfg["thinking"]))))
        return out

    def _first(self):
        steps = self.steps()
        return steps[0][2] if steps else None

    # Attributes callers read (model gauge, logs): those of the step that would answer now.
    @property
    def model_name(self) -> str:
        agent = self._first()
        return agent.model_name if agent else ""

    @property
    def provider(self) -> str:
        agent = self._first()
        return agent.provider_name if agent else ""

    @property
    def thinking(self) -> bool:
        agent = self._first()
        return bool(agent.thinking) if agent else False

    def _answered(self, index: int, step: dict) -> None:
        _answered.set({"use_case": self.use_case, "chain": usecase_config(self.use_case)["chain"], "step": index,
                       "provider": step["provider"], "model": step["model"]})

    def _failed(self, step: dict, exc: Exception, errors: list[str]) -> None:
        if is_quota_error(exc):
            mark_exhausted(step["provider"], step["model"], exc)
        else:
            logger.warning("[🔄] event=llm_chain_step_failed use_case=%s provider=%s model=%s error=%s",
                           self.use_case, step["provider"], step["model"], str(exc)[:200])
        errors.append(f"{step['provider']}/{step['model']}: {str(exc)[:160]}")

    def _exhausted(self, errors: list[str]) -> ChainExhausted:
        cfg = usecase_config(self.use_case)
        logger.error("event=llm_chain_exhausted use_case=%s chain=%s errors=%s", self.use_case, cfg["chain"],
                     " | ".join(errors) or "no usable step")
        return ChainExhausted(f"chain '{cfg['chain']}' ({self.use_case}): "
                              + (" | ".join(errors) or "no usable step (keys, logins or quota)"))

    def _call(self, method: str, *args, **kwargs):
        errors: list[str] = []
        for index, step, agent in self.steps():
            try:
                result = getattr(agent, method)(*args, **kwargs)
            except Exception as exc:
                self._failed(step, exc, errors)
                continue
            self._answered(index, step)
            return result
        raise self._exhausted(errors)

    # ── UniversalAgent interface ───────────────────────────────────────────
    def ask(self, user_message: str, thinking: bool | str | None = None) -> str:
        return self._call("ask", user_message, thinking=thinking)

    def ask_with_tools(self, user_message: str, tools: list[dict], thinking: bool | None = None) -> dict:
        return self._call("ask_with_tools", user_message, tools, thinking=thinking)

    def complete(self, prompt: str) -> str:
        return self._call("complete", prompt)

    def ask_with_attachment(self, *args, **kwargs) -> str:
        return self._call("ask_with_attachment", *args, **kwargs)

    def embed(self, text: str) -> list[float]:
        return self._call("embed", text)

    def ask_stream(self, user_message: str) -> Iterator[str]:
        """Stream from the first step that produces a token; a step failing before its first token passes
        to the next one; after the first token a failure ends the stream (callers keep what they got)."""
        errors: list[str] = []
        for index, step, agent in self.steps():
            started = False
            try:
                for token in agent.ask_stream(user_message):
                    if not started:
                        started = True
                        self._answered(index, step)
                    yield token
                return
            except Exception as exc:
                if started:
                    raise
                self._failed(step, exc, errors)
        raise self._exhausted(errors)


_chain_agents: dict[str, ChainAgent] = {}


def agent_for(use_case: str) -> ChainAgent:
    """Shared chain agent of a use case (module calls through ``/api/llm/generate``)."""
    use_case = str(use_case or GENERAL).strip().lower()
    with _lock:
        agent = _chain_agents.get(use_case)
        if agent is None:
            agent = _chain_agents[use_case] = ChainAgent(use_case, label=use_case)
        return agent


def claude_code_model(use_case: str = "forge.codice") -> str:
    """Model for Claude Code runs (Forge engine ``claude``): the first ``claude_cli`` step of the use case's
    chain, else "" (Claude Code's own default)."""
    from core.services import llm_providers
    for step in chain_steps(use_case):
        if llm_providers.type_of(step["provider"]) == "claude_cli":
            return step["model"]
    return ""


def chains_view() -> dict:
    """Chains with each step's provider state (WebUI Modelli, ``GET /api/llm/chains``)."""
    from core.services import llm_providers
    out = {}
    for name, chain in chains().items():
        rows = []
        for step in chain["steps"]:
            ok, detail = llm_providers.available(step["provider"])
            until = exhausted_until(step["provider"], step["model"])
            rows.append({**step, "available": ok, "detail": detail,
                         "exhausted_until": datetime.fromtimestamp(until).isoformat(timespec="minutes")
                         if until else ""})
        out[name] = {"label": chain["label"], "steps": rows, "single_step": name == EMBEDDING_CHAIN}
    return out


def usecases_view() -> list[dict]:
    """Every use case (Oracle's, modules', undeclared seen) with its effective chain and mode."""
    rows = []
    for uc, decl in declared_usecases().items():
        cfg = usecase_config(uc)
        rows.append({**decl, "effective_chain": cfg["chain"], "effective_mode": cfg["mode"],
                     "effective_thinking": cfg["thinking"]})
    return sorted(rows, key=lambda r: (r["module"] != "oracle", r["module"], r["id"]))
