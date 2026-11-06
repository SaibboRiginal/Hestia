"""Guided setup of the brain (docs/work/2026-10-30-setup-un-click §4.2 «Cervello»).

What the setup screen needs from Oracle, and only from Oracle (it owns the providers):
- ``runtimes(vram_gb)``: the programs that run models on this computer (Ollama, LM Studio, Jan, llama.cpp, vLLM),
  found by asking their usual port, each with the models it really has and a warning on those bigger than the video
  card. Hestia keeps no model list of its own for them: the program knows;
- ``CATALOG``: a few suggested models per hardware tier, shown only when nothing is installed (Ollama downloads them);
- ``recommend(vram_gb, ram_gb)``: the tier for this PC and its preselected models;
- ``test(provider, model)``: one tiny real call with a model the provider really lists, answer in plain words;
- ``apply(...)``: adds a found program as a provider block, writes ``oracle.chains`` from the user's choice (local
  program + model, cloud services in order with their models, embedding only when the user changed it: a new
  embedding model re-indexes the memory);
- ``pull`` / ``pulls``: Ollama downloads in the background with progress (``/api/pull`` stream), so the screen can
  show them while the user answers the next questions.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("hestia_oracle.llm_setup")

# Tier → models. Sizes are the download size in GB (what the user waits for), "good" is one short line.
CATALOG: list[dict[str, Any]] = [
    {"tier": "cpu", "label": "Senza scheda video", "max_vram": 5.9, "chat": [
        {"model": "gemma4:e4b", "size_gb": 3.3, "good": "Leggero, risponde bene alle cose di tutti i giorni."}]},
    {"tier": "8gb", "label": "Scheda video da 6–11 GB", "max_vram": 11.9, "chat": [
        {"model": "qwen3:8b", "size_gb": 5.2, "good": "Buon equilibrio tra velocità e ragionamento."},
        {"model": "gemma4:e4b", "size_gb": 3.3, "good": "Più leggero e veloce."}]},
    {"tier": "16gb", "label": "Scheda video da 12 GB o più", "max_vram": 999, "chat": [
        {"model": "qwen3:14b", "size_gb": 9.3, "good": "Ragiona meglio, ottimo per gli strumenti."},
        {"model": "qwen3:8b", "size_gb": 5.2, "good": "Più veloce, un po' meno preciso."}]},
]
EMBEDDING_MODEL = {"model": "qwen3-embedding:0.6b", "size_gb": 0.6, "good": "Serve alla memoria per ritrovare le cose."}
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
    try:
        resp = requests.get(f"{llm_providers.url('ollama')}/api/tags", timeout=5)
        resp.raise_for_status()
        rows = (resp.json() or {}).get("models", [])
    except Exception as exc:
        logger.warning("[🔄] event=llm_setup_local_models_failed error=%s", str(exc)[:160])
        return []
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
    low = f"{name} {family}".lower()
    return "embed" in low or "bert" in low or "bge-" in low


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


def runtimes(vram_gb: float = 0) -> list[dict[str, Any]]:
    """Every program for local models: Ollama first, then the OpenAI-compatible ones of ``RUNTIMES``. Each row:
    ``{name, label, url, site, found, configured, models: [{model, size_gb, params, quant, fits}], embed: [model]}``.
    A program already configured as a block (same address) keeps its block name."""
    from concurrent.futures import ThreadPoolExecutor
    from core.services import llm_providers
    ollama = {"name": "ollama", "label": "Ollama", "url": llm_providers.url("ollama") if llm_providers.get("ollama") else "",
              "site": OLLAMA_SITE, "configured": bool(llm_providers.get("ollama")), "found": False,
              "models": [], "embed": []}
    if ollama["configured"] and _ollama_up():
        ollama["found"] = True
        ollama["models"] = local_models(vram_gb)
        ollama["embed"] = [m for m in llm_providers.list_models("ollama") if _is_embedding(m)]
    host = _host()
    blocks = {llm_providers.url(n).rstrip("/"): n for n in llm_providers.providers()
              if llm_providers.type_of(n) == "openai"}
    bases = [f"http://{host}:{r['port']}/v1" for r in RUNTIMES]
    with ThreadPoolExecutor(max_workers=len(bases)) as pool:
        answers = list(pool.map(_probe_openai, bases))
    rows = [ollama]
    for spec, base, ids in zip(RUNTIMES, bases, answers):
        rows.append({"name": blocks.get(base, spec["name"]), "label": spec["label"], "url": base, "site": spec["site"],
                     "configured": base in blocks, "found": ids is not None,
                     # the program does not say the size: no warning rather than a wrong one
                     "models": [{"model": m, "size_gb": 0, "params": "", "quant": "", "fits": True}
                                for m in ids or [] if not _is_embedding(m)],
                     "embed": [m for m in ids or [] if _is_embedding(m)]})
    return rows


def ensure_runtime(name: str) -> bool:
    """A found program becomes a provider block (type ``openai``, its address) the first time the user picks it."""
    from core.services import llm_providers, oracle_settings
    if llm_providers.providers().get(name):
        return True
    spec = next((r for r in RUNTIMES if r["name"] == name), None)
    if spec is None:
        return False
    current = oracle_settings.settings.get(oracle_settings.PROVIDERS_KEY)
    provs = {k: dict(v) for k, v in (current if isinstance(current, dict) and current
                                     else llm_providers.DEFAULT_PROVIDERS).items()}
    provs[name] = {"type": "openai", "label": f"{spec['label']} (locale)", "url": f"http://{_host()}:{spec['port']}/v1"}
    ok = oracle_settings.settings.put(oracle_settings.PROVIDERS_KEY, provs, actor="user",
                                      reason=f"Setup guidato: {spec['label']} sul computer")
    logger.info("event=llm_setup_runtime_added provider=%s ok=%s", name, ok)
    return bool(ok)


def catalog(vram_gb: float = 0, ram_gb: float = 0) -> dict[str, Any]:
    from core.services import llm_chains, llm_providers
    installed = llm_providers.list_models("ollama") if llm_providers.get("ollama") else []
    cloud = [{"name": p["name"], "label": p["label"], "type": p["type"], "key_env": p["key_env"],
              "key_set": p["key_set"], "available": p["available"]}
             for p in llm_providers.public_view() if not llm_providers.is_local(p["name"])]
    found = runtimes(vram_gb)
    embedding = ((llm_chains.chains().get(llm_chains.EMBEDDING_CHAIN) or {}).get("steps") or [{}])[0]
    return {"recommended": recommend(vram_gb, ram_gb), "tiers": CATALOG, "installed": installed,
            "local": next((r["models"] for r in found if r["name"] == "ollama"), []), "runtimes": found,
            "embedding": {"provider": embedding.get("provider", ""), "model": embedding.get("model", "")},
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
    preferred = [m for m in chat if "flash" in m] if llm_providers.type_of(provider) == "gemini" else []
    return (preferred or chat or [wanted or default])[0]


def test(provider: str, model: str = "") -> dict[str, Any]:
    """One tiny real call. Returns ``{ok, detail, model, models}``: a reason a person understands, the model tried
    and the chat models the provider really has (for the model picker next to the key)."""
    from agents.universal_agent import UniversalAgent
    from core.services import llm_providers
    if not llm_providers.get(provider):
        return {"ok": False, "detail": "Questo servizio non è configurato."}
    ok, why = llm_providers.available(provider)
    if not ok:
        return {"ok": False, "detail": "Manca la chiave." if "not set" in why else why}
    listed = [] if llm_providers.type_of(provider) == "claude_cli" else llm_providers.list_models(provider)
    models = [m for m in listed if not _is_embedding(m)]
    model = _pick_model(provider, model, listed)
    if not model:
        return {"ok": False, "detail": "Nessun modello da provare.", "models": models}
    started = time.monotonic()
    try:
        answer = UniversalAgent(role_prompt="", provider=provider, model_name=model, thinking=False,
                                label="oracle.setup").ask("Rispondi solo con la parola: ok")
    except Exception as exc:
        text = str(exc)
        logger.info("[🔄] event=llm_setup_test_failed provider=%s model=%s error=%s", provider, model, text[:200])
        low = text.lower()
        if any(w in low for w in ("401", "403", "api key", "invalid", "permission", "unauthorized")):
            return {"ok": False, "detail": "La chiave non è valida.", "models": models}
        if any(w in low for w in ("429", "quota", "resource_exhausted")):
            return {"ok": True, "detail": "La chiave funziona, ma per oggi la quota è finita.", "model": model,
                    "models": models}
        if "not found" in low or "404" in low:
            # The key is fine (the list was read with it): another model, not a dead end.
            if models:
                return {"ok": True, "detail": f"La chiave funziona, ma {model} non risponde: scegli un altro modello.",
                        "model": "", "models": models}
            return {"ok": False, "detail": f"Il modello {model} non c'è: scegline un altro.", "models": models}
        return {"ok": False, "detail": "Non risponde: " + text[:160], "models": models}
    ms = int((time.monotonic() - started) * 1000)
    logger.info("event=llm_setup_test_ok provider=%s model=%s ms=%s", provider, model, ms)
    return {"ok": bool(str(answer or "").strip()), "detail": f"Funziona ({model}, {ms / 1000:.1f} s).", "model": model,
            "models": models}


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
                local_provider: str = "ollama", cloud_models: dict[str, str] | None = None,
                embedding: dict[str, str] | None = None) -> dict[str, dict]:
    """New ``oracle.chains`` for a recipe. Pure function (tests): local steps use ``local_provider``/``local_model``;
    each chosen cloud service uses the model picked for it (``cloud_models``), or its default models; the embedding
    chain changes only when ``embedding`` names another model; chains the setup does not know stay."""
    from core.services import llm_chains, llm_providers
    out = {name: dict(chain) for name, chain in current.items()}
    cloud = [c for c in cloud if c]
    picked = {k: v for k, v in (cloud_models or {}).items() if v}

    def cloud_steps_of(default_steps: list[dict]) -> list[dict]:
        steps: list[dict] = []
        for provider in cloud:
            if provider in picked:
                steps.append({"provider": provider, "model": picked[provider]})
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
        if steps:
            out[name] = {"label": out.get(name, default).get("label") or default["label"], "steps": steps}
    if "cloud" in out and cloud:
        steps = cloud_steps_of(llm_chains.DEFAULT_CHAINS["cloud"]["steps"])
        if steps:
            out["cloud"] = {"label": out["cloud"].get("label") or "Cloud", "steps": steps}
    emb = embedding or {}
    if emb.get("model"):
        step = {"provider": emb.get("provider") or "ollama", "model": emb["model"]}
        now = (out.get(llm_chains.EMBEDDING_CHAIN) or {}).get("steps") or []
        if now[:1] != [step]:
            out[llm_chains.EMBEDDING_CHAIN] = {"label": "Embedding", "steps": [step]}
    return out


def summary(chains: dict[str, dict]) -> str:
    """One sentence: who answers first, and who if not («Ti risponde X sul tuo computer; se non c'è, Y.»)."""
    from core.services import llm_providers
    steps = (chains.get("veloce") or {}).get("steps") or []
    if not steps:
        return "Nessun modello scelto."

    def say(step: dict) -> str:
        where = "sul tuo computer" if llm_providers.is_local(step["provider"]) else "nel cloud"
        return f"{step['model']} {where}"
    text = f"Ti risponde {say(steps[0])}"
    if len(steps) > 1:
        text += f"; se non c'è, {say(steps[1])}"
    return text + "."


def _live_models(cloud: list[str], picked: dict[str, str]) -> dict[str, str]:
    """For each chosen service without a picked model whose default models it no longer lists (a retired alias),
    a model it does list: the chains never start with a name that answers «not found»."""
    from core.services import llm_chains, llm_providers
    out: dict[str, str] = {}
    for provider in cloud:
        if picked.get(provider) or llm_providers.type_of(provider) == "claude_cli":
            continue
        listed = llm_providers.list_models(provider)
        defaults = {s["model"] for c in llm_chains.DEFAULT_CHAINS.values() for s in c["steps"] if s["provider"] == provider}
        if listed and defaults and not defaults <= set(listed):
            model = _pick_model(provider, "", listed)
            if model:
                out[provider] = model
                logger.info("[🔄] event=llm_setup_default_model_gone provider=%s using=%s", provider, model)
    return out


def apply(recipe: str, local_model: str = "", cloud: list[str] | None = None, local_provider: str = "ollama",
          cloud_models: dict[str, str] | None = None, embedding: dict[str, str] | None = None) -> dict[str, Any]:
    from core.services import llm_chains, oracle_settings
    if recipe not in RECIPES:
        return {"ok": False, "detail": "Scelta non valida."}
    local_provider = local_provider or "ollama"
    if recipe != "cloud" and local_model and not ensure_runtime(local_provider):
        return {"ok": False, "detail": "Non riesco ad aggiungere quel programma alle impostazioni."}
    if (embedding or {}).get("model") and not ensure_runtime((embedding or {}).get("provider") or "ollama"):
        return {"ok": False, "detail": "Non riesco ad aggiungere quel programma alle impostazioni."}
    cloud_models = {**_live_models(list(cloud or []), cloud_models or {}), **{k: v for k, v in (cloud_models or {}).items() if v}}
    chains = plan_chains(recipe, local_model if recipe != "cloud" else "", list(cloud or []), llm_chains.chains(),
                         local_provider=local_provider, cloud_models=cloud_models, embedding=embedding)
    if not oracle_settings.settings.put(oracle_settings.CHAINS_KEY, chains, actor="user", reason="Setup guidato"):
        return {"ok": False, "detail": "Le impostazioni non hanno accettato la scelta."}
    if recipe == "claude":
        for key, value in ((oracle_settings.BRAIN_MODE, "esterna"), (oracle_settings.BRAIN_AGENT, "claude"),
                           (oracle_settings.BRAIN_FALLBACK, "interna")):
            oracle_settings.settings.put(key, value, actor="user", reason="Setup guidato")
    logger.info("event=llm_setup_applied recipe=%s local=%s/%s cloud=%s", recipe, local_provider, local_model or "-",
                ",".join(cloud or []) or "-")
    text = summary(chains)
    if recipe == "claude":
        text = "Ti risponde Claude con il tuo abbonamento; se non c'è, " + text[0].lower() + text[1:]
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
        return {"ok": False, "detail": "Indirizzo non valido."}
    current = oracle_settings.settings.get(oracle_settings.PROVIDERS_KEY)
    provs = {k: dict(v) for k, v in (current if isinstance(current, dict) and current
                                     else llm_providers.DEFAULT_PROVIDERS).items()}
    entry = provs.get("ollama") or {"type": "ollama", "label": "Ollama (locale)", "url": ""}
    entry["url"] = f"http://{address}:11434" if address else ""
    entry["label"] = f"Ollama ({name or address})" if address else "Ollama (locale)"
    provs["ollama"] = entry
    if not oracle_settings.settings.put(oracle_settings.PROVIDERS_KEY, provs, actor="user",
                                        reason=f"Macchine: modelli locali su {name or address or 'questa macchina'}"):
        return {"ok": False, "detail": "Le impostazioni non hanno accettato la scelta."}
    logger.info("event=llm_setup_machine address=%s", address or "local")
    return {"ok": True, "detail": f"I modelli locali ora girano su {name or address}." if address
            else "I modelli locali tornano su questa macchina."}


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
        return {"ok": False, "detail": "Nome del modello non valido."}
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
                    raise DownloadError(f"Il modello {model} non esiste su Ollama.", final=True)
                if "space" in text.lower():
                    raise DownloadError("Il disco è pieno: libera spazio o scegli un modello più piccolo.", final=True)
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
