"""Wires the backup into Archive: settings (Themis), agenda rules (Chronos), notices (Hermes), the Backup panel
(plugin element shown in Archive's settings), the maintenance gate and the endpoints. All through Hub."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests
from sqlalchemy import create_engine

from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.plugin_client import PluginClient, settings_panel
from hestia_common.reminders import reminder_event
from hestia_common.settings_client import SettingsClient, setting

from .. import maintenance, schema
from ..routers.backup import build_router
from .pg import Pg
from .remote import DriveRemote
from .service import BackupService

logger = logging.getLogger("hestia_archive.backup")

HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
TZ = os.getenv("TZ") or "Europe/Rome"
UI_DIST = os.getenv("ARCHIVE_UI_DIST", "/ui/dist")
SERVICE_VERSION = os.getenv("ARCHIVE_SERVICE_VERSION", "1.0.0")

settings = SettingsClient("archive")
settings.declare([
    setting("archive.backup.keep_daily", "Backup recenti da tenere", "int", 3, group="Backup", min=1, max=60,
            unit="giorni", help="Un backup al giorno: quanti degli ultimi restano su Google Drive."),
    setting("archive.backup.keep_monthly", "Backup mensili da tenere", "int", 3, group="Backup", min=0, max=36,
            unit="mesi", help="Oltre ai recenti, il primo backup di ogni mese per questi mesi. 0 = nessuno."),
])

agenda = AgendaClient("archive", HUB_API_URL)


def agenda_rules() -> list[dict]:
    return [
        job_rule("archive.backup", "Backup", service="archive", path="/api/backup/run",
                 recurrence="FREQ=DAILY", start_at="2026-01-01T03:30:00", tz=TZ,
                 description="Copia cifrata di tutti i dati su Google Drive (cartella .hestia)."),
        job_rule("archive.backup_verify", "Verifica backup", service="archive", path="/api/backup/verify",
                 recurrence="FREQ=MONTHLY;BYMONTHDAY=1", start_at="2026-01-01T04:00:00", tz=TZ,
                 description="Ripristina l'ultimo backup in un database di prova e controlla che sia completo."),
    ]


ui = PluginClient("archive", title="Archivio", icon="memory", color="gray", kind="core", dist=UI_DIST,
                  description="Backup su Google Drive: storico, verifica, ripristino.", version=SERVICE_VERSION)
ui.webui(entry="archive.js", api_prefix="/api/backup/",
         settings_panels=[settings_panel("backup", "Backup", element="archive-backup-panel", icon="history",
                                         help="Storico dei backup su Google Drive, verifica e ripristino.")])


def _notify(ev: dict) -> None:
    """Problem notices for Marko via Hermes (generic texts; one live notice per key)."""
    if ev.get("closes"):
        body = {"event_type": "service.action_required", "domain": "system", "entity_id": f"{ev['key']}.ok",
                "payload": {"_message": ev["text"], "_title": ev["title"], "_level": "success", "_source": "archive",
                            "closes": ev["key"], "decision": "resolved", "outcome_text": ev["title"],
                            "service": "archive", "target": "owner"}}
    else:
        body = reminder_event(module="archive", domain="system", key=ev["key"], title=ev["title"], text=ev["text"],
                              actions=ev.get("actions") or [], level=ev.get("level", "warning"))
    try:
        requests.post(f"{HUB_API_URL}/route/hermes/api/events/ingest",
                      json={"method": "POST", "headers": {}, "query": {}, "body": body, "timeout_seconds": 8},
                      timeout=12)
    except Exception as exc:
        logger.warning("[🔄] event=backup_notify_failed key=%s error=%s", ev.get("key"), exc)


def setup(app, engine, database_url: str) -> BackupService | None:
    """Mount gate, endpoints, panel and settings. Not Postgres (tests on SQLite) → only the gate."""
    app.middleware("http")(maintenance.gate.middleware)
    app.include_router(ui.router())
    app.include_router(settings.router())
    try:
        pg = Pg(database_url)
    except Exception:
        logger.info("event=backup_disabled reason=not_postgres")
        return None

    def migrate(dbname: str) -> None:
        other = create_engine(engine.url.set(database=dbname))
        try:
            schema.migrate(other)
        finally:
            other.dispose()

    def before_swap() -> None:
        maintenance.gate.close()
        engine.dispose()

    def after_swap() -> None:
        try:
            engine.dispose()
            schema.migrate(engine)
            maintenance.new_epoch()
        finally:
            maintenance.gate.open()

    remote = DriveRemote(HUB_API_URL)
    service = BackupService(
        pg=pg, remote=remote, workdir=Path(maintenance.BACKUP_DIR),
        passphrase=lambda: os.getenv("HESTIA_BACKUP_PASSPHRASE", ""), setting=settings.get, notify=_notify,
        migrate=migrate, before_swap=before_swap, after_swap=after_swap, tz=TZ)
    app.include_router(build_router(
        service, passphrase_set=lambda: bool(os.getenv("HESTIA_BACKUP_PASSPHRASE", "").strip()),
        drive_status=remote.status,
        settings_view=lambda: {"keep_daily": settings.get("archive.backup.keep_daily", 3),
                               "keep_monthly": settings.get("archive.backup.keep_monthly", 3)}))
    return service


def start() -> None:
    settings.start()
    agenda.register_async(agenda_rules)


def capabilities(base_url: str) -> dict:
    return ui.capabilities(base_url)
