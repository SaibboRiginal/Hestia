"""Scout settings declared to Themis (central settings).

Replace the old tunable env vars (SCOUT_POLL_INTERVAL_SECONDS, SCOUT_EMAIL_SENDERS,
SCOUT_FILTER_QUERIES, SCOUT_*_BATCH_*, SCOUT_LLM_TIMEOUT_SECONDS, SCOUT_RECONCILE_EVERY_CYCLES,
SCOUT_ENABLE_LISTING_ENRICHMENT, LOG_LEVEL). All live: read at the point of use.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:
    _shared_pkg = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.settings_client import SettingsClient, setting

CYCLE_INTERVAL = "scout.cycle.interval"
MAIL_SENDERS = "scout.mail.senders"
MAIL_FILTER_QUERIES = "scout.mail.filter_queries"
BATCH_MIN_SIZE = "scout.batch.min_size"
BATCH_MAX_SIZE = "scout.batch.max_size"
BATCH_DEBOUNCE = "scout.batch.debounce"
BATCH_COOLDOWN = "scout.batch.cooldown"
LLM_TIMEOUT = "scout.llm.timeout"
RECONCILE_EVERY_CYCLES = "scout.reconcile.every_cycles"
ENRICHMENT_ENABLED = "scout.enrichment.enabled"

DEFAULT_SENDERS = ["nonrispondere@idealista.it", "noreply@notifiche.immobiliare.it"]

settings = SettingsClient("scout")
settings.declare([
    setting(CYCLE_INTERVAL, "Intervallo controllo email annunci", "int", 1800, group="Controllo email",
            min=60, max=86400, unit="s", order=0,
            help="Ogni quanto Scout legge le nuove email degli annunci. È la ricorrenza predefinita del "
                 "lavoro in agenda (se l'hai modificato dall'agenda vale la tua modifica)."),
    setting(MAIL_SENDERS, "Mittenti degli annunci", "list", list(DEFAULT_SENDERS), group="Controllo email",
            order=1,
            help="Indirizzi dei portali immobiliari da cui leggere le email. Ignorati se imposti "
                 "le ricerche email personalizzate."),
    setting(MAIL_FILTER_QUERIES, "Ricerche email personalizzate", "list", [], group="Controllo email",
            order=2, advanced=True,
            help="Ricerche email esplicite (una per riga, es. FROM \"indirizzo\"). Se vuoto si usano i mittenti."),
    setting(BATCH_MIN_SIZE, "Email minime per partire", "int", 1, group="Estrazione annunci", min=1, max=50,
            order=10, advanced=True,
            help="Scout aspetta di avere almeno queste email nuove prima di estrarre gli annunci."),
    setting(BATCH_MAX_SIZE, "Email per chiamata al modello", "int", 5, group="Estrazione annunci", min=1, max=50,
            order=11, advanced=True,
            help="Quante email manda insieme al modello. Più alto = meno chiamate ma più lunghe."),
    setting(BATCH_DEBOUNCE, "Attesa per raccogliere email", "int", 45, group="Estrazione annunci", min=0, max=600,
            unit="s", order=12, advanced=True,
            help="Prima di estrarre aspetta un attimo per raccogliere email arrivate quasi insieme (0 = subito)."),
    setting(BATCH_COOLDOWN, "Pausa tra un gruppo e l'altro", "int", 15, group="Estrazione annunci", min=0,
            max=600, unit="s", order=13, advanced=True,
            help="Pausa tra due chiamate al modello, per non superare i limiti di quota."),
    setting(LLM_TIMEOUT, "Tempo massimo estrazione", "int", 120, group="Estrazione annunci", min=10, max=900,
            unit="s", order=14, advanced=True,
            help="Quanto aspettare la risposta del modello per un gruppo di email prima di provare il successivo."),
    setting(RECONCILE_EVERY_CYCLES, "Riconciliazione ogni N cicli", "int", 1, group="Manutenzione dati",
            min=0, max=100, order=20, advanced=True,
            help="Ogni quanti cicli Scout ricontrolla gli immobili salvati (posizione, date, link). 0 = mai."),
    setting(ENRICHMENT_ENABLED, "Arricchisci dalla pagina dell'annuncio", "bool", True, group="Manutenzione dati",
            order=21,
            help="Apre la pagina dell'annuncio per completare descrizione e indirizzo e riprova quelli rimasti a metà."),
]).declare_log_level()


def _as_list(value, sep: str) -> list[str]:
    items = value.split(sep) if isinstance(value, str) else (value or [])
    return [str(i).strip() for i in items if str(i).strip()]


def target_filters() -> list[str]:
    """Mail search queries: explicit ones, else built from the sender list."""
    explicit = _as_list(settings.get(MAIL_FILTER_QUERIES), "||")
    if explicit:
        return explicit
    senders = _as_list(settings.get(MAIL_SENDERS), ",")
    return [f'FROM "{sender}"' for sender in senders]


def get_int(key: str, floor: int | None = None) -> int:
    """Integer setting, clamped to ``floor``; bad value → declared default."""
    try:
        value = int(settings.get(key))
    except (TypeError, ValueError):
        value = int(settings._defs[key]["default"])
    return max(floor, value) if floor is not None else value
