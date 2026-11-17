"""Oracle settings declared to Themis (central settings).

Models are three object settings (providers, chains, use cases — ``llm_providers`` / ``llm_chains``):
modules send ``use_case`` and declare theirs in the Hub registration. Provider keys
(``ORACLE_KEY_<NAME>``), binaries/paths, ``OLLAMA_URL``, ``ORACLE_EMBED_DIM`` (Archive ``Vector(768)``) and
``TZ`` are secrets/infrastructure and stay in env. Every tunable is read at use time (``apply="live"``).
"""
from __future__ import annotations

import sys
from pathlib import Path
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

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
BRAIN_MODES = [("interna", "Internal"), ("esterna", "External")]
BRAIN_AGENTS = [("claude", "Claude Code (subscription)"), ("codex", "Codex (ChatGPT)")]
BRAIN_FALLBACKS = [("interna", "Redo the turn in internal mode"), ("nessuno", "None: tell me it did not answer")]
# Operating mode (dossier docs/work/2026-11-06-moduli-come-agenti): how a chat turn works. More values may come.
OPERATING_MODE = "oracle.operating_mode"
OPERATING_MODES = [("classic", "Classic"), ("agents", "Module agents")]
AGENTS_MAX_PER_TURN = "oracle.agents.max_per_turn"
AGENTS_HISTORY = "oracle.agents.history"
AGENTS_STEPS = "oracle.agents.steps"

settings = SettingsClient("oracle")


def _definitions() -> list[dict]:
    from core.services.llm_chains import DEFAULT_CHAINS
    from core.services.llm_providers import DEFAULT_PROVIDERS
    return [
        setting(PROVIDERS_KEY, "Providers", "object", DEFAULT_PROVIDERS, group="Models", order=0,
                editor="llm_providers",
                help="Where the models are: name, standard (Ollama, OpenAI compatible, Anthropic compatible, Gemini, Claude subscription) and address. The key lives only in the .env file as ORACLE_KEY_<NAME>."),
        setting(CHAINS_KEY, "Model chains", "object", DEFAULT_CHAINS, group="Models", order=1,
                editor="llm_chains",
                help="Ordered provider/model lists, like font-family: if a model runs out of quota I move to the next and skip it until the quota refills."),
        setting(USECASES_KEY, "Module uses", "object", {}, group="Models", order=2, editor="llm_usecases",
                help="For each use declared by a module: chain, mode and reasoning. Empty = the choice suggested by the module."),
        setting(CHAIN_COOLDOWN, "Pause of a model without quota", "int", 60, group="Models", order=3,
                min=1, max=1440, unit="min", advanced=True,
                help="When the provider does not say when the quota refills (Gemini daily: Pacific midnight)."),
        setting(BRAIN_MODE, "Brain mode", "enum", "interna", group="Models", order=4, options=BRAIN_MODES,
                help="Internal: Oracle reasons with the model chains (classifier, Quick/Thoughtful/CoT, agent loop). External: an agent (Claude Code, Codex) runs the loop with {assistant}'s tools; Oracle prepares the context, saves messages and memory. Each use can choose its own."),
        setting(BRAIN_AGENT, "External agent", "enum", "claude", group="Models", order=5, options=BRAIN_AGENTS,
                help="It needs its login: Claude Code with CLAUDE_CODE_OAUTH_TOKEN, Codex with `codex login` (image with ORACLE_INSTALL_CODEX=1)."),
        setting(BRAIN_MODEL, "External agent model", "string", "sonnet", group="Models", order=6,
                help="E.g. sonnet, opus (Claude Code) or gpt-5-codex (Codex). Empty = the agent's default."),
        setting(BRAIN_FALLBACK, "If the external agent does not answer", "enum", "interna", group="Models", order=7,
                options=BRAIN_FALLBACKS),
        setting(OPERATING_MODE, "Operating mode", "enum", "classic", group="Models", order=8, options=OPERATING_MODES,
                help="Classic: a classifier picks the domains, one loop holds their tools. Module agents: the brain sees one colleague per module and hands it a job; each agent works with its own tools and model chain. How many agents really run together is decided by the local model queue."),
        setting(AGENTS_MAX_PER_TURN, "Agents per answer", "int", 4, group="Models", order=9, min=1, max=12,
                unit="agents", advanced=True, help="Module agents: most agents one answer may call."),
        setting(AGENTS_HISTORY, "Conversation an agent reads", "int", 6, group="Models", order=10, min=0, max=30,
                unit="messages", advanced=True, help="Module agents: last messages of the chat given to each agent."),
        setting(AGENTS_STEPS, "Steps of an agent", "int", 8, group="Models", order=11, min=1, max=40,
                unit="steps", advanced=True, help="Module agents: most steps (tool calls) of one agent's job."),
        setting(USAGE_RETENTION, "Keep model usage for", "int", 90, group="Usage", order=0, min=1,
                max=3650, unit="days", help="Each model call stays in the Usage panel for these days."),
        setting(PRICING_KEY, "Model prices", "object", {}, group="Usage", order=1,
                help="Dollars per million tokens, per «provider/model» (or just the model): {\"gemini/gemini-2.5-flash\": {\"in\": 0.3, \"out\": 2.5, \"cached\": 0.075}}. Only needed where the provider does not say the cost; local models cost 0."),
    ]


