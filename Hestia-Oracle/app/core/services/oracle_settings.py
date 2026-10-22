"""Oracle settings declared to Themis (central settings).

Models are three object settings (providers, chains, use cases — ``llm_providers`` / ``llm_chains``):
modules send ``use_case`` and declare theirs in the Hub registration. Provider keys
(``ORACLE_KEY_<NAME>``), binaries/paths, ``OLLAMA_URL``, ``ORACLE_EMBED_DIM`` (Archive ``Vector(768)``) and
``TZ`` are secrets/infrastructure and stay in env. Every tunable is read at use time (``apply="live"``).
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

# ── Models: providers · chains · use cases (dossier docs/work/2026-10-19-oracle-a-blocchi) ─────────
# Three object settings edited by the WebUI page Modelli (Oracle → Cervello): named providers (keys stay in env
# ORACLE_KEY_<NAME>), reusable chains of provider/model steps, use case → chain/mode overrides.
PROVIDERS_KEY = "oracle.providers"
CHAINS_KEY = "oracle.chains"
USECASES_KEY = "oracle.usecases"
CHAIN_COOLDOWN = "oracle.quota.cooldown_minutes"
USAGE_RETENTION = "oracle.usage.retention_days"
PRICING_KEY = "oracle.pricing"
BRAIN_MODE = "oracle.brain.mode"
BRAIN_AGENT = "oracle.brain.agent"
BRAIN_MODEL = "oracle.brain.model"
BRAIN_FALLBACK = "oracle.brain.fallback"
BRAIN_MODES = [("interna", "Interna"), ("esterna", "Esterna")]
BRAIN_AGENTS = [("claude", "Claude Code (abbonamento)"), ("codex", "Codex (ChatGPT)")]
BRAIN_FALLBACKS = [("interna", "Rifai il turno in modalità interna"), ("nessuno", "Nessuno: dimmi che non ha risposto")]

settings = SettingsClient("oracle")


def _definitions() -> list[dict]:
    from core.services.llm_chains import DEFAULT_CHAINS
    from core.services.llm_providers import DEFAULT_PROVIDERS
    return [
        setting(PROVIDERS_KEY, "Fornitori", "object", DEFAULT_PROVIDERS, group="Modelli", order=0,
                editor="llm_providers",
                help="Dove stanno i modelli: nome, standard (Ollama, compatibile OpenAI, compatibile Anthropic, "
                     "Gemini, Claude abbonamento) e indirizzo. La chiave sta solo nel file .env come "
                     "ORACLE_KEY_<NOME>."),
        setting(CHAINS_KEY, "Catene di modelli", "object", DEFAULT_CHAINS, group="Modelli", order=1,
                editor="llm_chains",
                help="Liste ordinate fornitore/modello, come font-family: se un modello finisce la quota passo "
                     "al successivo e lo salto finché la quota non si ricarica."),
        setting(USECASES_KEY, "Usi dei moduli", "object", {}, group="Modelli", order=2, editor="llm_usecases",
                help="Per ogni uso dichiarato da un modulo: catena, modalità e ragionamento. Vuoto = la scelta "
                     "suggerita dal modulo."),
        setting(CHAIN_COOLDOWN, "Pausa di un modello senza quota", "int", 60, group="Modelli", order=3,
                min=1, max=1440, unit="min", advanced=True,
                help="Quando il fornitore non dice quando si ricarica la quota (Gemini giornaliero: mezzanotte "
                     "del Pacifico)."),
        setting(BRAIN_MODE, "Modalità del cervello", "enum", "interna", group="Modelli", order=4, options=BRAIN_MODES,
                help="Interna: Oracle ragiona con le catene di modelli (classificatore, Rapida/Pensata/CoT, ciclo "
                     "agente). Esterna: un agente (Claude Code, Codex) fa il ciclo con gli strumenti di Hestia; "
                     "Oracle prepara il contesto, salva i messaggi e la memoria. Ogni uso può scegliere la sua."),
        setting(BRAIN_AGENT, "Agente esterno", "enum", "claude", group="Modelli", order=5, options=BRAIN_AGENTS,
                help="Serve il suo login: Claude Code con CLAUDE_CODE_OAUTH_TOKEN, Codex con `codex login` "
                     "(immagine con ORACLE_INSTALL_CODEX=1)."),
        setting(BRAIN_MODEL, "Modello dell'agente esterno", "string", "sonnet", group="Modelli", order=6,
                help="Es. sonnet, opus (Claude Code) o gpt-5-codex (Codex). Vuoto = quello predefinito dell'agente."),
        setting(BRAIN_FALLBACK, "Se l'agente esterno non risponde", "enum", "interna", group="Modelli", order=7,
                options=BRAIN_FALLBACKS),
        setting(USAGE_RETENTION, "Conserva l'uso dei modelli per", "int", 90, group="Uso", order=0, min=1,
                max=3650, unit="giorni", help="Ogni chiamata a un modello resta nel pannello Uso per questi giorni."),
        setting(PRICING_KEY, "Prezzi dei modelli", "object", {}, group="Uso", order=1,
                help="Dollari per milione di token, per «fornitore/modello» (o solo il modello): "
                     "{\"gemini/gemini-2.5-flash\": {\"in\": 0.3, \"out\": 2.5, \"cached\": 0.075}}. "
                     "Serve solo dove il fornitore non dice il costo; i modelli locali costano 0."),
    ]


TONES = [("warm", "Caldo"), ("neutral", "Neutro"), ("direct", "Diretto"), ("formal", "Formale")]
_TONE_SENTENCE = {"warm": "Tono: caldo e amichevole.", "neutral": "",
                  "direct": "Tono: diretto, essenziale, niente preamboli.", "formal": "Tono: formale."}
TONE, INSTRUCTIONS = "oracle.chat.tone", "oracle.chat.instructions"
MODE = "oracle.chat.mode"
# Conversation modes (process, not brain): quick = one call no tools · auto = classifier decides ·
# thinking = always agent loop + model reasoning · cot = deep reasoning, more turns, step-by-step plan.
MODES = [("auto", "Auto"), ("quick", "Rapida"), ("thinking", "Pensata"), ("cot", "CoT · passo passo")]
_MODE_ALIASES = {"fast": "quick", "rapida": "quick", "pensata": "thinking", "deep": "cot"}

# Personal chat settings (scope user): same values on every client; profile = default for new sessions,
# a client or a single conversation can override (session → client → profile → default).
_CHAT = [
    setting(TONE, "Tono delle risposte", "enum", "warm", group="Chat", scope="user", options=TONES, order=0,
            help="Come ti risponde Hestia, su ogni client."),
    setting(INSTRUCTIONS, "Istruzioni personali", "text", "", group="Chat", scope="user", order=1,
            help="Aggiunte a ogni conversazione (es. «rispondi sempre in breve»)."),
    setting(MODE, "Modalità di conversazione", "enum", "auto", group="Chat", scope="user", options=MODES, order=2,
            help="Rapida: una risposta senza strumenti. Auto: decide Hestia. Pensata: ragiona e usa gli "
                 "strumenti. CoT: ragionamento profondo passo passo (più lento)."),
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

# ── Runtime tunables (were ORACLE_* / OLLAMA_* / DOC_* env vars) ─────────────────────────────
# Agent loop
MAX_TURNS = "oracle.agent.max_turns"
ASK_TIMEOUT = "oracle.ask.timeout"
MAX_TOKENS = "oracle.agent.max_tokens"
TOOL_RESULT_MAX_CHARS = "oracle.agent.tool_result_max_chars"
EARLY_EXIT_NO_TOOL_TURNS = "oracle.agent.early_exit_no_tool_turns"
MAX_PARALLEL_TOOLS = "oracle.agent.max_parallel_tools"
# Conversation context
HISTORY_LIMIT = "oracle.context.history_messages"
HISTORY_CHAR_LIMIT = "oracle.context.history_message_chars"
ENTITIES_LIMIT = "oracle.context.entities"
FIELD_CHAR_LIMIT = "oracle.context.entity_field_chars"
COMPACT_TRIGGER = "oracle.context.compact_trigger_messages"
COMPACT_KEEP = "oracle.context.compact_keep_recent"
TODAY_AGENDA = "oracle.context.today_agenda"
# Time limits per request source (s)
TIMEOUTS = {
    "foreground_chat": ("Risposta in chat", 8),
    "action_selection": ("Scelta dell'azione", 12),
    "action_service_route": ("Azione su un modulo", 25),
    "memory_extraction": ("Estrazione della memoria", 10),
    "background_compaction": ("Compattazione in background", 8),
    "notification_formatting": ("Testo delle notifiche", 12),
}
GATEWAY_CHAT_TIMEOUT = "oracle.timeouts.gateway_chat"
# Providers (endpoints stay env)
LLM_RETRIES = "oracle.provider.retries"
LLM_RETRY_DELAY = "oracle.provider.retry_delay"
OLLAMA_TIMEOUT = "oracle.provider.ollama.timeout"
OLLAMA_EMBED_TIMEOUT = "oracle.provider.ollama.embed_timeout"
OLLAMA_TOOL_MODE = "oracle.provider.ollama.tool_call_mode"
THINKING_FAMILIES = "oracle.provider.ollama.thinking_families"
# Memory
NOTICE_WAIT = "oracle.memory.notice_wait"
DOMAIN_THRESHOLD = "oracle.memory.domain_threshold"
PREFERENCE_DOMAINS = "oracle.memory.preference_domains"
FORCE_OWNER_TARGET = "oracle.memory.force_owner_target"
# High-impact approval gate (safety: the assistant may only read these)
APPROVAL_ENABLED = "oracle.approval.enabled"
APPROVAL_TTL = "oracle.approval.ttl"
APPROVAL_BULK_MIN = "oracle.approval.bulk_min_count"
APPROVAL_METHODS = "oracle.approval.methods"
APPROVAL_COMMANDS = "oracle.approval.commands"
# Athena hints, caches, background tasks
HINTS_ENABLED = "oracle.hints.enabled"
HINTS_TTL = "oracle.hints.ttl"
HINTS_MAX = "oracle.hints.max"
SCHEMAS_CACHE_TTL = "oracle.cache.schemas_ttl"
TOOL_REGISTRY_TTL = "oracle.cache.tool_registry_ttl"
TASKS_MAX = "oracle.tasks.max_kept"
# Documents
DOC_MAX_ARCHIVE_MB = "oracle.documents.max_archive_mb"
DOC_SEARCH_THRESHOLD = "oracle.documents.search_threshold"
VISION_MODELS = "oracle.documents.vision_models"
AUDIO_MODELS = "oracle.documents.audio_models"
# Prompt A/B experiments: surface → key prefix
AB_SURFACES = {"alert_formatter": ("oracle.prompt_ab.alert", "Notifiche"),
               "planner_behavior": ("oracle.prompt_ab.planner", "Pianificatore")}

DEFAULT_PREFERENCE_DOMAINS = {
    "general": "Universal preferences, default catch-all for anything not fitting other domains",
    "calendar": "Scheduling, time management, appointments, events, deadlines, agenda, reminders",
    "real_estate": "Housing, property, apartments, listings, buying, selling, renting homes, real estate market",
    "email": "Messages, communication, inbox, correspondence, mail, letters, notifications",
    "system": "Technology, services, monitoring, software, hardware, tech infrastructure, servers",
    "food": "Cuisine, restaurants, dietary preferences, cooking, eating, food, meals, recipes",
    "work": "Professional life, projects, career, workplace, business, job, office, employment",
    "health": "Medical, fitness, wellness, exercise, healthcare, doctor, gym, nutrition",
    "travel": "Trips, transportation, locations, navigation, commuting, vacations, flights, hotels",
    "finance": "Money, budgeting, purchases, banking, investments, savings, expenses, payments",
}
_DEFAULT_THINKING_FAMILIES = ["gemma4", "gemma3", "gemma", "qwen3", "deepseek-r1", "llama4", "phi4", "llama",
                              "llama2", "llama3"]
_DEFAULT_VISION = ["gemma-3", "gemma4", "gemma3", "gemini", "gpt-4o", "gpt-4-vision", "claude-3", "llava", "bakllava",
                   "moondream", "minicpm-v", "phi-3-vision", "phi3v", "qwen2-vl", "qwen-vl", "internvl"]
_TOOL_MODES = [("auto", "Automatico"), ("native", "Nativo"), ("text", "Testo")]

_AGENT = [
    setting(MAX_TURNS, "Passi massimi per risposta", "int", 25, group="Agente", min=1, max=100, unit="passi",
            order=0, help="Quante volte al massimo l'assistente usa gli strumenti prima di risponderti "
                          "(la modalità CoT ne usa almeno 50)."),
    setting(ASK_TIMEOUT, "Una domanda per te resta aperta per", "int", 24, group="Agente", min=1, max=720,
            unit="ore", order=3, help="Quando l'assistente ti chiede qualcosa (scelta, conferma, testo libero), "
                                      "dopo questo tempo senza risposta la domanda si chiude."),
    setting(MAX_TOKENS, "Token massimi per risposta", "int", 0, group="Agente", min=0, max=2_000_000,
            unit="token", order=1, advanced=True, help="Limite di token consumati in un ragionamento. 0 = nessun limite."),
    setting(TOOL_RESULT_MAX_CHARS, "Lunghezza massima del risultato di uno strumento", "int", 2000,
            group="Agente", min=200, max=50000, unit="caratteri", order=2, advanced=True,
            help="Oltre questa lunghezza il risultato viene accorciato prima di darlo al modello."),
    setting(EARLY_EXIT_NO_TOOL_TURNS, "Chiudi dopo passi senza strumenti", "int", 2, group="Agente", min=1,
            max=10, unit="passi", order=3, advanced=True,
            help="Se il modello non usa strumenti per questi passi di fila (e ha già fatto qualcosa), risponde."),
    setting(MAX_PARALLEL_TOOLS, "Strumenti in parallelo", "int", 8, group="Agente", min=1, max=32, order=4,
            advanced=True, help="Quanti strumenti possono girare insieme nello stesso passo."),
    setting(HISTORY_LIMIT, "Messaggi precedenti nel contesto", "int", 6, group="Contesto", min=1, max=100,
            unit="messaggi", order=10, help="Quanti messaggi della conversazione l'assistente rilegge a ogni risposta."),
    setting(HISTORY_CHAR_LIMIT, "Lunghezza massima di un messaggio precedente", "int", 500, group="Contesto",
            min=50, max=20000, unit="caratteri", order=11, advanced=True,
            help="I messaggi vecchi più lunghi vengono accorciati nel contesto."),
    setting(ENTITIES_LIMIT, "Elementi dei moduli nel contesto", "int", 12, group="Contesto", min=1, max=100,
            order=12, advanced=True, help="Quanti elementi trovati nei moduli (annunci, eventi…) entrano nell'analisi."),
    setting(FIELD_CHAR_LIMIT, "Lunghezza massima di un campo", "int", 280, group="Contesto", min=50, max=5000,
            unit="caratteri", order=13, advanced=True, help="Ogni campo di un elemento viene accorciato a questa lunghezza."),
    setting(COMPACT_TRIGGER, "Riassumi la conversazione oltre", "int", 20, group="Contesto", min=6, max=500,
            unit="messaggi", order=14, advanced=True,
            help="Oltre questo numero di messaggi la parte vecchia della conversazione viene riassunta."),
    setting(COMPACT_KEEP, "Messaggi recenti da non riassumere", "int", 6, group="Contesto", min=2, max=50,
            unit="messaggi", order=15, advanced=True, help="Gli ultimi messaggi restano interi quando si riassume."),
    setting(TODAY_AGENDA, "Agenda di oggi nel contesto", "bool", True, group="Contesto", order=16,
            help="A ogni risposta l'assistente legge gli impegni di oggi dal calendario (qualche token in più)."),
]
_TIMEOUTS = [
    setting(f"oracle.timeouts.{name}", f"Tempo massimo · {label.lower()}", "int", default, group="Tempi",
            min=1, max=600, unit="s", order=i, advanced=True,
            help="Oltre questo tempo il passaggio viene saltato o si passa al piano di riserva.")
    for i, (name, (label, default)) in enumerate(TIMEOUTS.items())
] + [
    setting(GATEWAY_CHAT_TIMEOUT, "Tempo massimo · richieste di Forge al modello", "int", 600, group="Tempi",
            min=30, max=3600, unit="s", order=20, advanced=True,
            help="Una richiesta di Forge al modello (uso forge.codice) che supera questo tempo fallisce."),
    setting(OLLAMA_TIMEOUT, "Tempo massimo · risposta di Ollama", "int", 120, group="Tempi", min=10, max=1800,
            unit="s", order=21, help="Quanto aspetto una risposta del modello locale."),
    setting(OLLAMA_EMBED_TIMEOUT, "Tempo massimo · embedding di Ollama", "int", 60, group="Tempi", min=5,
            max=600, unit="s", order=22, advanced=True),
    setting(LLM_RETRIES, "Tentativi verso il modello", "int", 3, group="Tempi", min=1, max=10, order=23,
            advanced=True, help="Quante volte riprovo una chiamata al modello che fallisce."),
    setting(LLM_RETRY_DELAY, "Attesa tra i tentativi", "float", 1.0, group="Tempi", min=0.1, max=60, unit="s",
            order=24, advanced=True, help="Prima attesa; raddoppia a ogni nuovo tentativo."),
]
_PROVIDER = [
    setting(OLLAMA_TOOL_MODE, "Ollama · modo di chiamare gli strumenti", "enum", "auto", group="Contesto",
            options=_TOOL_MODES, order=5, advanced=True,
            help="Nativo: usa le chiamate strumenti di Ollama. Testo: il modello le scrive nel testo. "
                 "Automatico: nativo, testo se il modello non lo supporta."),
    setting(THINKING_FAMILIES, "Ollama · famiglie di modelli che ragionano", "list", _DEFAULT_THINKING_FAMILIES,
            group="Contesto", order=6, advanced=True,
            help="Con ragionamento «Automatico», un modello di queste famiglie ragiona prima di rispondere."),
]
_MEMORY = [
    setting(NOTICE_WAIT, "Attesa per gli avvisi di memoria", "float", 8.0, group="Memoria", min=0, max=60,
            unit="s", order=0, advanced=True,
            help="Dopo la risposta aspetto al massimo questo tempo per dirti cosa ho memorizzato."),
    setting(DOMAIN_THRESHOLD, "Somiglianza per assegnare un'area", "float", 0.55, group="Memoria", min=0.1,
            max=0.99, order=1, advanced=True,
            help="Una preferenza va in un'area (cibo, lavoro…) se le somiglia almeno così. Più alto = più severo."),
    setting(PREFERENCE_DOMAINS, "Aree delle preferenze", "object", DEFAULT_PREFERENCE_DOMAINS, group="Memoria",
            order=2, advanced=True,
            help="Nome dell'area → descrizione (in inglese) usata per riconoscerla. «general» c'è sempre."),
    setting(FORCE_OWNER_TARGET, "Avvisi delle sottoscrizioni sempre a te", "bool", True, group="Memoria",
            order=3, advanced=True,
            help="Gli avvisi che chiedi in chat («avvisami quando…») arrivano sempre a te, "
                 "ignorando altre destinazioni proposte dal modello."),
]
_APPROVAL = [
    setting(APPROVAL_ENABLED, "Chiedi conferma per le azioni importanti", "bool", True, group="Conferme",
            oracle="read", order=0,
            help="Prima di cancellare, modificare o fare azioni su più elementi l'assistente ti chiede conferma."),
    setting(APPROVAL_TTL, "Validità di una richiesta di conferma", "int", 600, group="Conferme", min=30,
            max=86400, unit="s", oracle="read", order=1, advanced=True,
            depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="Dopo questo tempo una richiesta di conferma senza risposta scade."),
    setting(APPROVAL_BULK_MIN, "Conferma se l'azione tocca almeno", "int", 2, group="Conferme", min=1, max=100,
            unit="elementi", oracle="read", order=2, advanced=True,
            depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="Un'azione ripetuta su almeno questi elementi chiede conferma."),
    setting(APPROVAL_METHODS, "Tipi di richiesta da confermare", "list", ["DELETE", "PUT", "PATCH"],
            group="Conferme", oracle="read", order=3, advanced=True,
            depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="Metodi HTTP che chiedono sempre conferma (DELETE = cancella, PUT/PATCH = modifica)."),
    setting(APPROVAL_COMMANDS, "Comandi da confermare sempre", "list", [], group="Conferme", oracle="read",
            order=4, advanced=True, depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="Nomi di comandi che chiedono sempre conferma, qualunque sia il tipo."),
]
_RUNTIME = [
    setting(HINTS_ENABLED, "Usa i suggerimenti di Athena", "bool", True, group="Memoria", order=9,
            help="Le osservazioni di Athena (cosa ti interessa ora) guidano le risposte. Spento = ignorate."),
    setting(HINTS_TTL, "Durata dei suggerimenti di Athena", "int", 7200, group="Memoria", min=60, max=604800,
            unit="s", order=10, advanced=True, help="Per quanto tempo un suggerimento di Athena resta valido."),
    setting(HINTS_MAX, "Suggerimenti di Athena tenuti", "int", 300, group="Memoria", min=10, max=5000,
            order=11, advanced=True),
    setting(SCHEMAS_CACHE_TTL, "Cache degli schemi dei moduli", "int", 30, group="Diagnostica", min=0,
            max=3600, unit="s", order=10, advanced=True),
    setting(TOOL_REGISTRY_TTL, "Cache degli strumenti dei moduli", "int", 120, group="Diagnostica", min=0,
            max=3600, unit="s", order=11, advanced=True,
            help="Ogni quanto rileggo dai moduli l'elenco degli strumenti disponibili."),
    setting(TASKS_MAX, "Attività in background ricordate", "int", 500, group="Diagnostica", min=50, max=10000,
            order=12, advanced=True),
]
_DOCUMENTS = [
    setting(DOC_MAX_ARCHIVE_MB, "Dimensione massima per archiviare un file", "int", 10, group="Documenti",
            min=1, max=500, unit="MB", order=0,
            help="I file più grandi vengono analizzati ma non salvati nell'archivio dei documenti."),
    setting(DOC_SEARCH_THRESHOLD, "Distanza massima nella ricerca documenti", "float", 1.2, group="Documenti",
            min=0.1, max=2.0, order=1, advanced=True,
            help="Più basso = solo documenti molto pertinenti; più alto = più risultati."),
    setting(VISION_MODELS, "Modelli che leggono immagini", "list", _DEFAULT_VISION, group="Documenti",
            order=3, advanced=True, help="Inizio del nome dei modelli che possono guardare immagini e PDF."),
    setting(AUDIO_MODELS, "Modelli che ascoltano l'audio", "list", ["gemini-1.5", "gemini-2"], group="Documenti",
            order=4, advanced=True, help="Inizio del nome dei modelli che capiscono l'audio senza trascrizione."),
]
_AB = []
for _i, (_surface, (_prefix, _label)) in enumerate(AB_SURFACES.items()):
    _AB += [
        setting(f"{_prefix}.enabled", f"Esperimento prompt · {_label}", "bool", False, group="Esperimenti",
                order=_i * 10, advanced=True,
                help="Divide le richieste tra le varianti del prompt per confrontarle."),
        setting(f"{_prefix}.variants", f"Esperimento prompt · {_label} · varianti", "list",
                ["control", "experimental"], group="Esperimenti", order=_i * 10 + 1, advanced=True),
        setting(f"{_prefix}.default", f"Esperimento prompt · {_label} · variante normale", "string", "control",
                group="Esperimenti", order=_i * 10 + 2, advanced=True,
                help="Usata quando l'esperimento è spento."),
        setting(f"{_prefix}.force", f"Esperimento prompt · {_label} · forza variante", "string", "",
                group="Esperimenti", order=_i * 10 + 3, advanced=True,
                help="Se indicata, usata sempre (anche a esperimento spento)."),
    ]

def _advanced_except_models(defs: list[dict]) -> list[dict]:
    """Only Modelli (and the personal Chat settings) stay in view; Oracle's other tunables go under *avanzate*."""
    for d in defs:
        if d.get("group") not in ("Modelli", "Chat"):
            d["advanced"] = True
    return defs


