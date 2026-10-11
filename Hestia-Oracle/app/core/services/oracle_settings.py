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

# Provider types implemented in UniversalAgent (new types add a value here). Claude types
# (agents/providers) are offered only when their key / login is configured.
from agents.providers import available_types

PROVIDERS = [("ollama", "Ollama (locale)"), ("gemini", "Gemini (cloud)")] + available_types()
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


TONES = [("warm", "Caldo"), ("neutral", "Neutro"), ("direct", "Diretto"), ("formal", "Formale")]
_TONE_SENTENCE = {"warm": "Tono: caldo e amichevole.", "neutral": "",
                  "direct": "Tono: diretto, essenziale, niente preamboli.", "formal": "Tono: formale."}
TONE, INSTRUCTIONS = "oracle.chat.tone", "oracle.chat.instructions"

# Personal chat settings (scope user): same values on every client; profile = default for new sessions,
# a client or a single conversation can override (session → client → profile → default).
_CHAT = [
    setting(TONE, "Tono delle risposte", "enum", "warm", group="Chat", scope="user", options=TONES, order=0,
            help="Come ti risponde Hestia, su ogni client."),
    setting(INSTRUCTIONS, "Istruzioni personali", "text", "", group="Chat", scope="user", order=1,
            help="Aggiunte a ogni conversazione (es. «rispondi sempre in breve»)."),
]

# Context & local runtimes (dossier docs/work/2026-10-10-oracle-local-context). Endpoints stay in env.
NUM_CTX = "oracle.provider.ollama.num_ctx"
KEEP_ALIVE = "oracle.provider.ollama.keep_alive"
COMPACT_THRESHOLD = "oracle.context.compact_threshold"
STUB_AFTER_TURNS = "oracle.context.tool_result_stub_after_turns"
OPENAI_CACHE_PROMPT = "oracle.provider.openai.cache_prompt"
_KEEP_ALIVE = [("5m", "5 minuti"), ("30m", "30 minuti"), ("2h", "2 ore"), ("always", "Sempre")]

_CONTEXT = [
    setting(NUM_CTX, "Ollama · finestra di contesto", "int", 8192, group="Contesto", min=2048, max=262144,
            unit="token", order=0,
            help="Token che il modello locale tiene in memoria per ogni richiesta. Più alto = ricorda di più "
                 "ma usa più VRAM; cambiarlo ricarica il modello."),
    setting(KEEP_ALIVE, "Ollama · modello in memoria", "enum", "30m", group="Contesto", options=_KEEP_ALIVE,
            order=1, help="Quanto resta caricato il modello dopo l'ultima richiesta: evita la partenza a freddo."),
    setting(COMPACT_THRESHOLD, "Compatta il contesto oltre", "float", 0.8, group="Contesto", min=0.3, max=0.95,
            order=2, advanced=True, help="Frazione della finestra oltre la quale la conversazione viene riassunta."),
    setting(STUB_AFTER_TURNS, "Accorcia i risultati degli strumenti dopo", "int", 2, group="Contesto", min=0,
            max=20, unit="passi", order=3, advanced=True,
            help="Nei ragionamenti lunghi i risultati più vecchi di N passi diventano una riga di riepilogo "
                 "quando il contesto si riempie. 0 = mai."),
    setting(OPENAI_CACHE_PROMPT, "Server compatibile OpenAI · riusa la cache del prompt", "bool", True,
            group="Contesto", order=4, advanced=True,
            help="Chiede a llama-server di riusare il prefisso già calcolato (cache_prompt). "
                 "Disattivalo se il server rifiuta il campo."),
]

settings.declare(_definitions() + _CHAT + _CONTEXT, presets=_presets()).declare_log_level()


def context_window() -> int:
    """Real context window (tokens) sent to Ollama and used for budgeting/compaction."""
    try:
        return max(512, int(settings.get(NUM_CTX) or 8192))
    except (TypeError, ValueError):
        return 8192


def compact_threshold() -> float:
    try:
        return float(settings.get(COMPACT_THRESHOLD) or 0.8)
    except (TypeError, ValueError):
        return 0.8


def stub_after_turns() -> int:
    try:
        return max(0, int(settings.get(STUB_AFTER_TURNS) or 0))
    except (TypeError, ValueError):
        return 0


def ollama_request_options() -> dict:
    """Fields added to every Ollama request: same ``num_ctx`` on every call (a different
    value makes Ollama reload the model) and ``keep_alive`` (avoid cold starts)."""
    keep = str(settings.get(KEEP_ALIVE) or "30m")
    return {"options": {"num_ctx": context_window()}, "keep_alive": -1 if keep == "always" else keep}


def provider_settings(provider_type: str) -> dict:
    """Tunables of one provider type (merged into its infrastructure config)."""
    if provider_type == "openai":
        return {"cache_prompt": bool(settings.get(OPENAI_CACHE_PROMPT, True))}
    return {}


def chat_instructions(*, client: str = "", session: str = "") -> list[str]:
    """Answer-shaping personal settings of this conversation, as short sentences for the prompt."""
    values = settings.user_values(client=client, session=session)
    out = []
    tone = _TONE_SENTENCE.get(str(values.get(TONE) or ""), "")
    if tone:
        out.append(tone)
    custom = str(values.get(INSTRUCTIONS) or "").strip()
    if custom:
        out.append(f"Istruzioni dell'utente: {custom}")
    return out


def usecase(uc: str) -> dict[str, str]:
    """Current config of one use case: provider, model, thinking, fallback provider/model."""
    return {
        "prov": str(settings.get(key(uc, "provider")) or "ollama"),
        "mod": str(settings.get(key(uc, "model")) or "").strip(),
        "thinking_raw": str(settings.get(key(uc, "thinking"), "auto") or "auto").strip().lower(),
        "fb_prov": str(settings.get(key(uc, "fallback_provider")) or "gemini"),
        "fb_mod": str(settings.get(key(uc, "fallback_model")) or "").strip(),
    }