TONES = [("warm", "Warm"), ("neutral", "Neutral"), ("direct", "Direct"), ("formal", "Formal")]
_TONE_SENTENCE = {"warm": "Tone: warm and friendly.", "neutral": "",
                  "direct": "Tone: direct, essential, no preambles.", "formal": "Tone: formal."}
TONE, INSTRUCTIONS = "oracle.chat.tone", "oracle.chat.instructions"
MODE = "oracle.chat.mode"
PROFILE_MAX_TOKENS = "oracle.chat.profile_max_tokens"
# Conversation modes (process, not brain): quick = one call no tools · auto = classifier decides ·
# thinking = always agent loop + model reasoning · cot = deep reasoning, more turns, step-by-step plan.
MODES = [("auto", "Auto"), ("quick", "Quick"), ("thinking", "Thoughtful"), ("cot", "CoT · step by step")]
_MODE_ALIASES = {"fast": "quick", "rapida": "quick", "pensata": "thinking", "deep": "cot"}

# Personal chat settings (scope user): same values on every client; profile = default for new sessions,
# a client or a single conversation can override (session → client → profile → default).
_CHAT = [
    setting(TONE, "Answer tone", "enum", "warm", group="Chat", scope="user", options=TONES, order=0,
            help="How {assistant} answers you, on every client."),
    setting(INSTRUCTIONS, "Personal instructions", "text", "", group="Chat", scope="user", order=1,
            help="Added to every conversation (e.g. «always answer briefly»)."),
    setting(MODE, "Conversation mode", "enum", "auto", group="Chat", scope="user", options=MODES, order=2,
            help="Quick: one answer without tools. Auto: {assistant} decides. Thoughtful: reasons and uses tools. CoT: deep step by step reasoning (slower)."),
]

# Context & local runtimes (dossier docs/work/2026-10-10-oracle-local-context). Endpoints stay in env.
NUM_CTX = "oracle.provider.ollama.num_ctx"
KEEP_ALIVE = "oracle.provider.ollama.keep_alive"
COMPACT_THRESHOLD = "oracle.context.compact_threshold"
STUB_AFTER_TURNS = "oracle.context.tool_result_stub_after_turns"
OPENAI_CACHE_PROMPT = "oracle.provider.openai.cache_prompt"
_KEEP_ALIVE = [("5m", "5 minutes"), ("30m", "30 minutes"), ("2h", "2 hours"), ("always", "Always")]

AWARENESS_ITEMS = "oracle.chat.consapevolezza_righe"

