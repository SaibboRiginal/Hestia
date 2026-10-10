"""Athena settings declared to Themis (central settings).

Every tunable of Athena lives here (no env vars): the loop, the relevance gate, the
retrospective, Oracle hints, observer/strategist/auditor timeouts, memory consolidation and
skill curation thresholds. All ``live`` (read at use time) except the task store size.

*When* Athena works (consolidation, skill curation, thinking windows) is NOT a setting:
those are assistant-agenda windows (Chronos) the user moves/skips/pauses there.
"""
from __future__ import annotations

from .shared_imports import import_shared_symbol

SettingsClient = import_shared_symbol("hestia_common.settings_client", "SettingsClient")
setting = import_shared_symbol("hestia_common.settings_client", "setting")

PROPOSALS_PER_DAY = "athena.settings.proposals_per_day"

LOOP_ENABLED = "athena.loop.enabled"
LOOP_INTERVAL = "athena.loop.interval"
LOOP_IDLE_SECONDS = "athena.loop.idle_seconds"
GATE_THRESHOLD = "athena.gate.threshold"

RETRO_WINDOW = "athena.retro.window"
RETRO_FAILURE_URGENCY_BOOST = "athena.retro.failure_urgency_boost"
RETRO_UNRESOLVED_URGENCY_BOOST = "athena.retro.unresolved_urgency_boost"
RETRO_UNRESOLVED_USEFULNESS_BOOST = "athena.retro.unresolved_usefulness_boost"
COMMITMENT_TTL = "athena.commitments.ttl"

HINTS_ENABLED = "athena.hints.enabled"
HINTS_TIMEOUT = "athena.hints.timeout"

THINKING_ARCHIVE_ENABLED = "athena.thinking.archive_enabled"
THINKING_STORE_MAX = "athena.thinking.store_max"
TASK_STORE_MAX = "athena.tasks.store_max"

OBSERVE_TIMEOUT = "athena.observe.timeout"
OBSERVE_ENTITY_WINDOW_HOURS = "athena.observe.entity_window_hours"

STRATEGIST_ENABLED = "athena.strategist.enabled"
STRATEGIST_TIMEOUT = "athena.strategist.timeout"
STRATEGIST_MAX_CANDIDATES = "athena.strategist.max_candidates"

FORGE_ENABLED = "athena.forge.enabled"
FORGE_MAX_PER_DAY = "athena.forge.max_per_day"

MEMORY_ACTIVE_DAYS = "athena.memory.active_days"
MEMORY_LOOKBACK_HOURS = "athena.memory.lookback_hours"
MEMORY_ORACLE_TIMEOUT = "athena.memory.oracle_timeout"
MEMORY_PREFERENCE_DECAY_DAYS = "athena.memory.preference_decay_days"
MEMORY_REINFORCE_THRESHOLD = "athena.memory.reinforce_threshold"

SKILLS_MIN_SESSIONS = "athena.skills.min_sessions"
SKILLS_SIM_THRESHOLD = "athena.skills.sim_threshold"
SKILLS_DEDUP_THRESHOLD = "athena.skills.dedup_threshold"
SKILLS_STALE_DAYS = "athena.skills.stale_days"
SKILLS_HARD_DELETE_DAYS = "athena.skills.hard_delete_days"
SKILLS_CORE_USE_COUNT = "athena.skills.core_use_count"

AUDIT_TIMEOUT = "athena.audit.timeout"
AUDIT_MAX_TURNS = "athena.audit.max_turns"

_G_LOOP = "Pensiero proattivo"
_G_RETRO = "Retrospettiva"
_G_HINTS = "Suggerimenti a Oracle"
_G_RECORDS = "Registro dei pensieri"
_G_STRATEGY = "Osservazione e strategia"
_G_FORGE = "Miglioramenti (Forge)"
_G_MEMORY = "Consolidamento memoria"
_G_SKILLS = "Cura delle skill"
_G_AUDIT = "Audit conversazioni"

_ON_LOOP = {"key": LOOP_ENABLED, "equals": True}
_ON_HINTS = {"key": HINTS_ENABLED, "equals": True}
_ON_FORGE = {"key": FORGE_ENABLED, "equals": True}
_ON_STRATEGIST = {"key": STRATEGIST_ENABLED, "equals": True}