settings.declare(_advanced_except_models(_definitions() + _CHAT + _CONTEXT + _AGENT + _TIMEOUTS + _PROVIDER
                                         + _MEMORY + _APPROVAL + _RUNTIME + _DOCUMENTS + _AB)).declare_log_level()


# ── Typed readers (live; a bad stored value falls back to the declared default) ──────────────
def _default(key_: str):
    return (settings._defs.get(key_) or {}).get("default")


def get_int(key_: str, minimum: int | None = None) -> int:
    try:
        value = int(settings.get(key_))
    except (TypeError, ValueError):
        value = int(_default(key_))
    return value if minimum is None else max(minimum, value)


def get_float(key_: str, minimum: float | None = None) -> float:
    try:
        value = float(settings.get(key_))
    except (TypeError, ValueError):
        value = float(_default(key_))
    return value if minimum is None else max(minimum, value)


def get_bool(key_: str) -> bool:
    value = settings.get(key_)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "si", "sì"}
    return bool(value)


def get_list(key_: str, *, lower: bool = False, upper: bool = False) -> list[str]:
    """List setting as clean strings (a comma-separated string is accepted too)."""
    value = settings.get(key_)
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        value = _default(key_) or []
    out = [str(v).strip() for v in value if str(v).strip()]
    if lower:
        out = [v.lower() for v in out]
    if upper:
        out = [v.upper() for v in out]
    return out


