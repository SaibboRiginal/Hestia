"""Argus settings declared to Themis (central settings).

Every tunable of the monitor (poll interval, log source, alert cooldown/batching,
auto-remediation, repair rechecks, Forge proposals, provider auth checks) lives here;
env keeps only secrets and infrastructure (Hub URL, base URL, port, docs path).
All values are read at use time (``settings.get``) → ``apply="live"``, except the
per-container log buffer size (deque allocated once per container).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:  # local run: shared package next to the module
    _shared_pkg = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.settings_client import SettingsClient, setting

POLL_INTERVAL = "argus.poll.interval"
LOG_SOURCE = "argus.logs.source"
HUB_LOG_LIMIT = "argus.logs.hub_limit"
SEEN_CACHE_SIZE = "argus.logs.seen_cache_size"
BUFFER_SIZE = "argus.logs.buffer_size"
BACKFILL_MINUTES = "argus.logs.backfill_minutes"
IGNORE_HEALTH_ACCESS = "argus.logs.ignore_health_access"
IGNORE_PATTERNS = "argus.logs.ignore_patterns"
ALERT_COOLDOWN = "argus.alerts.cooldown"
ALERT_BATCH_WINDOW = "argus.alerts.batch_window"
REMEDIATE_ENABLED = "argus.remediate.enabled"
REMEDIATE_DRY_RUN = "argus.remediate.dry_run"
REMEDIATE_ENVIRONMENT = "argus.remediate.environment"
REMEDIATE_TIMEOUT = "argus.remediate.timeout"
REPAIR_RECHECK = "argus.repair.recheck"
REPAIR_RECHECK_MAX = "argus.repair.recheck_max"
AUTH_CHECK_ENABLED = "argus.auth_check.enabled"
AUTH_CHECK_EVERY = "argus.auth_check.every_cycles"
FORGE_ENABLED = "argus.forge.enabled"
FORGE_THRESHOLD = "argus.forge.threshold"
FORGE_WINDOW = "argus.forge.window"
FORGE_COOLDOWN = "argus.forge.cooldown"

_REMEDIATE_ON = {"key": REMEDIATE_ENABLED, "equals": True}
_AUTH_ON = {"key": AUTH_CHECK_ENABLED, "equals": True}
_FORGE_ON = {"key": FORGE_ENABLED, "equals": True}
_DOCKER = {"key": LOG_SOURCE, "equals": "docker"}

settings = SettingsClient("argus")
settings.declare([
    # ── Controlli ───────────────────────────────────────────────────────────
    setting(POLL_INTERVAL, "Intervallo controlli", "int", 60, group="Controlli", min=10, max=3600, unit="s",
            order=0, help="Ogni quanti secondi controllo salute e log dei moduli. Più basso = avvisi più rapidi."),
    setting(AUTH_CHECK_ENABLED, "Controllo accessi Google/Outlook", "bool", True, group="Controlli", order=1,
            help="Verifica periodicamente che gli account collegati funzionino e ti avvisa se serve "
                 "riautenticarli."),
    setting(AUTH_CHECK_EVERY, "Frequenza controllo accessi", "int", 5, group="Controlli", min=1, max=1440,
            unit="cicli", order=2, depends_on=_AUTH_ON,
            help="Ogni quanti cicli di controllo verifico gli accessi (5 cicli da 60 s = ogni 5 minuti)."),
    # ── Log ─────────────────────────────────────────────────────────────────
    setting(LOG_SOURCE, "Fonte dei log", "enum", "hub", group="Log", advanced=True, order=10,
            options=[("hub", "Hub (consigliato)"), ("docker", "Docker (lettura diretta dei container)")],
            help="Da dove leggo i log dei moduli. Docker richiede l'accesso al socket Docker."),
    setting(HUB_LOG_LIMIT, "Righe di log per modulo", "int", 200, group="Log", min=10, max=5000, advanced=True,
            order=11, help="Quante righe di log (avvisi ed errori) leggo al massimo per modulo a ogni controllo."),
    setting(SEEN_CACHE_SIZE, "Memoria eventi già visti", "int", 5000, group="Log", min=500, max=100000,
            advanced=True, order=12,
            help="Quanti eventi di log ricordo per non avvisarti due volte dello stesso."),
    setting(IGNORE_HEALTH_ACCESS, "Ignora i controlli di salute nei log", "bool", True, group="Log", order=13,
            advanced=True, depends_on=_DOCKER,
            help="Scarta le righe di accesso a /health dei container (solo rumore)."),
    setting(IGNORE_PATTERNS, "Testi da ignorare nei log", "list",
            ["OUTLOOK_CLIENT_ID and OUTLOOK_TENANT_ID must be set"], group="Log", order=14, depends_on=_DOCKER,
            help="Le righe di log che contengono uno di questi testi non generano avvisi."),
    setting(BUFFER_SIZE, "Righe in memoria per container", "int", 500, group="Log", min=50, max=10000,
            advanced=True, apply="restart", order=15, depends_on=_DOCKER,
            help="Quante righe di log tengo in memoria per ogni container."),
    setting(BACKFILL_MINUTES, "Log passati all'avvio", "int", 0, group="Log", min=0, max=1440, unit="min",
            advanced=True, order=16, depends_on=_DOCKER,
            help="Quanti minuti di log precedenti all'avvio rileggo per ogni container (0 = nessuno)."),
    # ── Avvisi ──────────────────────────────────────────────────────────────
    setting(ALERT_COOLDOWN, "Pausa tra avvisi uguali", "int", 60, group="Avvisi", min=1, max=10080, unit="min",
            order=20, help="Dopo un avviso su un modulo, per quanto tempo non te lo ripeto."),
    setting(ALERT_BATCH_WINDOW, "Attesa per raggruppare gli avvisi", "int", 20, group="Avvisi", min=0, max=3600,
            unit="s", order=21,
            help="Aspetto questo tempo senza nuovi problemi prima di mandarti un unico messaggio riassuntivo."),
    # ── Riparazione automatica (safety: the assistant can only read) ───────
    setting(REMEDIATE_ENABLED, "Riparazione automatica", "bool", True, group="Riparazione", oracle="read",
            order=30, help="Quando un modulo si ferma chiedo subito a Hephaestus di ripararlo."),
    setting(REMEDIATE_DRY_RUN, "Solo simulazione", "bool", True, group="Riparazione", oracle="read", order=31,
            depends_on=_REMEDIATE_ON,
            help="Hephaestus prepara la riparazione ma non la esegue davvero."),
    setting(REMEDIATE_ENVIRONMENT, "Ambiente", "enum", "dev", group="Riparazione", oracle="read", order=32,
            options=[("dev", "Sviluppo"), ("staging", "Prova"), ("prod", "Produzione")], advanced=True,
            depends_on=_REMEDIATE_ON, help="Ambiente indicato a Hephaestus nelle richieste di riparazione."),
    setting(REMEDIATE_TIMEOUT, "Attesa risposta riparazione", "int", 15, group="Riparazione", min=1, max=300,
            unit="s", advanced=True, order=33, depends_on=_REMEDIATE_ON,
            help="Quanto aspetto Hephaestus quando gli chiedo una riparazione."),
    setting(REPAIR_RECHECK, "Primo ricontrollo", "int", 10, group="Riparazione", min=1, max=1440, unit="min",
            order=34, help="Dopo quanto ricontrollo un modulo fermo (poi il tempo raddoppia a ogni tentativo)."),
    setting(REPAIR_RECHECK_MAX, "Ricontrollo massimo", "int", 360, group="Riparazione", min=1, max=10080,
            unit="min", order=35, help="Tempo massimo tra due ricontrolli di un modulo che resta fermo."),
    # ── Proposte di correzione a Forge (acts without the user → read only) ─
    setting(FORGE_ENABLED, "Proposte di correzione", "bool", True, group="Proposte di correzione",
            oracle="read", order=40,
            help="Se lo stesso errore si ripete, chiedo a Forge di correggere il codice "
                 "(Forge rispetta i permessi che hai scelto)."),
    setting(FORGE_THRESHOLD, "Ripetizioni prima di proporre", "int", 3, group="Proposte di correzione", min=1,
            max=100, order=41, depends_on=_FORGE_ON,
            help="Quante volte lo stesso errore deve comparire nella finestra prima della proposta."),
    setting(FORGE_WINDOW, "Finestra di conteggio", "int", 3600, group="Proposte di correzione", min=60,
            max=604800, unit="s", order=42, depends_on=_FORGE_ON, advanced=True,
            help="Periodo in cui conto le ripetizioni dello stesso errore."),
    setting(FORGE_COOLDOWN, "Pausa tra proposte uguali", "int", 86400, group="Proposte di correzione", min=60,
            max=2592000, unit="s", order=43, depends_on=_FORGE_ON, advanced=True,
            help="Dopo una proposta per un errore, per quanto tempo non la ripeto."),
]).declare_log_level()


def get_int(key: str, minimum: int | None = None) -> int:
    """Effective int value (bad stored value → default), optionally floored."""
    try:
        value = int(settings.get(key))
    except (TypeError, ValueError):
        value = int(settings._defs[key]["default"])
    return max(minimum, value) if minimum is not None else value


def get_bool(key: str) -> bool:
    value = settings.get(key)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", ""}
    return bool(value)


def get_str(key: str) -> str:
    return str(settings.get(key) or settings._defs[key]["default"]).strip().lower()


def ignore_patterns() -> list[str]:
    raw = settings.get(IGNORE_PATTERNS) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(p).strip().lower() for p in raw if str(p).strip()]
