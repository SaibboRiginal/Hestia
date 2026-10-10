"""Hermes settings declared to Themis (central settings).

Env keeps only infrastructure (Hub/Archive URLs, base URL, version, Hub registration
plumbing, startup wait). Every tunable below is read at use time (``apply="live"``).
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

DELIVERY_MAX_ATTEMPTS = "hermes.delivery.max_attempts"
DELIVERY_RETRY_INTERVAL = "hermes.delivery.retry_interval"
DEDUPE_RECURRING_MAX_AGE = "hermes.dedupe.recurring_max_age"
DEDUPE_RECURRING_TYPES = "hermes.dedupe.recurring_types"
BATCH_WINDOW = "hermes.batch.window"
BATCH_MAX_ATTEMPTS = "hermes.batch.max_attempts"
RETRACT_AFTER = "hermes.retract.after"

settings = SettingsClient("hermes")
settings.declare([
    setting(DELIVERY_MAX_ATTEMPTS, "Tentativi di consegna per client", "int", 6, group="Consegna",
            min=1, max=50,
            help="Quante volte provo a consegnare una notifica a un client (Telegram, WebUI) prima di "
                 "rinunciare per quel client."),
    setting(DELIVERY_RETRY_INTERVAL, "Intervallo tra i tentativi", "int", 120, group="Consegna",
            min=15, max=3600, unit="s", advanced=True,
            help="Ogni quanto riprovo le consegne fallite."),
    setting(DEDUPE_RECURRING_MAX_AGE, "Ripeti avvisi ricorrenti dopo", "int", 3600, group="Anti-duplicati",
            min=60, max=86400, unit="s",
            help="Un avviso ricorrente (es. modulo in errore) già inviato non viene ripetuto prima di "
                 "questo tempo; dopo, se il problema persiste, ti riavviso."),
    setting(DEDUPE_RECURRING_TYPES, "Tipi di avviso ricorrenti", "list",
            ["service.action_required", "service.health"], group="Anti-duplicati", advanced=True,
            help="Tipi di evento a cui si applica la ripetizione a tempo; gli altri non vengono mai ripetuti."),
    setting(BATCH_WINDOW, "Attesa per raggruppare annunci", "int", 30, group="Raggruppamento",
            min=5, max=1800, unit="s",
            help="Dopo un nuovo annuncio aspetto questo tempo senza novità e poi ti mando un unico "
                 "messaggio con tutti quelli arrivati."),
    setting(BATCH_MAX_ATTEMPTS, "Tentativi per un gruppo di annunci", "int", 6, group="Raggruppamento",
            min=1, max=20, advanced=True,
            help="Quante volte riprovo a inviare un gruppo di annunci (con attesa crescente) prima di rinunciare."),
    setting(RETRACT_AFTER, "Togli dalla chat le notifiche gestite dopo", "int", 6, group="Pulizia",
            min=1, max=46, unit="h",
            help="Le notifiche già viste o gestite spariscono dalla chat Telegram dopo questo tempo "
                 "(restano nell'elenco della WebUI). Telegram permette di cancellarle solo entro 48 h."),
]).declare_log_level()


def recurring_event_types() -> frozenset[str]:
    raw = settings.get(DEDUPE_RECURRING_TYPES) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return frozenset(str(e).strip() for e in raw if str(e).strip())
