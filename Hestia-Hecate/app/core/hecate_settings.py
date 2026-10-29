"""Hecate settings declared to Themis (central settings).

Env keeps only secrets (OAuth client ids/secrets/tokens), infrastructure (URLs, token/tunnel files)
and credential-bound deployment choices (provider enable flags, OAuth flow mode/scopes).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:  # local run outside the container: use the workspace copy
    _shared = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.settings_client import SettingsClient, setting

CALENDAR_BACKFILL_DAYS = "hecate.calendar.backfill_days"
ARCHIVE_ROUTE_TIMEOUT = "hecate.archive.route_timeout"
CALENDAR_WRITE_TIMEOUT = "hecate.archive.calendar_write_timeout"
AUTH_RECHECK_INTERVAL = "hecate.auth.recheck_interval"
ACTION_NOTIFY_COOLDOWN = "hecate.auth.notify_cooldown"
MAIL_WATCH_INTERVAL = "hecate.mail.watch_interval"
MAIL_SAFETY_INTERVAL = "hecate.mail.safety_interval"
WEATHER_CACHE_MINUTES = "hecate.weather.cache_minutes"
PERSONAL_PLACES = "themis.personal.places"
PHONE_HOME_WIFI = "hecate.telefono.wifi_casa"
PHONE_APPS = "hecate.telefono.app"

settings = SettingsClient("hecate")
settings.declare([
    setting(CALENDAR_BACKFILL_DAYS, "Giorni passati da sincronizzare", "int", 7, group="Calendario",
            min=0, max=365, unit="giorni",
            help="Quanti giorni indietro leggo dai calendari (Google/Outlook) a ogni sincronizzazione. "
                 "Più giorni = più eventi passati importati, sincronizzazione più lenta."),
    setting(ARCHIVE_ROUTE_TIMEOUT, "Attesa salvataggio dati", "int", 8, group="Archivio",
            min=1, max=120, unit="s", advanced=True,
            help="Quanti secondi aspetto l'Archivio quando salvo un dato. Se è lento, aumentalo."),
    setting(CALENDAR_WRITE_TIMEOUT, "Attesa salvataggio eventi", "int", 10, group="Archivio",
            min=1, max=120, unit="s", advanced=True,
            help="Quanti secondi aspetto l'Archivio quando salvo un evento del calendario."),
    setting(AUTH_RECHECK_INTERVAL, "Controllo accessi account", "int", 3600, group="Account",
            min=0, max=86400, unit="s",
            help="Ogni quanti secondi ricontrollo che Google/Outlook siano ancora collegati e, se no, "
                 "ti avviso di nuovo. 0 = solo all'avvio."),
    setting(ACTION_NOTIFY_COOLDOWN, "Pausa tra avvisi uguali", "int", 300, group="Account",
            min=0, max=86400, unit="s", advanced=True,
            help="Tempo minimo tra due avvisi uguali (es. 'ricollega Google'), per non ricevere doppioni."),
    setting(MAIL_WATCH_INTERVAL, "Controllo nuove email", "int", 900, group="Email", min=60, max=86400,
            unit="s",
            help="Ogni quanto guardo se sono arrivate email nuove (un solo controllo leggero per tutta Hestia: "
                 "poi Iris le passa ai moduli interessati). È la ricorrenza predefinita del lavoro in agenda."),
    setting(MAIL_SAFETY_INTERVAL, "Controllo di sicurezza con Gmail push", "int", 21600, group="Email",
            min=300, max=86400, unit="s", advanced=True,
            help="Quando le notifiche push di Gmail (Pub/Sub) sono attive, il controllo periodico serve solo "
                 "da rete di sicurezza e passa a questo intervallo."),
    setting(WEATHER_CACHE_MINUTES, "Validità della previsione meteo", "int", 30, group="Meteo", min=5, max=360,
            unit="min", advanced=True,
            help="Per quanti minuti riuso la previsione già scaricata per un luogo prima di chiederla di nuovo "
                 "(il servizio meteo aggiorna i dati circa ogni ora)."),
    setting(PHONE_HOME_WIFI, "Wi-Fi di casa", "list", [], group="Telefono",
            help="Nomi delle reti Wi-Fi di casa: quando il telefono è connesso a una di queste sei «a casa». "
                 "Vuoto = il telefono deve dirlo da solo (campo home)."),
    setting(PHONE_APPS, "App da ascoltare", "list", [], group="Telefono",
            help="Le notifiche di queste app (es. la banca, Satispay) passano ai moduli che le usano, come le spese. "
                 "Vuoto = tutte quelle che il telefono manda."),
]).declare_log_level().follow_personal()