_CONTEXT = [
    setting(AWARENESS_ITEMS, "Awareness · recent things per line", "int", 3, group="Context", order=21,
            min=0, max=6, unit="items",
            help="In your conversations {assistant} knows your mood today, the last notifications it sent you and the last things you opened: how many of each (0 = none)."),
    setting(PROFILE_MAX_TOKENS, "{assistant} in other AIs · most space", "int", 1500, group="Context", order=20,
            min=300, max=8000, unit="token",
            help="How much {assistant}'s personality weighs at most (with instructions and memories) when you turn it on inside another AI, for example Claude."),
    setting(NUM_CTX, "Local model · context window", "int", 0, group="Context", min=0, max=262144,
            unit="token", order=0,
            help="0 = automatic: {assistant} uses the window set in the program that runs the model (Ollama, LM Studio, llama-server) and reads it from there. A number forces it from here: higher = remembers more but uses more VRAM; changing it reloads the model."),
    setting(KEEP_ALIVE, "Ollama · model in memory", "enum", "30m", group="Context", options=_KEEP_ALIVE,
            order=1, help="How long the model stays loaded after the last request: avoids a cold start."),
    setting(COMPACT_THRESHOLD, "Compact the context beyond", "float", 0.8, group="Context", min=0.3, max=0.95,
            order=2, advanced=True, help="Fraction of the window beyond which the conversation is summarised."),
    setting(STUB_AFTER_TURNS, "Shorten tool results after", "int", 2, group="Context", min=0,
            max=20, unit="steps", order=3, advanced=True,
            help="In long reasoning, results older than N steps become a summary line when the context fills up. 0 = never."),
    setting(OPENAI_CACHE_PROMPT, "OpenAI compatible server · reuse the prompt cache", "bool", True,
            group="Context", order=4, advanced=True,
            help="Asks llama-server to reuse the prefix already computed (cache_prompt). Turn it off if the server refuses the field."),
    setting("oracle.provider.llamacpp.slots", "llama-server · warm conversations together", "int", 3,
            group="Context", min=2, max=16, unit="slot", order=5, advanced=True,
            help="Must equal the server's --parallel. Slot 0 serves the calls without a chat (classifier, modules); the others each hold the context of one chat and save it to disk when they switch to another."),
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
    "foreground_chat": ("Chat answer", 8),
    "action_selection": ("Choice of the action", 12),
    "action_service_route": ("Action on a module", 25),
    "memory_extraction": ("Memory extraction", 10),
    "background_compaction": ("Background compaction", 8),
    "notification_formatting": ("Notification text", 12),
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
AB_SURFACES = {"alert_formatter": ("oracle.prompt_ab.alert", "Notifications"),
               "planner_behavior": ("oracle.prompt_ab.planner", "Planner")}

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
_TOOL_MODES = [("auto", "Automatic"), ("native", "Native"), ("text", "Text")]

_AGENT = [
    setting(MAX_TURNS, "Most steps per answer", "int", 25, group="Agent", min=1, max=100, unit="steps",
            order=0, help="How many times at most the assistant uses tools before answering you (CoT mode uses at least 50)."),
    setting(ASK_TIMEOUT, "A question for you stays open for", "int", 24, group="Agent", min=1, max=720,
            unit="hours", order=3, help="When the assistant asks you something (choice, confirmation, free text), after this time without an answer the question closes."),
    setting(MAX_TOKENS, "Most tokens per answer", "int", 0, group="Agent", min=0, max=2_000_000,
            unit="token", order=1, advanced=True, help="Limit of tokens used in one reasoning. 0 = no limit."),
    setting(TOOL_RESULT_MAX_CHARS, "Longest tool result", "int", 2000,
            group="Agent", min=200, max=50000, unit="characters", order=2, advanced=True,
            help="Beyond this length the result is shortened before giving it to the model."),
    setting(EARLY_EXIT_NO_TOOL_TURNS, "Close after steps without tools", "int", 2, group="Agent", min=1,
            max=10, unit="steps", order=3, advanced=True,
            help="If the model uses no tools for these steps in a row (and has already done something), it answers."),
    setting(MAX_PARALLEL_TOOLS, "Parallel tools", "int", 8, group="Agent", min=1, max=32, order=4,
            advanced=True, help="How many tools can run together in the same step."),
    # Loop guard (core/services/loop_guard.py, Cindy 1): always on, these only shape it.
    setting("oracle.agent.giri.ripetizioni", "Loops · same call in a row", "int", 4, group="Agent",
            min=2, max=20, order=5, advanced=True,
            help="If the assistant makes the same identical call many times in a row, it stops and answers you with what it has."),
    setting("oracle.agent.giri.finestra", "Loops · calls watched", "int", 12, group="Agent", min=6,
            max=50, order=6, advanced=True,
            help="Last calls in which I look for a ping-pong (A-B-A-B) or a repeating loop."),
    setting("oracle.agent.giri.attesa_secondi", "Loops · a real wait lasts at least", "int", 30,
            group="Agent", min=0, max=3600, unit="s", order=7, advanced=True,
            help="A call repeated after this time is a check («checking again shortly»), not a loop."),
    setting("oracle.agent.giri.verifiche", "Loops · checks with the light model", "int", 3,
            group="Agent", min=0, max=10, order=8, advanced=True,
            help="When in doubt a light model looks at the calls and says whether it is waiting or looping. 0 = I stop at once."),
    # Conversation goal (core/services/conversation_goal.py, Cindy 23).
    setting("oracle.obiettivo.giri", "Goal · rounds in total", "int", 8, group="Agent", min=1, max=50,
            order=9, help="How many work rounds in total the assistant does on a conversation goal."),
    setting("oracle.obiettivo.giri_per_risposta", "Goal · rounds after each answer", "int", 3, group="Agent",
            min=1, max=10, order=9, advanced=True,
            help="After answering one of your messages, how many rounds it does on the goal before updating you."),
    setting(HISTORY_LIMIT, "Previous messages in the context", "int", 6, group="Context", min=1, max=100,
            unit="messages", order=10, help="How many conversation messages the assistant rereads at each answer."),
    setting(HISTORY_CHAR_LIMIT, "Longest previous message", "int", 500, group="Context",
            min=50, max=20000, unit="characters", order=11, advanced=True,
            help="Longer old messages are shortened in the context."),
    setting(ENTITIES_LIMIT, "Module items in the context", "int", 12, group="Context", min=1, max=100,
            order=12, advanced=True, help="How many items found in the modules (listings, events…) go into the analysis."),
    setting(FIELD_CHAR_LIMIT, "Longest field", "int", 280, group="Context", min=50, max=5000,
            unit="characters", order=13, advanced=True, help="Each field of an item is shortened to this length."),
    setting(COMPACT_TRIGGER, "Summarise the conversation beyond", "int", 20, group="Context", min=6, max=500,
            unit="messages", order=14, advanced=True,
            help="Beyond this number of messages the old part of the conversation is summarised."),
    setting(COMPACT_KEEP, "Recent messages not to summarise", "int", 6, group="Context", min=2, max=50,
            unit="messages", order=15, advanced=True, help="The latest messages stay whole when summarising."),
    setting(TODAY_AGENDA, "Today's agenda in the context", "bool", True, group="Context", order=16,
            help="At each answer the assistant reads today's commitments from the calendar (a few more tokens)."),
]
_TIMEOUTS = [
    setting(f"oracle.timeouts.{name}", f"Maximum time · {label.lower()}", "int", default, group="Timings",
            min=1, max=600, unit="s", order=i, advanced=True,
            help="Beyond this time the step is skipped or the backup plan is used.")
    for i, (name, (label, default)) in enumerate(TIMEOUTS.items())
] + [
    setting(GATEWAY_CHAT_TIMEOUT, "Longest time · Forge requests to the model", "int", 600, group="Timings",
            min=30, max=3600, unit="s", order=20, advanced=True,
            help="A Forge request to the model (use forge.codice) that exceeds this time fails."),
    setting(OLLAMA_TIMEOUT, "Longest time · Ollama answer", "int", 120, group="Timings", min=10, max=1800,
            unit="s", order=21, help="How long I wait for an answer from the local model."),
    setting(OLLAMA_EMBED_TIMEOUT, "Longest time · Ollama embedding", "int", 60, group="Timings", min=5,
            max=600, unit="s", order=22, advanced=True),
    setting(LLM_RETRIES, "Attempts towards the model", "int", 3, group="Timings", min=1, max=10, order=23,
            advanced=True, help="How many times I retry a failing model call."),
    setting(LLM_RETRY_DELAY, "Wait between attempts", "float", 1.0, group="Timings", min=0.1, max=60, unit="s",
            order=24, advanced=True, help="First wait; it doubles at each new attempt."),
]
_PROVIDER = [
    setting(OLLAMA_TOOL_MODE, "Ollama · way to call tools", "enum", "auto", group="Context",
            options=_TOOL_MODES, order=5, advanced=True,
            help="Native: uses Ollama tool calls. Text: the model writes them in the text. Automatic: native, text if the model does not support it."),
    setting(THINKING_FAMILIES, "Ollama · model families that reason", "list", _DEFAULT_THINKING_FAMILIES,
            group="Context", order=6, advanced=True,
            help="With «Automatic» reasoning, a model of these families reasons before answering."),
    # LLM bus (core/services/llm_bus.py, dossier 2026-11-16-bus-llm): local calls served together.
    setting("oracle.bus.local_workers", "Local models · answers prepared together", "int", 1, group="Context",
            min=1, max=16, order=7,
            help="How many requests the local model works on at the same time; the others wait in line and your "
                 "messages always go ahead of background work. 1 = one at a time. Raise it only if the program "
                 "running the model can handle more at once (Ollama: OLLAMA_NUM_PARALLEL, llama-server: --parallel)."),
]
_MEMORY = [
    setting(NOTICE_WAIT, "Wait for memory notices", "float", 8.0, group="Memory", min=0, max=60,
            unit="s", order=0, advanced=True,
            help="After the answer I wait at most this long to tell you what I memorised."),
    setting(DOMAIN_THRESHOLD, "Similarity to assign an area", "float", 0.55, group="Memory", min=0.1,
            max=0.99, order=1, advanced=True,
            help="A preference goes into an area (food, work…) if it resembles it at least this much. Higher = stricter."),
    setting(PREFERENCE_DOMAINS, "Preference areas", "object", DEFAULT_PREFERENCE_DOMAINS, group="Memory",
            order=2, advanced=True,
            help="Area name → description (in English) used to recognise it. «general» is always there."),
    setting(FORCE_OWNER_TARGET, "Subscription alerts always to you", "bool", True, group="Memory",
            order=3, advanced=True,
            help="The alerts you ask for in chat («tell me when…») always come to you, ignoring other destinations the model proposes."),
]
_APPROVAL = [
    setting(APPROVAL_ENABLED, "Ask confirmation for important actions", "bool", True, group="Confirmations",
            oracle="read", order=0,
            help="Before deleting, changing or acting on several items the assistant asks you to confirm."),
    setting(APPROVAL_TTL, "Validity of a confirmation request", "int", 600, group="Confirmations", min=30,
            max=86400, unit="s", oracle="read", order=1, advanced=True,
            depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="After this time a confirmation request with no answer expires."),
    setting(APPROVAL_BULK_MIN, "Confirm if the action touches at least", "int", 2, group="Confirmations", min=1, max=100,
            unit="items", oracle="read", order=2, advanced=True,
            depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="An action repeated on at least these items asks for confirmation."),
    setting(APPROVAL_METHODS, "Request types to confirm", "list", ["DELETE", "PUT", "PATCH"],
            group="Confirmations", oracle="read", order=3, advanced=True,
            depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="HTTP methods that always ask confirmation (DELETE = delete, PUT/PATCH = change)."),
    setting(APPROVAL_COMMANDS, "Commands to always confirm", "list", [], group="Confirmations", oracle="read",
            order=4, advanced=True, depends_on={"key": APPROVAL_ENABLED, "equals": True},
            help="Names of commands that always ask confirmation, whatever their type."),
]
_RUNTIME = [
    setting(HINTS_ENABLED, "Use Athena's suggestions", "bool", True, group="Memory", order=9,
            help="Athena's observations (what interests you now) guide the answers. Off = ignored."),
    setting(HINTS_TTL, "Duration of Athena's suggestions", "int", 7200, group="Memory", min=60, max=604800,
            unit="s", order=10, advanced=True, help="How long an Athena suggestion stays valid."),
    setting(HINTS_MAX, "Athena suggestions kept", "int", 300, group="Memory", min=10, max=5000,
            order=11, advanced=True),
    setting(SCHEMAS_CACHE_TTL, "Module schema cache", "int", 30, group="Diagnostics", min=0,
            max=3600, unit="s", order=10, advanced=True),
    setting(TOOL_REGISTRY_TTL, "Module tool cache", "int", 120, group="Diagnostics", min=0,
            max=3600, unit="s", order=11, advanced=True,
            help="How often I reread the list of available tools from the modules."),
    setting(TASKS_MAX, "Background tasks remembered", "int", 500, group="Diagnostics", min=50, max=10000,
            order=12, advanced=True),
]
_DOCUMENTS = [
    setting(DOC_MAX_ARCHIVE_MB, "Largest size to archive a file", "int", 10, group="Documents",
            min=1, max=500, unit="MB", order=0,
            help="Larger files are analysed but not saved in the document archive."),
    setting(DOC_SEARCH_THRESHOLD, "Longest distance in document search", "float", 1.2, group="Documents",
            min=0.1, max=2.0, order=1, advanced=True,
            help="Lower = only very relevant documents; higher = more results."),
    setting(VISION_MODELS, "Models that read images", "list", _DEFAULT_VISION, group="Documents",
            order=3, advanced=True, help="Start of the name of the models that can look at images and PDFs."),
    setting(AUDIO_MODELS, "Models that listen to audio", "list", ["gemini-1.5", "gemini-2"], group="Documents",
            order=4, advanced=True, help="Start of the name of the models that understand audio without transcription."),
]
_AB = []
for _i, (_surface, (_prefix, _label)) in enumerate(AB_SURFACES.items()):
    _AB += [
        setting(f"{_prefix}.enabled", f"Prompt experiment · {_label}", "bool", False, group="Experiments",
                order=_i * 10, advanced=True,
                help="Splits requests between prompt variants to compare them."),
        setting(f"{_prefix}.variants", f"Prompt experiment · {_label} · variants", "list",
                ["control", "experimental"], group="Experiments", order=_i * 10 + 1, advanced=True),
        setting(f"{_prefix}.default", f"Prompt experiment · {_label} · normal variant", "string", "control",
                group="Experiments", order=_i * 10 + 2, advanced=True,
                help="Used when the experiment is off."),
        setting(f"{_prefix}.force", f"Prompt experiment · {_label} · force variant", "string", "",
                group="Experiments", order=_i * 10 + 3, advanced=True,
                help="If set, always used (even with the experiment off)."),
    ]

def _advanced_except_models(defs: list[dict]) -> list[dict]:
    """Only Models (and the personal Chat settings) stay in view; Oracle's other tunables are advanced."""
    for d in defs:
        if d.get("group") not in ("Models", "Chat"):
            d["advanced"] = True
    return defs


settings.declare(_advanced_except_models(_definitions() + _CHAT + _CONTEXT + _AGENT + _TIMEOUTS + _PROVIDER
                                         + _MEMORY + _APPROVAL + _RUNTIME + _DOCUMENTS + _AB)).declare_log_level()
settings.follow_personal()      # who the owner is and who the assistant is (hestia_common.identity)


def identity() -> dict[str, str]:
    """Assistant name, she/he and the owner's name, live from the personal settings."""
    from hestia_common import identity as _identity
    return _identity.read(settings.get)


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


def forced_num_ctx() -> int:
    """Window the owner forced from Hestia (0 = automatic: the local program decides)."""
    try:
        value = int(settings.get(NUM_CTX) or 0)
    except (TypeError, ValueError):
        return 0
    return max(512, value) if value > 0 else 0


def context_window(model: str = "") -> int:
    """Real context window (tokens) of the local model: budgeting, compaction, gauge. Forced by the setting, or
    read from the program that runs the model (``core.services.local_window``)."""
    from core.services import local_window
    return local_window.ollama_window(model)


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


def ollama_request_options(model: str = "") -> dict:
    """Fields added to every Ollama request: ``keep_alive`` (avoid cold starts) and, only when the window is
    forced from Hestia (or Ollama's own is too small), the same ``num_ctx`` on every call (a different value
    makes Ollama reload the model). On «automatica» no ``num_ctx`` is sent: Ollama keeps the owner's window."""
    from core.services import local_window
    keep = str(settings.get(KEEP_ALIVE) or "30m")
    num_ctx = local_window.ollama_num_ctx(model)
    return {"options": {"num_ctx": num_ctx} if num_ctx else {}, "keep_alive": -1 if keep == "always" else keep}


def provider_settings(provider_type: str) -> dict:
    """Tunables of one provider type (merged into its infrastructure config)."""
    if provider_type == "openai":
        return {"cache_prompt": bool(settings.get(OPENAI_CACHE_PROMPT, True))}
    if provider_type == "llamacpp":
        return {"cache_prompt": True}
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
        out.append(f"The owner's own instructions (follow them): {custom}")
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


def operating_mode() -> str:
    """``classic`` or ``agents`` (live; unknown value = ``classic``)."""
    value = str(settings.get(OPERATING_MODE) or "classic").strip().lower()
    return value if value in {v for v, _ in OPERATING_MODES} else "classic"