def timeout(source: str, fallback: int) -> int:
    """Time limit (s) of one request source (``oracle.timeouts.<source>``)."""
    if source not in TIMEOUTS:
        return fallback
    return get_int(f"oracle.timeouts.{source}", 1)


def preference_domains() -> dict[str, str]:
    value = settings.get(PREFERENCE_DOMAINS)
    if isinstance(value, dict) and value:
        return {str(k): str(v) for k, v in value.items() if str(k).strip()}
    return dict(DEFAULT_PREFERENCE_DOMAINS)


def prompt_ab(surface: str) -> dict:
    """A/B config of one prompt surface: enabled, variants, default, forced."""
    prefix = (AB_SURFACES.get(surface) or ("", ""))[0]
    if not prefix:
        return {}
    return {"enabled": get_bool(f"{prefix}.enabled"),
            "variants": tuple(dict.fromkeys(get_list(f"{prefix}.variants"))) or ("control",),
            "default": str(settings.get(f"{prefix}.default") or "").strip() or "control",
            "forced": str(settings.get(f"{prefix}.force") or "").strip()}


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


def normalize_mode(raw: str | None) -> str:
    """A known mode name, or "" (= follow the setting)."""
    value = str(raw or "").strip().lower()
    value = _MODE_ALIASES.get(value, value)
    return value if value in {m for m, _ in MODES} else ""


def chat_mode(requested: str | None, *, client: str = "", session: str = "") -> str:
    """Mode of this turn: explicit request wins, else the user's setting (session → client → profile)."""
    explicit = normalize_mode(requested)
    if explicit:
        return explicit
    # user_values never raises: Themis down → declared defaults ([🔄] logged there).
    return normalize_mode(settings.user_values(client=client, session=session).get(MODE)) or "auto"
