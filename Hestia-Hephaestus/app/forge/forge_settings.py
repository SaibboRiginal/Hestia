"""Hephaestus settings declared to Themis (central settings) — one file for the module.

Forge: default engine, permission modes, fallback order, turn/timeout limits, merge/rollback/push
switches, verify delay, scheduler check interval. Remediation: execution timeout, approval
switches, retry policy. All live: read with ``settings.get`` at use time (engine/modes also via
``Forge._apply_settings``). ``data/forge/settings.json`` keeps only the Claude Pro schedule/state.
Env keeps infrastructure only (repo/worktree/data paths, base branch, git identity, deploy and
test commands, notify target, Forge on/off of the deployment) — see config.py.
"""
from __future__ import annotations

from ..core.shared_imports import import_shared_symbol

SettingsClient = import_shared_symbol("hestia_common.settings_client", "SettingsClient")
setting = import_shared_symbol("hestia_common.settings_client", "setting")

ENGINE = "hephaestus.forge.engine"
MODE = {"local": "hephaestus.forge.mode.local", "cloud": "hephaestus.forge.mode.cloud"}
FALLBACK = "hephaestus.forge.fallback"
MAX_TURNS = "hephaestus.forge.max_turns"
LLM_TIMEOUT = "hephaestus.forge.llm_timeout"
ENGINE_TIMEOUT = "hephaestus.forge.engine_timeout"
AUTO_MERGE = "hephaestus.forge.auto_merge"
AUTO_ROLLBACK = "hephaestus.forge.auto_rollback"
PUSH_BRANCH = "hephaestus.forge.push_branch"
VERIFY_DELAY = "hephaestus.forge.verify_delay"
SCHEDULER_INTERVAL = "hephaestus.forge.scheduler_interval"

REMEDIATE_TIMEOUT = "hephaestus.remediate.timeout"
REMEDIATE_REQUIRE_APPROVAL = "hephaestus.remediate.require_approval"
REMEDIATE_AUTO_APPROVE_NON_PROD = "hephaestus.remediate.auto_approve_non_prod"
REPAIR_RETRY_MINUTES = "hephaestus.remediate.retry_minutes"
REPAIR_MAX_ATTEMPTS = "hephaestus.remediate.max_attempts"

_ENGINES = [("local", "Locale (Ollama)"), ("cloud", "Cloud (Gemini)"), ("claude", "Claude Code")]
_MODES = [("ask", "Chiedi sempre"), ("auto", "Sviluppa da solo, il merge chiede"),
          ("full_auto", "Tutto da solo se i test passano")]
_FORGE = "Sviluppo (Forge)"
_REPAIR = "Riparazioni"

