"""Guided setup of the brain (docs/work/2026-10-30-setup-un-click §4.2 «Cervello»).

What the setup screen needs from Oracle, and only from Oracle (it owns the providers):
- ``CATALOG``: recommended local models per hardware tier (data, edit freely; any other Ollama name works too);
- ``recommend(vram_gb, ram_gb)``: the tier for this PC and its preselected models;
- ``test(provider, model)``: one tiny real call, answer in plain words;
- ``apply(recipe, local_model, cloud)``: writes ``oracle.chains`` (and the brain mode for the Claude subscription)
  from the user's choice, keeping the embedding chain as it is (changing it re-indexes the memory);
- ``pull`` / ``pulls``: Ollama downloads in the background with progress (``/api/pull`` stream), so the screen can
  show them while the user answers the next questions.
"""
from __future__ import annotations

import json
import logging
import threading
import time
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
LOCAL_TYPES = {"ollama", "llamacpp"}
CHAT_CHAINS = ("veloce", "potente", "codice", "visione")


def recommend(vram_gb: float = 0, ram_gb: float = 0) -> dict[str, Any]:
    """Tier for the detected hardware, its preselected chat model and the recipe to preselect."""
    vram = float(vram_gb or 0)
    tier = next(t for t in CATALOG if vram <= t["max_vram"])
    recipe = "entrambi" if vram >= 8 else ("cloud" if float(ram_gb or 0) and float(ram_gb) < 12 else "entrambi")
    return {"tier": tier["tier"], "label": tier["label"], "chat": tier["chat"], "model": tier["chat"][0]["model"],
            "embedding": EMBEDDING_MODEL, "recipe": recipe}


def catalog(vram_gb: float = 0, ram_gb: float = 0) -> dict[str, Any]:
    from core.services import llm_providers
    installed = llm_providers.list_models("ollama") if llm_providers.get("ollama") else []
    cloud = [{"name": p["name"], "label": p["label"], "type": p["type"], "key_env": p["key_env"],
              "key_set": p["key_set"], "available": p["available"]}
             for p in llm_providers.public_view() if p["type"] not in LOCAL_TYPES]
    return {"recommended": recommend(vram_gb, ram_gb), "tiers": CATALOG, "installed": installed,
            "ollama": bool(llm_providers.get("ollama")) and _ollama_up(), "cloud": cloud, "recipes": list(RECIPES)}


def _ollama_up() -> bool:
    import requests
    from core.services import llm_providers
    try:
        return requests.get(f"{llm_providers.url('ollama')}/api/version", timeout=3).ok
    except Exception:
        return False


# ── Prova ───────────────────────────────────────────────────────────────────

def test(provider: str, model: str = "") -> dict[str, Any]:
    """One tiny real call. Returns ``{ok, detail}`` with a reason a person understands."""
    from agents.universal_agent import UniversalAgent
    from core.services import llm_providers
    if not llm_providers.get(provider):
        return {"ok": False, "detail": "Questo servizio non è configurato."}
    ok, why = llm_providers.available(provider)
    if not ok:
        return {"ok": False, "detail": "Manca la chiave." if "not set" in why else why}
    model = model or _default_model(provider)
    if not model:
        return {"ok": False, "detail": "Nessun modello da provare."}
    started = time.monotonic()
    try:
        answer = UniversalAgent(role_prompt="", provider=provider, model_name=model, thinking=False,
                                label="oracle.setup").ask("Rispondi solo con la parola: ok")
    except Exception as exc:
        text = str(exc)
        logger.info("[🔄] event=llm_setup_test_failed provider=%s model=%s error=%s", provider, model, text[:200])
        low = text.lower()
        if any(w in low for w in ("401", "403", "api key", "invalid", "permission", "unauthorized")):
            return {"ok": False, "detail": "La chiave non è valida."}
        if any(w in low for w in ("429", "quota", "resource_exhausted")):
            return {"ok": True, "detail": "La chiave funziona, ma per oggi la quota è finita."}
        if "not found" in low or "404" in low:
            return {"ok": False, "detail": f"Il modello {model} non c'è: scaricalo o scegline un altro."}
        return {"ok": False, "detail": "Non risponde: " + text[:160]}
    ms = int((time.monotonic() - started) * 1000)
    logger.info("event=llm_setup_test_ok provider=%s model=%s ms=%s", provider, model, ms)
    return {"ok": bool(str(answer or "").strip()), "detail": f"Funziona ({model}, {ms / 1000:.1f} s).", "model": model}


def _default_model(provider: str) -> str:
    from core.services import llm_chains
    for chain in llm_chains.DEFAULT_CHAINS.values():
        for step in chain["steps"]:
            if step["provider"] == provider:
                return step["model"]
    from core.services import llm_providers
    models = llm_providers.list_models(provider)
    return models[0] if models else ""


# ── Applica la scelta ───────────────────────────────────────────────────────