settings = SettingsClient("athena")
settings.declare([
    setting(PROPOSALS_PER_DAY, "Proposte di impostazioni al giorno", "int", 2, group="Proposte", min=0, max=10,
            help="Quante modifiche alle impostazioni Athena può proporti al giorno (0 = nessuna). "
                 "Ogni proposta aspetta sempre la tua conferma."),

    # ── Loop ────────────────────────────────────────────────────────────────
    setting(LOOP_ENABLED, "Athena attiva", "bool", True, group=_G_LOOP, order=0,
            help="Se spenta, Athena non osserva, non pensa e non ti propone nulla da sola."),
    setting(LOOP_INTERVAL, "Intervallo tra i cicli", "int", 300, group=_G_LOOP, min=30, max=86400, unit="s",
            order=1, depends_on=_ON_LOOP,
            help="Ogni quanto Athena fa un giro di osservazione e riflessione. Più corto = più reattiva ma "
                 "usa di più il modello."),
    setting(LOOP_IDLE_SECONDS, "Pausa dalla chat richiesta", "int", 300, group=_G_LOOP, min=0, max=7200, unit="s",
            order=2, depends_on=_ON_LOOP,
            help="Athena pensa solo se non chatti da almeno questo tempo, per non rubare il modello "
                 "(0 = pensa anche mentre chatti)."),
    setting(GATE_THRESHOLD, "Soglia di rilevanza", "float", 0.55, group=_G_LOOP, min=0.0, max=1.0, order=3,
            depends_on=_ON_LOOP,
            help="Quanto deve essere rilevante un'idea perché Athena te la mandi. Più alta = meno messaggi, "
                 "solo i più utili."),

    # ── Retrospective (expert) ──────────────────────────────────────────────
    setting(RETRO_WINDOW, "Esiti ricordati", "int", 24, group=_G_RETRO, min=1, max=500, advanced=True,
            help="Quanti esiti recenti Athena considera per capire cosa sta andando male."),
    setting(RETRO_FAILURE_URGENCY_BOOST, "Spinta urgenza per fallimenti", "float", 0.07, group=_G_RETRO,
            min=0.0, max=0.5, advanced=True,
            help="Quanto ogni fallimento consecutivo aumenta l'urgenza delle nuove idee."),
    setting(RETRO_UNRESOLVED_URGENCY_BOOST, "Spinta urgenza per impegni aperti", "float", 0.04, group=_G_RETRO,
            min=0.0, max=0.5, advanced=True,
            help="Quanto ogni impegno non risolto aumenta l'urgenza delle nuove idee."),
    setting(RETRO_UNRESOLVED_USEFULNESS_BOOST, "Spinta utilità per impegni aperti", "float", 0.03,
            group=_G_RETRO, min=0.0, max=0.5, advanced=True,
            help="Quanto ogni impegno non risolto aumenta l'utilità stimata delle nuove idee."),
    setting(COMMITMENT_TTL, "Durata di un impegno", "int", 86400, group=_G_RETRO, min=60, max=2592000, unit="s",
            advanced=True,
            help="Dopo quanto un suggerimento non risolto scade (vale anche per i suggerimenti dati a Oracle)."),

    # ── Oracle hints ────────────────────────────────────────────────────────
    setting(HINTS_ENABLED, "Suggerimenti all'assistente", "bool", True, group=_G_HINTS,
            help="Athena passa a Oracle le sue idee, così l'assistente ne tiene conto quando parli con lui."),
    setting(HINTS_TIMEOUT, "Attesa invio suggerimento", "int", 8, group=_G_HINTS, min=1, max=120, unit="s",
            advanced=True, depends_on=_ON_HINTS,
            help="Quanto aspettare Oracle quando Athena gli passa un suggerimento."),

    # ── Thinking records ────────────────────────────────────────────────────
    setting(THINKING_ARCHIVE_ENABLED, "Salva i pensieri in archivio", "bool", True, group=_G_RECORDS,
            help="Conserva in Archive ogni ciclo di pensiero (cosa ha visto, considerato e deciso)."),
    setting(THINKING_STORE_MAX, "Pensieri tenuti in memoria", "int", 100, group=_G_RECORDS, min=5, max=1000,
            advanced=True, help="Quanti cicli di pensiero recenti Athena tiene pronti da mostrarti."),
    setting(TASK_STORE_MAX, "Attività tenute in memoria", "int", 500, group=_G_RECORDS, min=50, max=5000,
            apply="restart", advanced=True,
            help="Quante attività recenti Athena ricorda (vale dal prossimo riavvio)."),

    # ── Observer + strategist ───────────────────────────────────────────────
    setting(OBSERVE_TIMEOUT, "Attesa osservazione moduli", "float", 8.0, group=_G_STRATEGY, min=1, max=60,
            unit="s", advanced=True,
            help="Quanto aspettare ogni modulo quando Athena raccoglie lo stato del sistema."),
    setting(OBSERVE_ENTITY_WINDOW_HOURS, "Novità considerate", "int", 24, group=_G_STRATEGY, min=1, max=720,
            unit="h", help="Quanto indietro guardare per i dati nuovi dei moduli (es. annunci, eventi)."),
    setting(STRATEGIST_ENABLED, "Idee con il modello", "bool", True, group=_G_STRATEGY,
            help="Athena usa il modello per trasformare ciò che osserva in idee e proposte."),
    setting(STRATEGIST_TIMEOUT, "Attesa idee dal modello", "float", 20.0, group=_G_STRATEGY, min=5, max=300,
            unit="s", advanced=True, depends_on=_ON_STRATEGIST,
            help="Quanto aspettare il modello per ogni giro di idee."),
    setting(STRATEGIST_MAX_CANDIDATES, "Idee per ciclo", "int", 3, group=_G_STRATEGY, min=1, max=10,
            depends_on=_ON_STRATEGIST,
            help="Quante idee al massimo Athena valuta in ogni ciclo."),

    # ── Forge hand-off (acts without the user: assistant may only read it) ─
    setting(FORGE_ENABLED, "Proponi miglioramenti a Forge", "bool", True, group=_G_FORGE, oracle="read",
            help="Athena manda a Forge le idee di miglioramento del codice. Forge segue i permessi che hai "
                 "scelto; il merge chiede sempre a te."),
    setting(FORGE_MAX_PER_DAY, "Miglioramenti al giorno", "int", 2, group=_G_FORGE, min=0, max=20,
            depends_on=_ON_FORGE, oracle="read",
            help="Quante richieste di miglioramento Athena può mandare a Forge ogni giorno."),

    # ── Memory consolidation ────────────────────────────────────────────────
    setting(MEMORY_ACTIVE_DAYS, "Sessioni recenti considerate", "int", 7, group=_G_MEMORY, min=1, max=90,
            unit="giorni", help="Consolida la memoria delle conversazioni attive negli ultimi N giorni."),
    setting(MEMORY_LOOKBACK_HOURS, "Intervallo minimo per sessione", "int", 24, group=_G_MEMORY, min=1, max=720,
            unit="h", advanced=True,
            help="Una stessa conversazione non viene riconsolidata prima di questo tempo."),
    setting(MEMORY_ORACLE_TIMEOUT, "Attesa analisi memoria", "int", 30, group=_G_MEMORY, min=5, max=600,
            unit="s", advanced=True, help="Quanto aspettare il modello che estrae i fatti da ricordare."),
    setting(MEMORY_PREFERENCE_DECAY_DAYS, "Oblio preferenze", "int", 90, group=_G_MEMORY, min=7, max=3650,
            unit="giorni",
            help="Le preferenze non più confermate da questo tempo perdono importanza."),
    setting(MEMORY_REINFORCE_THRESHOLD, "Conferme per rafforzare", "int", 3, group=_G_MEMORY, min=1, max=50,
            advanced=True, help="Quante volte uno schema deve ripetersi prima di diventare una preferenza forte."),

    # ── Skill curation ──────────────────────────────────────────────────────
    setting(SKILLS_MIN_SESSIONS, "Sessioni per creare una skill", "int", 3, group=_G_SKILLS, min=1, max=50,
            help="Quante conversazioni simili servono perché Athena ne ricavi una skill."),
    setting(SKILLS_SIM_THRESHOLD, "Somiglianza tra conversazioni", "float", 0.90, group=_G_SKILLS,
            min=0.5, max=1.0, advanced=True,
            help="Quanto devono somigliarsi due conversazioni per essere raggruppate."),
    setting(SKILLS_DEDUP_THRESHOLD, "Somiglianza per skill doppie", "float", 0.95, group=_G_SKILLS,
            min=0.5, max=1.0, advanced=True,
            help="Oltre questa somiglianza due skill sono considerate la stessa e vengono unite."),
    setting(SKILLS_STALE_DAYS, "Skill inutilizzate da deprecare", "int", 30, group=_G_SKILLS, min=1, max=3650,
            unit="giorni", help="Una skill non usata da questo tempo viene deprecata."),
    setting(SKILLS_HARD_DELETE_DAYS, "Skill inutilizzate da eliminare", "int", 90, group=_G_SKILLS, min=1,
            max=3650, unit="giorni",
            help="Una skill poco usata e ferma da questo tempo viene eliminata."),
    setting(SKILLS_CORE_USE_COUNT, "Usi per skill fondamentale", "int", 50, group=_G_SKILLS, min=1, max=10000,
            advanced=True,
            help="Una skill usata più di così con successo diventa fondamentale."),

    # ── Conversation audit ──────────────────────────────────────────────────
    setting(AUDIT_TIMEOUT, "Attesa audit", "float", 40.0, group=_G_AUDIT, min=5, max=600, unit="s",
            advanced=True, help="Quanto aspettare il modello che valuta le risposte."),
    setting(AUDIT_MAX_TURNS, "Risposte per audit", "int", 20, group=_G_AUDIT, min=1, max=100,
            help="Quante risposte recenti valuta un audit se non indichi altro."),
]).declare_log_level()


def get_int(key: str) -> int:
    return int(settings.get(key))


def get_float(key: str) -> float:
    return float(settings.get(key))


def get_bool(key: str) -> bool:
    return bool(settings.get(key))