settings = SettingsClient("hephaestus")
settings.declare([
    setting(ENGINE, "Motore di sviluppo predefinito", "enum", "local", group=_FORGE,
            options=_ENGINES, order=0,
            help="Chi scrive il codice quando chiedi una modifica. Se non è disponibile si usa il successivo."),
    # Safety switches: the assistant can read them but never propose a change.
    setting(MODE["local"], "Permessi · motore locale", "enum", "auto", group=_FORGE,
            options=_MODES, order=1, oracle="read",
            help="Quanta autonomia ha Forge quando usa il modello locale (gratis)."),
    setting(MODE["cloud"], "Permessi · cloud e Claude", "enum", "ask", group=_FORGE,
            options=_MODES, order=2, oracle="read",
            help="Quanta autonomia ha Forge quando usa motori a pagamento o a consumo."),
    setting(FALLBACK, "Ordine dei motori di riserva", "list", ["local", "cloud", "claude"], group=_FORGE,
            order=3, advanced=True,
            help="Se il motore predefinito non è disponibile provo questi, in ordine (local, cloud, claude)."),
    setting(MAX_TURNS, "Passi massimi per task", "int", 40, group=_FORGE, min=5, max=300, order=4,
            help="Quante azioni (letture, modifiche, test) può fare il motore prima di fermarsi."),
    setting(LLM_TIMEOUT, "Attesa massima per risposta del modello", "int", 600, group=_FORGE,
            min=60, max=3600, unit="s", order=5, advanced=True,
            help="Motori local/cloud: quanto aspetto ogni risposta del modello prima di dare errore."),
    setting(ENGINE_TIMEOUT, "Durata massima Claude Code", "int", 1800, group=_FORGE,
            min=60, max=14400, unit="s", order=6, advanced=True,
            help="Tempo massimo di una sessione Claude Code su un task."),
    setting(AUTO_MERGE, "Merge automatico predefinito", "bool", False, group=_FORGE, order=7, oracle="read",
            help="Se attivo, i task senza indicazione fanno il merge da soli quando i test passano "
                 "(sempre nel rispetto dei permessi)."),
    setting(AUTO_ROLLBACK, "Annulla da solo un deploy non sano", "bool", True, group=_FORGE, order=8,
            oracle="read",
            help="Dopo il deploy, se un servizio non risponde sano, Forge annulla il merge e riavvia."),
    setting(PUSH_BRANCH, "Pubblica il branch sul remoto", "bool", False, group=_FORGE, order=9,
            oracle="read", advanced=True,
            help="Fa git push del branch del task verso il remoto (origin) dopo i test."),
    setting(VERIFY_DELAY, "Attesa prima del controllo salute", "int", 20, group=_FORGE,
            min=0, max=600, unit="s", order=10, advanced=True,
            help="Dopo il riavvio dei servizi aspetto questo tempo prima di verificarne la salute."),
    setting(SCHEDULER_INTERVAL, "Controllo finestra Claude", "int", 300, group=_FORGE,
            min=30, max=3600, unit="s", order=11, advanced=True,
            help="Ogni quanto controllo se un task in attesa della finestra Claude Pro può partire."),
    setting(REMEDIATE_TIMEOUT, "Attesa massima di una riparazione", "float", 25.0, group=_REPAIR,
            min=5, max=600, unit="s", order=20, advanced=True,
            help="Quanto aspetto il servizio quando eseguo un'azione di manutenzione."),
    setting(REMEDIATE_REQUIRE_APPROVAL, "Chiedi conferma per le riparazioni", "bool", True, group=_REPAIR,
            order=21, oracle="read",
            help="Se attivo, ogni riparazione che modifica qualcosa (non simulata) aspetta il tuo ok."),
    setting(REMEDIATE_AUTO_APPROVE_NON_PROD, "Auto-approvazione fuori produzione", "bool", False,
            group=_REPAIR, order=22, oracle="read",
            help="Permette alle richieste di auto-approvarsi negli ambienti non di produzione."),
    setting(REPAIR_RETRY_MINUTES, "Attesa tra i tentativi", "int", 15, group=_REPAIR,
            min=1, max=1440, unit="min", order=23,
            help="Dopo una riparazione fallita riprovo dopo questo tempo × numero di tentativi."),
    setting(REPAIR_MAX_ATTEMPTS, "Tentativi massimi", "int", 3, group=_REPAIR, min=1, max=20, order=24,
            help="Dopo l'ultimo tentativo fallito il problema passa a Forge come correzione del codice."),
]).declare_log_level()


def get_int(key: str, minimum: int) -> int:
    try:
        return max(minimum, int(settings.get(key)))
    except (TypeError, ValueError):
        return max(minimum, int(settings._defs[key]["default"]))


def get_float(key: str, minimum: float) -> float:
    try:
        return max(minimum, float(settings.get(key)))
    except (TypeError, ValueError):
        return max(minimum, float(settings._defs[key]["default"]))


def get_bool(key: str) -> bool:
    value = settings.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def fallback() -> list[str]:
    """Engine fallback order (normalized, unknown names dropped by ``select_engine``)."""
    from .config import normalize_engine
    raw = settings.get(FALLBACK)
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    out: list[str] = []
    for item in items:
        name = normalize_engine(item)
        if name and name not in out:
            out.append(name)
    return out
