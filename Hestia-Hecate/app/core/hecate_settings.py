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
]).declare_log_level()
