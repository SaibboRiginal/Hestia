"""Oracle settings declared to Themis (central settings).

Models per use case replace the old ``MODEL_USECASE_*`` env vars. Endpoints and keys
(``OLLAMA_URL``, ``GEMINI_API_KEY``…) are infrastructure and stay in env.
Model changes are live: ``AgentFactory.reconfigure`` updates the agents in place.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, preset, setting
except ModuleNotFoundError:  # local runs without PYTHONPATH
    _shared = Path(__file__).resolve().parents[4] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.settings_client import SettingsClient, preset, setting

# Provider types implemented in UniversalAgent (new types add a value here).
PROVIDERS = [("ollama", "Ollama (locale)"), ("gemini", "Gemini (cloud)")]
THINKING = [("auto", "Automatico"), ("true", "Sempre"), ("false", "Mai")]

USECASES = {
    #  use case    label                       provider  model                  fb provider fb model                  thinking
    "generic":   ("Uso generale",             "ollama", "gemma4:e4b",          "gemini", "gemini-2.0-flash-lite", "auto"),
    "reasoning": ("Ragionamento",             "ollama", "gemma4:e4b",          "gemini", "gemini-2.5-flash",      "true"),
    "code":      ("Codice",                   "ollama", "gemma4:e4b",          "gemini", "gemini-2.0-flash",      "auto"),
    "embedding": ("Embedding (ricerca)",      "ollama", "qwen3-embedding:0.6b", "gemini", "gemini-embedding-001", None),
}
_HELP = {
    "generic": "Chat, classificazione, scelta degli strumenti, memoria.",
    "reasoning": "Analisi lunghe e ragionamenti complessi (caricato quando serve).",
    "code": "Generazione e correzione di codice; usato anche da Forge (motore locale/cloud).",
    "embedding": "Vettori per memoria e documenti. Attenzione: cambiarlo rende diversi i vettori già salvati.",
}

settings = SettingsClient("oracle")


def key(usecase: str, field: str) -> str:
    return f"oracle.models.{usecase}.{field}"


def _definitions() -> list[dict]:
    defs: list[dict] = []
    for i, (uc, (label, prov, model, fb_prov, fb_model, thinking)) in enumerate(USECASES.items()):
        advanced = uc == "embedding"
        base = i * 10
        defs += [
            setting(key(uc, "provider"), f"{label} · fornitore", "enum", prov, group="Modelli", options=PROVIDERS,
                    help=_HELP[uc], order=base, advanced=advanced, row=label, column="Fornitore"),
            setting(key(uc, "model"), f"{label} · modello", "model", model, group="Modelli",
                    options_source=f"/api/llm/models?provider={{{key(uc, 'provider')}}}",
                    help="Nome del modello del fornitore scelto.", order=base + 1, advanced=advanced,
                    row=label, column="Modello"),
            setting(key(uc, "fallback_provider"), f"{label} · fornitore di riserva", "enum", fb_prov,
                    group="Modelli", options=PROVIDERS, order=base + 2, advanced=True,
                    help="Usato se il principale non risponde.", row=label, column="Riserva · fornitore"),
            setting(key(uc, "fallback_model"), f"{label} · modello di riserva", "model", fb_model, group="Modelli",
                    options_source=f"/api/llm/models?provider={{{key(uc, 'fallback_provider')}}}",
                    order=base + 3, advanced=True, row=label, column="Riserva · modello"),
        ]
        if thinking is not None:
            defs.append(setting(key(uc, "thinking"), f"{label} · ragionamento del modello", "enum", thinking,
                                group="Modelli", options=THINKING, order=base + 4, advanced=True,
                                help="Automatico = attivo se il modello lo supporta.", row=label,
                                column="Ragionamento"))
    return defs


def _presets() -> list[dict]:
    local = {key(uc, "provider"): "ollama" for uc in ("generic", "reasoning", "code")}
    local.update({key(uc, "model"): USECASES[uc][2] for uc in ("generic", "reasoning", "code")})
    cloud = {key("generic", "provider"): "gemini", key("generic", "model"): "gemini-2.5-flash",
             key("reasoning", "provider"): "gemini", key("reasoning", "model"): "gemini-2.5-pro",
             key("code", "provider"): "gemini", key("code", "model"): "gemini-2.5-flash"}
    balanced = {key("generic", "provider"): "ollama", key("generic", "model"): USECASES["generic"][2],
                key("reasoning", "provider"): "gemini", key("reasoning", "model"): "gemini-2.5-flash",
                key("code", "provider"): "gemini", key("code", "model"): "gemini-2.5-flash"}
    return [
        preset("economico", "Economico", group="Modelli", values=local,
               help="Tutto sui modelli locali (Ollama): gratis e privato, più lento sulle cose difficili."),
        preset("bilanciato", "Bilanciato", group="Modelli", values=balanced,
               help="Chat in locale, ragionamento e codice nel cloud (Gemini)."),
        preset("qualita", "Qualità", group="Modelli", values=cloud,
               help="Tutto nel cloud (Gemini): risposte migliori, serve la chiave API."),
    ]


settings.declare(_definitions(), presets=_presets()).declare_log_level()


def usecase(uc: str) -> dict[str, str]:
    """Current config of one use case: provider, model, thinking, fallback provider/model."""
    return {
        "prov": str(settings.get(key(uc, "provider")) or "ollama"),
        "mod": str(settings.get(key(uc, "model")) or "").strip(),
        "thinking_raw": str(settings.get(key(uc, "thinking"), "auto") or "auto").strip().lower(),
        "fb_prov": str(settings.get(key(uc, "fallback_provider")) or "gemini"),
        "fb_mod": str(settings.get(key(uc, "fallback_model")) or "").strip(),
    }