def plan_chains(recipe: str, local_model: str, cloud: list[str], current: dict[str, dict]) -> dict[str, dict]:
    """New ``oracle.chains`` for a recipe. Pure function (tests): local steps use ``local_model``; cloud steps
    keep the default models of the chosen cloud providers; embedding and chains the setup does not know stay."""
    from core.services import llm_chains, llm_providers
    out = {name: dict(chain) for name, chain in current.items()}
    cloud = [c for c in cloud if c]
    for name in CHAT_CHAINS:
        default = llm_chains.DEFAULT_CHAINS.get(name, {"label": name.capitalize(), "steps": []})
        local_steps = [{"provider": "ollama", "model": local_model}] if local_model else []
        cloud_steps = [dict(s) for s in default["steps"]
                       if s["provider"] in cloud and llm_providers.type_of(s["provider"]) not in LOCAL_TYPES]
        for provider in cloud:   # a chosen provider the default chain does not list: its first default model
            if not any(s["provider"] == provider for s in cloud_steps):
                model = _default_model(provider)
                if model:
                    cloud_steps.append({"provider": provider, "model": model})
        if recipe == "locale":
            steps = local_steps
        elif recipe == "cloud":
            steps = cloud_steps
        else:   # entrambi, claude (the chains stay the fallback of the external brain)
            steps = local_steps + cloud_steps
        if steps:
            out[name] = {"label": out.get(name, default).get("label") or default["label"], "steps": steps}
    if "cloud" in out and cloud:
        steps = [dict(s) for s in llm_chains.DEFAULT_CHAINS["cloud"]["steps"] if s["provider"] in cloud]
        if steps:
            out["cloud"] = {"label": out["cloud"].get("label") or "Cloud", "steps": steps}
    return out


def summary(chains: dict[str, dict]) -> str:
    """One sentence: who answers first, and who if not («Ti risponde X sul tuo computer; se non c'è, Y.»)."""
    from core.services import llm_providers
    steps = (chains.get("veloce") or {}).get("steps") or []
    if not steps:
        return "Nessun modello scelto."

    def say(step: dict) -> str:
        where = "sul tuo computer" if llm_providers.type_of(step["provider"]) in LOCAL_TYPES else "nel cloud"
        return f"{step['model']} {where}"
    text = f"Ti risponde {say(steps[0])}"
    if len(steps) > 1:
        text += f"; se non c'è, {say(steps[1])}"
    return text + "."


def apply(recipe: str, local_model: str = "", cloud: list[str] | None = None) -> dict[str, Any]:
    from core.services import llm_chains, oracle_settings
    if recipe not in RECIPES:
        return {"ok": False, "detail": "Scelta non valida."}
    chains = plan_chains(recipe, local_model if recipe != "cloud" else "", list(cloud or []), llm_chains.chains())
    if not oracle_settings.settings.put(oracle_settings.CHAINS_KEY, chains, actor="user", reason="Setup guidato"):
        return {"ok": False, "detail": "Le impostazioni non hanno accettato la scelta."}
    if recipe == "claude":
        for key, value in ((oracle_settings.BRAIN_MODE, "esterna"), (oracle_settings.BRAIN_AGENT, "claude"),
                           (oracle_settings.BRAIN_FALLBACK, "interna")):
            oracle_settings.settings.put(key, value, actor="user", reason="Setup guidato")
    logger.info("event=llm_setup_applied recipe=%s local=%s cloud=%s", recipe, local_model or "-",
                ",".join(cloud or []) or "-")
    text = summary(chains)
    if recipe == "claude":
        text = "Ti risponde Claude con il tuo abbonamento; se non c'è, " + text[0].lower() + text[1:]
    return {"ok": True, "detail": text, "chains": chains}


# ── Download dei modelli (Ollama) ─────────────────────────────────────────────

_pulls: dict[str, dict[str, Any]] = {}
_plock = threading.Lock()


def pulls() -> list[dict[str, Any]]:
    with _plock:
        return [dict(p) for p in _pulls.values()]


def pull(model: str) -> dict[str, Any]:
    """Start (or report) the background download of an Ollama model. Idempotent per model."""
    model = str(model or "").strip()
    if not model or len(model) > 120 or any(c.isspace() for c in model):
        return {"ok": False, "detail": "Nome del modello non valido."}
    with _plock:
        job = _pulls.get(model)
        if job and job["state"] in ("in_coda", "in_corso"):
            return {"ok": True, **job}
        job = {"id": model, "what": model, "source": "ollama", "state": "in_coda", "size": 0, "done": 0,
               "error": "", "started_at": time.time()}
        _pulls[model] = job
    threading.Thread(target=_run_pull, args=(model,), daemon=True, name=f"pull-{model}").start()
    return {"ok": True, **job}


def _set(model: str, **kw) -> None:
    with _plock:
        if model in _pulls:
            _pulls[model].update(kw)


def _run_pull(model: str) -> None:
    import requests
    from core.services import llm_providers
    delay = 2
    for attempt in range(1, 4):
        _set(model, state="in_corso", error="")
        try:
            with requests.post(f"{llm_providers.url('ollama')}/api/pull", json={"model": model, "stream": True},
                               stream=True, timeout=(10, 600)) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise RuntimeError(data["error"])
                    if data.get("total"):
                        _set(model, size=int(data["total"]), done=int(data.get("completed") or 0))
                    if data.get("status") == "success":
                        _set(model, state="fatto", done=_pulls[model].get("size", 0))
                        logger.info("event=llm_setup_pull_done model=%s", model)
                        return
            raise RuntimeError("download interrotto")
        except Exception as exc:
            text = str(exc)
            logger.warning("[🔄] event=llm_setup_pull_failed model=%s attempt=%s error=%s", model, attempt, text[:200])
            if "not found" in text.lower() or "manifest" in text.lower():
                _set(model, state="errore", error=f"Il modello {model} non esiste su Ollama.")
                return
            if attempt == 3:
                _set(model, state="errore", error="Download non riuscito: " + text[:160])
                return
            time.sleep(delay)
            delay *= 2
