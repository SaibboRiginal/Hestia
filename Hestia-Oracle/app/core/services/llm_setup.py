"""Guided setup of the brain (docs/work/2026-10-30-one-click-setup §4.2 «Cervello»).

What the setup screen needs from Oracle, and only from Oracle (it owns the providers):
- ``runtimes(vram_gb, hosts)``: the programs that run models at home (Ollama, LM Studio, Jan, llama.cpp, vLLM), on
  this computer and on the other computers of the home network the user names (e.g. Hestia on a Raspberry, the
  models on the PC with the video card), found by asking their usual port, each with the models it really has and a warning on those bigger than the video
  card. Hestia keeps no model list of its own for them: the program knows;
- ``CATALOG``: a few suggested models per hardware tier, shown only when nothing is installed (Ollama downloads them);
- ``recommend(vram_gb, ram_gb)``: the tier for this PC and its preselected models;
- ``test(provider, model)``: one tiny real call with a model the provider really lists, answer in plain words;
- ``apply(...)``: adds a found program as a provider block, writes ``oracle.chains`` from the user's choice (local
  program + model, cloud services in order with their models, memory (embedding) models in order, only when the user
  changed them: every stored vector keeps the model that made it, so nothing is re-read);
- ``pull`` / ``pulls``: Ollama downloads in the background with progress (``/api/pull`` stream), so the screen can
  show them while the user answers the next questions.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_oracle.llm_setup")

# Tier → models. Sizes are the download size in GB (what the user waits for), "good" is one short line.
CATALOG: list[dict[str, Any]] = [
    {"tier": "cpu", "label": "Without a graphics card", "max_vram": 5.9, "chat": [
        {"model": "gemma4:e4b", "size_gb": 3.3, "good": "Light, answers everyday things well."}]},
    {"tier": "8gb", "label": "Graphics card with 6–11 GB", "max_vram": 11.9, "chat": [
        {"model": "qwen3:8b", "size_gb": 5.2, "good": "Good balance between speed and reasoning."},
        {"model": "gemma4:e4b", "size_gb": 3.3, "good": "Lighter and faster."}]},
    {"tier": "16gb", "label": "Graphics card with 12 GB or more", "max_vram": 999, "chat": [
        {"model": "qwen3:14b", "size_gb": 9.3, "good": "Reasons better, great for tools."},
        {"model": "qwen3:8b", "size_gb": 5.2, "good": "Faster, a bit less accurate."}]},
]
EMBEDDING_MODEL = {"model": "qwen3-embedding:0.6b", "size_gb": 0.6, "good": "Memory needs it to find things again."}
RECIPES = ("locale", "cloud", "entrambi", "claude")
CHAT_CHAINS = ("veloce", "potente", "codice", "visione")


def recommend(vram_gb: float = 0, ram_gb: float = 0) -> dict[str, Any]:
    """Tier for the detected hardware, its preselected chat model and the recipe to preselect."""
    vram = float(vram_gb or 0)
    tier = next(t for t in CATALOG if vram <= t["max_vram"])
    recipe = "entrambi" if vram >= 8 else ("cloud" if float(ram_gb or 0) and float(ram_gb) < 12 else "entrambi")
    return {"tier": tier["tier"], "label": tier["label"], "chat": tier["chat"], "model": tier["chat"][0]["model"],
            "embedding": EMBEDDING_MODEL, "recipe": recipe}


def local_models(vram_gb: float = 0) -> list[dict[str, Any]]:
    """Every chat model already in Ollama (embedding models left out), biggest first, each with ``fits``: False when
    the file is bigger than the video card (it still runs, slower, partly on the CPU). Ollama knows the models; the
    curated ``CATALOG`` is only a suggestion when Ollama has none."""
    import requests
    from core.services import llm_providers
    if not llm_providers.get("ollama"):
        return []
    return _ollama_models(llm_providers.url("ollama"), vram_gb) or []


def _ollama_models(base: str, vram_gb: float = 0, timeout: float = 5) -> list[dict[str, Any]] | None:
    """The chat models of the Ollama at ``base`` (None when nothing answers there)."""
    import requests
    try:
        resp = requests.get(f"{base.rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
        rows = (resp.json() or {}).get("models", [])
    except Exception as exc:
        logger.info("[🔄] event=llm_setup_local_models_failed base=%s error=%s", base, str(exc)[:160])
        return None
    vram = float(vram_gb or 0)
    out = []
    for m in rows:
        name = m.get("name") or m.get("model") or ""
        details = m.get("details") or {}
        family = " ".join([str(details.get("family") or "")] + [str(f) for f in details.get("families") or []]).lower()
        if not name or "embed" in name.lower() or "bert" in family:
            continue
        size_gb = round(float(m.get("size") or 0) / 1e9, 1)
        out.append({"model": name, "size_gb": size_gb, "params": details.get("parameter_size") or "",
                    "quant": details.get("quantization_level") or "",
                    # ~10% over the file for the context; unknown card → no warning
                    "fits": not vram or size_gb * 1.1 <= vram})
    return sorted(out, key=lambda r: (not r["fits"], -r["size_gb"]))


def _ollama_embed(base: str) -> list[str]:
    import requests
    try:
        rows = requests.get(f"{base.rstrip('/')}/api/tags", timeout=3).json().get("models", [])
    except Exception:
        return []
    return [str(m.get("name")) for m in rows if m.get("name") and _is_embedding(str(m.get("name")),
                                                                            str((m.get("details") or {}).get("family") or ""))]


# Programs that serve models on the user's PC with the OpenAI-compatible API (``/v1/models``), on their usual port.
# Probed on the same host as Ollama (``host.docker.internal`` from the containers). Name = the provider block it becomes.
RUNTIMES: list[dict[str, Any]] = [
    {"name": "lmstudio", "label": "LM Studio", "port": 1234, "site": "https://lmstudio.ai"},
    {"name": "jan", "label": "Jan", "port": 1337, "site": "https://jan.ai"},
    {"name": "llamacpp-pc", "label": "llama.cpp", "port": 8080, "site": "https://github.com/ggml-org/llama.cpp"},
    {"name": "vllm", "label": "vLLM", "port": 8000, "site": "https://docs.vllm.ai"},
]
OLLAMA_SITE = "https://ollama.com/download"


def _is_embedding(name: str, family: str = "") -> bool:
    from core.services import llm_providers   # one rule for every picker (llm_providers.is_embedding_name)
    return llm_providers.is_embedding_name(name, family)


def _host() -> str:
    """Where the PC's own programs answer, seen from Oracle: the host of the infrastructure Ollama address."""
    from urllib.parse import urlsplit
    from core.services import llm_providers
    return urlsplit(llm_providers.ollama_host()).hostname or "localhost"


def _probe_openai(base: str) -> list[str] | None:
    """Model ids of an OpenAI-compatible server, or None when nothing answers there (short timeout: most are off)."""
    import requests
    try:
        resp = requests.get(f"{base}/models", timeout=1.5)
        if not resp.ok:
            return None
        data = (resp.json() or {}).get("data")
        if not isinstance(data, list):
            return None
        return [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")]
    except Exception:
        return None


HOST_RE = re.compile(r"[A-Za-z0-9.-]{1,120}")


def home_hosts(hosts: str | list[str] | None) -> list[str]:
    """The other computers of the home network to look on (names or addresses, at most 4), checked."""
    raw = hosts.split(",") if isinstance(hosts, str) else list(hosts or [])
    out: list[str] = []
    for h in raw:
        h = str(h).strip().removeprefix("http://").removeprefix("https://").split("/")[0].split(":")[0]
        if h and HOST_RE.fullmatch(h) and h != _host() and h not in out:
            out.append(h)
    return out[:4]


def _slug(host: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")


def runtimes(vram_gb: float = 0, hosts: str | list[str] | None = None) -> list[dict[str, Any]]:
    """Every program for local models: on this computer Ollama first, then the OpenAI-compatible ones of
    ``RUNTIMES``; then the same programs on each other computer of ``hosts``. Each row: ``{name, label, type, url,
    host, site, found, configured, models: [{model, size_gb, params, quant, fits}], embed: [model]}`` (``host`` empty
    = this computer). A program already configured as a block (same address) keeps its block name; one on another
    computer is named ``<program>-<address>``."""
    from concurrent.futures import ThreadPoolExecutor
    from core.services import llm_providers
    ollama = {"name": "ollama", "label": "Ollama", "type": "ollama", "host": "",
              "url": llm_providers.url("ollama") if llm_providers.get("ollama") else "",
              "site": OLLAMA_SITE, "configured": bool(llm_providers.get("ollama")), "found": False,
              "models": [], "embed": []}
    if ollama["configured"] and _ollama_up():
        ollama["found"] = True
        ollama["models"] = local_models(vram_gb)
        ollama["embed"] = [m for m in llm_providers.list_models("ollama") if _is_embedding(m)]
    blocks = {llm_providers.url(n).rstrip("/"): n for n in llm_providers.providers()
              if llm_providers.type_of(n) in ("openai", "ollama")}
    probes: list[tuple[dict, str, str]] = [(spec, _host(), f"http://{_host()}:{spec['port']}/v1") for spec in RUNTIMES]
    others = home_hosts(hosts)
    for host in others:
        probes.append(({"name": "ollama", "label": "Ollama", "port": 11434, "site": OLLAMA_SITE}, host, f"http://{host}:11434"))
        probes += [(spec, host, f"http://{host}:{spec['port']}/v1") for spec in RUNTIMES]

    def ask(probe):
        spec, host, base = probe
        if spec["name"] == "ollama":
            return _ollama_models(base, vram_gb, timeout=1.5), _ollama_embed(base)
        ids = _probe_openai(base)
        return ([{"model": m, "size_gb": 0, "params": "", "quant": "", "fits": True} for m in ids if not _is_embedding(m)]
                if ids is not None else None), [m for m in ids or [] if _is_embedding(m)]
    with ThreadPoolExecutor(max_workers=min(16, len(probes))) as pool:
        answers = list(pool.map(ask, probes))
    rows = [ollama]
    for (spec, host, base), (models, embed) in zip(probes, answers):
        remote = host != _host()
        if remote and models is None:
            continue                       # another computer: only what answers there
        own = f"{spec['name']}-{_slug(host)}" if remote else spec["name"]
        rows.append({"name": blocks.get(base.rstrip("/"), own), "label": f"{spec['label']} · {host}" if remote else spec["label"],
                     "type": "ollama" if spec["name"] == "ollama" else "openai", "url": base, "host": host if remote else "",
                     "site": spec["site"], "configured": base.rstrip("/") in blocks, "found": models is not None,
                     # an OpenAI-compatible program does not say the size: no warning rather than a wrong one
                     "models": models or [], "embed": embed})
    return rows


def ensure_runtime(name: str, runtime: dict | None = None) -> bool:
    """A found program becomes a provider block the first time the user picks it: type ``openai`` (or ``ollama`` on
    another computer) with its address. ``runtime {url, type, label}`` comes from ``runtimes`` (another computer);
    without it the program is one of ``RUNTIMES`` on this computer."""
    from core.services import llm_providers, oracle_settings
    if llm_providers.providers().get(name):
        return True
    runtime = runtime or {}
    url = str(runtime.get("url") or "")
    spec = next((r for r in RUNTIMES if r["name"] == name), None)
    if url:
        host = urlsplit(url).hostname or ""
        if not url.startswith("http://") or not HOST_RE.fullmatch(host):
            return False
        entry = {"type": "ollama" if runtime.get("type") == "ollama" else "openai",
                 "label": str(runtime.get("label") or name)[:80], "url": url}
    elif spec is not None:
        entry = {"type": "openai", "label": tr("{0} (local)", spec['label']), "url": f"http://{_host()}:{spec['port']}/v1"}
    else:
        return False
    current = oracle_settings.settings.get(oracle_settings.PROVIDERS_KEY)
    provs = {k: dict(v) for k, v in (current if isinstance(current, dict) and current
                                     else llm_providers.DEFAULT_PROVIDERS).items()}
    provs[name] = entry
    ok = oracle_settings.settings.put(oracle_settings.PROVIDERS_KEY, provs, actor="user",
                                      reason=tr("Guided setup: {0}", entry['label']))
    logger.info("event=llm_setup_runtime_added provider=%s ok=%s", name, ok)
    return bool(ok)


def catalog(vram_gb: float = 0, ram_gb: float = 0, hosts: str | list[str] | None = None) -> dict[str, Any]:
    from core.services import llm_chains, llm_providers
    installed = llm_providers.list_models("ollama") if llm_providers.get("ollama") else []
    cloud = [{"name": p["name"], "label": p["label"], "type": p["type"], "key_env": p["key_env"],
              "key_set": p["key_set"], "available": p["available"]}
             for p in llm_providers.public_view() if not llm_providers.is_local(p["name"])]
    found = runtimes(vram_gb, hosts)
    emb_steps = (llm_chains.chains().get(llm_chains.EMBEDDING_CHAIN) or {}).get("steps") or []
    embedding = (emb_steps or [{}])[0]
    return {"recommended": recommend(vram_gb, ram_gb), "tiers": CATALOG, "installed": installed,
            "local": next((r["models"] for r in found if r["name"] == "ollama"), []), "runtimes": found,
            "embedding": {"provider": embedding.get("provider", ""), "model": embedding.get("model", "")},
            "embedding_steps": [{"provider": s.get("provider", ""), "model": s.get("model", "")} for s in emb_steps],
            "ollama": found[0]["found"], "cloud": cloud, "recipes": list(RECIPES)}


def _ollama_up() -> bool:
    import requests
    from core.services import llm_providers
    try:
        return requests.get(f"{llm_providers.url('ollama')}/api/version", timeout=3).ok
    except Exception:
        return False


# ── Prova ───────────────────────────────────────────────────────────────────

def _pick_model(provider: str, wanted: str, listed: list[str]) -> str:
    """The model to try: the one asked if the provider lists it (or lists nothing), else Hestia's default for it if
    listed, else the provider's first chat model. So a retired name never blocks the «Prova»."""
    chat = [m for m in listed if not _is_embedding(m)]
    if wanted and (not listed or wanted in listed):
        return wanted
    default = _default_model(provider)
    if default and (not listed or default in listed):
        return default
    from core.services import llm_providers
    preferred = ([m for m in chat if "flash-lite" in m] or [m for m in chat if "flash" in m]
                 if llm_providers.type_of(provider) == "gemini" else [])
    return (preferred or chat or [wanted or default])[0]


def _list_checked(provider: str) -> tuple[list[str] | None, str]:
    """The provider's model list read with its key, without generating anything (zero tokens). Returns
    ``(models, "")`` when the service answered, ``(None, reason)`` when the key is wrong or it does not answer, and
    ``(None, "")`` when this kind of service has no list to read (then a tiny call is the only check)."""
    import requests
    from core.services import llm_providers
    ptype = llm_providers.type_of(provider)
    key = llm_providers.api_key(provider)
    base = llm_providers.url(provider).rstrip("/")
    try:
        if ptype == "gemini":
            resp = requests.get(f"{base}/v1beta/models", params={"key": key, "pageSize": 1000}, timeout=10)
            ids = lambda data: [str(m.get("name") or "").removeprefix("models/") for m in data.get("models") or []
                                if {"generateContent", "embedContent"} & set(m.get("supportedGenerationMethods") or [])]
        elif ptype in ("openai", "llamacpp"):
            resp = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=10)
            ids = lambda data: [str(m.get("id")) for m in data.get("data") or [] if m.get("id")]
        elif ptype == "anthropic":
            resp = requests.get(f"{base or 'https://api.anthropic.com'}/v1/models", timeout=10,
                                headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
            ids = lambda data: [str(m.get("id")) for m in data.get("data") or [] if m.get("id")]
        else:
            return None, ""
    except Exception as exc:
        logger.info("[🔄] event=llm_setup_list_failed provider=%s error=%s", provider, str(exc)[:160])
        return None, tr("It does not answer: check the connection.")
    if resp.status_code in (400, 401, 403):
        return None, tr("The key is not valid.")
    if resp.status_code == 429:
        return [], ""
    if not resp.ok:
        return None, tr("It does not answer (error {0}).", resp.status_code)
    try:
        return [m for m in ids(resp.json() or {}) if m], ""
    except ValueError:
        return None, tr("Invalid answer from the service.")


def test(provider: str, model: str = "") -> dict[str, Any]:
    """«Prova» without spending tokens: reading the model list with the key proves the key works and gives the models
    for the picker. Returns ``{ok, detail, model, models}`` in words a person understands; ``model`` = the one to
    preselect (the one asked, else Hestia's default, else the cheapest-looking listed). Only a service with no list
    to read gets one tiny real call."""
    from core.services import llm_providers
    if not llm_providers.get(provider):
        return {"ok": False, "detail": tr("This service is not configured.")}
    ok, why = llm_providers.available(provider)
    if not ok:
        return {"ok": False, "detail": tr("The key is missing.") if "not set" in why else why}
    listed, error = _list_checked(provider)
    if error:
        return {"ok": False, "detail": error, "models": []}
    # only chat models for «Modelli» (no speech, pictures, live audio); the embedding ones go to «Memoria»
    models = None if listed is None else [m for m in listed if is_chat(m)]
    embed = [m for m in listed or [] if _is_embedding(m)]
    if models is not None:
        if not models:
            return {"ok": True, "detail": tr("The key works (today's quota might be used up)."),
                    "model": model or _default_model(provider), "models": []}
        chosen = _pick_model(provider, model, models)
        logger.info("event=llm_setup_test_ok provider=%s models=%s via=list", provider, len(models))
        return {"ok": True, "detail": tr("The key works: {0} models available.", len(models)), "model": chosen,
                "models": models, "recommended": recommended(provider, models), "embed": embed}
    return _tiny_call(provider, model or _default_model(provider))


def is_chat(name: str) -> bool:
    """A model to chat with: not an embedding one, not speech/pictures/live audio (the «Modelli» step lists only these)."""
    from core.services import llm_providers
    return llm_providers.is_chat_name(name)


def recommended(provider: str, listed: list[str], limit: int = 2) -> list[str]:
    """The models preselected for a service once its key works, in order (the first answers, the next ones take over
    when it fails or its quota ends): Hestia's default models that the service still lists, then the cheapest-looking
    chat models it lists. The user may change them; nothing is asked when the key is right."""
    from core.services import llm_chains, llm_providers
    chat = [m for m in listed if is_chat(m)]
    out: list[str] = []
    for chain in llm_chains.DEFAULT_CHAINS.values():
        for step in chain["steps"]:
            if step["provider"] == provider and step["model"] in chat and step["model"] not in out:
                out.append(step["model"])
    if llm_providers.type_of(provider) == "gemini":
        stable = [m for m in chat if "preview" not in m and "exp" not in m]
        for word in ("flash-lite", "flash"):
            out += [m for m in stable if word in m and m not in out][:1]
    out += [m for m in chat if m not in out]
    return out[:limit]


def _tiny_call(provider: str, model: str) -> dict[str, Any]:
    """One tiny real call («ok»), for services whose model list cannot be read."""
    from agents.universal_agent import UniversalAgent
    if not model:
        return {"ok": False, "detail": tr("No model to try."), "models": []}
    started = time.monotonic()
    try:
        answer = UniversalAgent(role_prompt="", provider=provider, model_name=model, thinking=False,
                                label="oracle.setup").ask("Reply only with: ok")
    except Exception as exc:
        text = str(exc)
        logger.info("[🔄] event=llm_setup_test_failed provider=%s model=%s error=%s", provider, model, text[:200])
        low = text.lower()
        if any(w in low for w in ("401", "403", "api key", "invalid", "permission", "unauthorized")):
            return {"ok": False, "detail": tr("The key is not valid."), "models": []}
        if any(w in low for w in ("429", "quota", "resource_exhausted")):
            return {"ok": True, "detail": tr("The key works, but today's quota is used up."), "model": model, "models": []}
        return {"ok": False, "detail": tr("Does not answer: ") + text[:160], "models": []}
    ms = int((time.monotonic() - started) * 1000)
    logger.info("event=llm_setup_test_ok provider=%s model=%s ms=%s via=call", provider, model, ms)
    return {"ok": bool(str(answer or "").strip()), "detail": tr("It works ({0}, {1:.1f} s).", model, ms / 1000), "model": model,
            "models": []}


def _default_model(provider: str) -> str:
    from core.services import llm_chains
    for chain in llm_chains.DEFAULT_CHAINS.values():
        for step in chain["steps"]:
            if step["provider"] == provider:
                return step["model"]
    from core.services import llm_providers
    models = [m for m in llm_providers.list_models(provider) if not _is_embedding(m)]
    return models[0] if models else ""


# ── Applica la scelta ───────────────────────────────────────────────────────

def plan_chains(recipe: str, local_model: str, cloud: list[str], current: dict[str, dict],
                local_provider: str = "ollama", cloud_models: dict[str, list[str] | str] | None = None,
                embedding: dict | None = None, modes: dict[str, dict] | None = None,
                order: list[dict] | None = None) -> dict[str, dict]:
    """New ``oracle.chains`` for a recipe. ``order``: the setup's «Scelti» list (``{provider, model}``, model empty =
    every model of that service) to put the chosen steps in the user's order, the local one included; a step it does
    not name keeps its place after the named ones. ``modes``: per chat chain (``potente``, ``codice``, ``visione``) a model
    chosen for that mode only (``{provider, model}``): it answers first there, the general choice follows as fallback. Pure function (tests): local steps use ``local_provider``/``local_model``;
    each chosen cloud service uses the models picked for it in order (``cloud_models``, one or more: the next one takes
    over when the first fails), or its default models; the embedding
    chain changes only when ``embedding`` names another model; chains the setup does not know stay."""
    from core.services import llm_chains, llm_providers
    out = {name: dict(chain) for name, chain in current.items()}
    cloud = [c for c in cloud if c]
    picked = _as_lists(cloud_models)

    def cloud_steps_of(default_steps: list[dict]) -> list[dict]:
        steps: list[dict] = []
        for provider in cloud:
            if provider in picked:
                steps.extend({"provider": provider, "model": m} for m in picked[provider])
                continue
            own = [dict(s) for s in default_steps if s["provider"] == provider]
            if not own:   # a chosen provider the default chain does not list: its first default model
                model = _default_model(provider)
                own = [{"provider": provider, "model": model}] if model else []
            steps.extend(own)
        return [s for s in steps if not llm_providers.is_local(s["provider"])]

    for name in CHAT_CHAINS:
        default = llm_chains.DEFAULT_CHAINS.get(name, {"label": name.capitalize(), "steps": []})
        local_steps = [{"provider": local_provider or "ollama", "model": local_model}] if local_model else []
        cloud_steps = cloud_steps_of(default["steps"])
        if recipe == "locale":
            steps = local_steps
        elif recipe == "cloud":
            steps = cloud_steps
        else:   # entrambi, claude (the chains stay the fallback of the external brain)
            steps = local_steps + cloud_steps
        steps = _in_order(steps, order)
        own = (modes or {}).get(name) or {}
        own_steps = [{"provider": p, "model": m} for p, m in
                     ((s.get("provider") or "ollama", s.get("model") or _default_model(s.get("provider") or "ollama"))
                      for s in (own.get("steps") or []) if isinstance(s, dict)) if m]
        if own_steps:   # the mode has its own whole list, in the user's order
            steps = own_steps
        elif own.get("model"):
            first = {"provider": own.get("provider") or "ollama", "model": own["model"]}
            steps = [first] + [s for s in steps if s != first]
        if steps:
            out[name] = {"label": out.get(name, default).get("label") or default["label"], "steps": steps}
    if "cloud" in out and cloud:
        steps = _in_order(cloud_steps_of(llm_chains.DEFAULT_CHAINS["cloud"]["steps"]), order)
        if steps:
            out["cloud"] = {"label": out["cloud"].get("label") or "Cloud", "steps": steps}
    wanted = [{"provider": s["provider"], "model": s["model"]} for s in embedding_steps(embedding)]
    if wanted:
        now = [{"provider": s.get("provider"), "model": s.get("model")}
               for s in (out.get(llm_chains.EMBEDDING_CHAIN) or {}).get("steps") or []]
        if now != wanted:
            out[llm_chains.EMBEDDING_CHAIN] = {"label": "Embedding", "steps": wanted}
    return out


def embedding_steps(embedding: dict | None) -> list[dict]:
    """The memory models chosen in the setup, in order: ``{steps: [{provider, model, url?, type?, label?}]}`` (the
    first is used, the next ones when it is not available) or one ``{provider, model}`` (older clients)."""
    emb = embedding or {}
    raw = emb.get("steps") if isinstance(emb.get("steps"), list) else [emb]
    out = []
    for s in raw:
        if isinstance(s, dict) and s.get("model"):
            step = {"provider": s.get("provider") or "ollama", "model": str(s["model"])}
            step.update({k: s[k] for k in ("url", "type", "label") if s.get(k)})
            if not any(o["provider"] == step["provider"] and o["model"] == step["model"] for o in out):
                out.append(step)
    return out


def _in_order(steps: list[dict], order: list[dict] | None) -> list[dict]:
    """``steps`` sorted by the user's «Scelti» order; steps it does not name stay after, in their own order."""
    wanted = [o for o in (order or []) if isinstance(o, dict) and o.get("provider")]
    if not wanted:
        return steps

    def rank(item: tuple[int, dict]) -> tuple[int, int]:
        i, s = item
        for pos, o in enumerate(wanted):
            if o["provider"] == s["provider"] and (not o.get("model") or o["model"] == s["model"]):
                return (0, pos)
        return (1, i)
    return [s for _, s in sorted(enumerate(steps), key=rank)]


def _as_lists(cloud_models: dict | None) -> dict[str, list[str]]:
    """``{service: [models]}`` from the setup's choice (a single name is still accepted)."""
    out: dict[str, list[str]] = {}
    for k, v in (cloud_models or {}).items():
        models = [v] if isinstance(v, str) else list(v or [])
        models = [str(m) for m in models if m]
        if models:
            out[k] = list(dict.fromkeys(models))
    return out


def summary(chains: dict[str, dict]) -> str:
    """One sentence: who answers first, and who if not («Ti risponde X sul tuo computer; se non c'è, Y.»)."""
    from core.services import llm_providers
    steps = (chains.get("veloce") or {}).get("steps") or []
    if not steps:
        return tr("No model chosen.")

    def say(step: dict) -> str:
        where = tr("on your computer") if llm_providers.is_local(step["provider"]) else tr("in the cloud")
        return f"{step['model']} {where}"
    text = tr("{0} answers you", say(steps[0]))
    if len(steps) > 1:
        text += tr("; if missing, {0}", say(steps[1]))
    return text + "."


def _live_models(cloud: list[str], picked: dict[str, list[str]]) -> dict[str, list[str]]:
    """For each chosen service without a picked model whose default models it no longer lists (a retired alias),
    a model it does list: the chains never start with a name that answers «not found»."""
    from core.services import llm_chains, llm_providers
    out: dict[str, list[str]] = {}
    for provider in cloud:
        if picked.get(provider) or llm_providers.type_of(provider) == "claude_cli":
            continue
        listed = llm_providers.list_models(provider)
        defaults = {s["model"] for c in llm_chains.DEFAULT_CHAINS.values() for s in c["steps"] if s["provider"] == provider}
        if listed and defaults and not defaults <= set(listed):
            models = recommended(provider, listed)
            if models:
                out[provider] = models
                model = models[0]
                logger.info("[🔄] event=llm_setup_default_model_gone provider=%s using=%s", provider, model)
    return out


def apply(recipe: str, local_model: str = "", cloud: list[str] | None = None, local_provider: str = "ollama",
          cloud_models: dict[str, list[str] | str] | None = None, embedding: dict | None = None,
          local_runtime: dict | None = None, modes: dict[str, dict] | None = None,
          order: list[dict] | None = None) -> dict[str, Any]:
    from core.services import llm_chains, oracle_settings
    if recipe not in RECIPES:
        return {"ok": False, "detail": tr("Invalid choice.")}
    local_provider = local_provider or "ollama"
    if recipe != "cloud" and local_model and not ensure_runtime(local_provider, local_runtime):
        return {"ok": False, "detail": tr("I can't add that program to the settings.")}
    for emb in embedding_steps(embedding):
        if not ensure_runtime(emb["provider"], {k: emb.get(k, "") for k in ("url", "type", "label")}):
            return {"ok": False, "detail": tr("I can't add that program to the settings.")}
    modes = {k: v for k, v in (modes or {}).items()
             if k in CHAT_CHAINS and isinstance(v, dict) and (v.get("model") or v.get("steps"))}
    for own in modes.values():
        for step in ([s for s in own.get("steps") or [] if isinstance(s, dict)] or [own]):
            if (step.get("model") or step.get("url")) and not ensure_runtime(step.get("provider") or "ollama", {k: step.get(k, "") for k in ("url", "type", "label")}):
                return {"ok": False, "detail": tr("I can't add that program to the settings.")}
    chosen = _as_lists(cloud_models)
    cloud_models = {**_live_models(list(cloud or []), chosen), **chosen}
    chains = plan_chains(recipe, local_model if recipe != "cloud" else "", list(cloud or []), llm_chains.chains(),
                         local_provider=local_provider, cloud_models=cloud_models, embedding=embedding, modes=modes,
                         order=order)
    if not oracle_settings.settings.put(oracle_settings.CHAINS_KEY, chains, actor="user", reason=tr("Guided setup")):
        return {"ok": False, "detail": tr("The settings did not accept the choice.")}
    if recipe == "claude":
        for key, value in ((oracle_settings.BRAIN_MODE, "esterna"), (oracle_settings.BRAIN_AGENT, "claude"),
                           (oracle_settings.BRAIN_FALLBACK, "interna")):
            oracle_settings.settings.put(key, value, actor="user", reason=tr("Guided setup"))
    logger.info("event=llm_setup_applied recipe=%s local=%s/%s cloud=%s", recipe, local_provider, local_model or "-",
                ",".join(cloud or []) or "-")
    text = summary(chains)
    if recipe == "claude":
        text = tr("Claude answers you with your subscription; if missing, ") + text[0].lower() + text[1:]
    return {"ok": True, "detail": text, "chains": chains}


def machine() -> dict[str, Any]:
    """Where the local models run now: ``{address, label}`` (empty address = this machine)."""
    from urllib.parse import urlsplit
    from core.services import llm_providers, oracle_settings
    current = oracle_settings.settings.get(oracle_settings.PROVIDERS_KEY)
    provs = current if isinstance(current, dict) and current else llm_providers.DEFAULT_PROVIDERS
    entry = provs.get("ollama") or {}
    return {"address": urlsplit(str(entry.get("url") or "")).hostname or "", "label": entry.get("label") or ""}


def use_machine(address: str, name: str = "") -> dict[str, Any]:
    """«Usa la sua scheda video» on the Macchine page: the local provider ``ollama`` points at a satellite's Ollama
    (``http://<address>:11434``); empty address = back to this machine's own (infrastructure env)."""
    import re
    from core.services import llm_providers, oracle_settings
    address = str(address or "").strip()
    if address and not re.fullmatch(r"[A-Za-z0-9.-]{1,120}", address):
        return {"ok": False, "detail": tr("Invalid address.")}
    current = oracle_settings.settings.get(oracle_settings.PROVIDERS_KEY)
    provs = {k: dict(v) for k, v in (current if isinstance(current, dict) and current
                                     else llm_providers.DEFAULT_PROVIDERS).items()}
    entry = provs.get("ollama") or {"type": "ollama", "label": tr("Ollama (local)"), "url": ""}
    entry["url"] = f"http://{address}:11434" if address else ""
    entry["label"] = f"Ollama ({name or address})" if address else tr("Ollama (local)")
    provs["ollama"] = entry
    if not oracle_settings.settings.put(oracle_settings.PROVIDERS_KEY, provs, actor="user",
                                        reason=tr("Machines: local models on {0}", name or address or tr("this machine"))):
        return {"ok": False, "detail": tr("The settings did not accept the choice.")}
    logger.info("event=llm_setup_machine address=%s", address or "local")
    return {"ok": True, "detail": tr("Local models now run on {0}.", name or address) if address
            else tr("Local models are back on this machine.")}


# ── Download dei modelli (Ollama) — hestia_common.downloads, page «Download» ──────────────

_downloads = None
_dlock = threading.Lock()


def downloads():
    """Oracle's download manager (source ``ollama``): jobs in ``data/downloads.json``, notices through Hermes."""
    global _downloads
    with _dlock:
        if _downloads is None:
            from hestia_common.downloads import Downloads
            from hestia_common.module_kit import Hub
            hub = Hub(os.getenv("HUB_API_URL", "http://hestia_hub:19001/api"))
            _downloads = Downloads("oracle", state_path=Path(os.getenv("ORACLE_DATA_DIR", "data")) / "downloads.json",
                                   hub=hub, page="cervello")
            _downloads.source("ollama", _run_pull, remove=_remove_model)
        return _downloads


def pulls() -> list[dict[str, Any]]:
    return [j for j in downloads().list() if j["source"] == "ollama"]


def pull(model: str) -> dict[str, Any]:
    """Queue (or report) the download of an Ollama model. Idempotent per model."""
    model = str(model or "").strip()
    if not model or len(model) > 120 or any(c.isspace() for c in model):
        return {"ok": False, "detail": tr("Invalid model name.")}
    from core.services import llm_providers
    have = llm_providers.list_models("ollama") if llm_providers.get("ollama") else []
    if model in have or f"{model}:latest" in have:
        # Already on the computer (also one made from a Modelfile, which is on no registry): nothing to download.
        return {"ok": True, "id": f"ollama:{model}", "state": "fatto", "already": True}
    size = next((int(m["size_gb"] * 1e9) for t in CATALOG for m in t["chat"] if m["model"] == model),
                int(EMBEDDING_MODEL["size_gb"] * 1e9) if model == EMBEDDING_MODEL["model"] else 0)
    return {"ok": True, **downloads().add(f"ollama:{model}", model, "ollama", {"model": model}, size_hint=size)}


def _run_pull(job) -> None:
    """``ollama pull`` with progress summed over its layers; Ollama resumes a broken pull by itself."""
    import requests
    from hestia_common.downloads import DownloadError
    from core.services import llm_providers
    model = job.params["model"]
    layers: dict[str, tuple[int, int]] = {}
    with requests.post(f"{llm_providers.url('ollama')}/api/pull", json={"model": model, "stream": True},
                       stream=True, timeout=(10, 600)) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                text = str(data["error"])
                if "not found" in text.lower() or "manifest" in text.lower():
                    raise DownloadError(tr("{0} is not in the Ollama library: if you created it (Modelfile) or it comes from elsewhere, load it into Ollama and choose that.", model), final=True)
                if "space" in text.lower():
                    raise DownloadError(tr("The disk is full: free some space or choose a smaller model."), final=True)
                raise RuntimeError(text)
            if data.get("total") and data.get("digest"):
                layers[data["digest"]] = (int(data.get("completed") or 0), int(data["total"]))
                job.progress(sum(c for c, _ in layers.values()), sum(t for _, t in layers.values()))
            else:
                job.check()
            if data.get("status") == "success":
                logger.info("event=llm_setup_pull_done model=%s", model)
                return
    raise RuntimeError("download interrotto")


def _remove_model(job) -> None:
    import requests
    from core.services import llm_providers
    requests.delete(f"{llm_providers.url('ollama')}/api/delete", json={"model": job.params["model"]},
                    timeout=30).raise_for_status()
    logger.info("event=llm_setup_model_removed model=%s", job.params["model"])
