"""Athena settings declared to Themis (central settings)."""
from __future__ import annotations

from .shared_imports import import_shared_symbol

SettingsClient = import_shared_symbol("hestia_common.settings_client", "SettingsClient")
setting = import_shared_symbol("hestia_common.settings_client", "setting")

PROPOSALS_PER_DAY = "athena.settings.proposals_per_day"

settings = SettingsClient("athena")
settings.declare([
    setting(PROPOSALS_PER_DAY, "Proposte di impostazioni al giorno", "int", 2, group="Proposte", min=0, max=10,
            help="Quante modifiche alle impostazioni Athena può proporti al giorno (0 = nessuna). "
                 "Ogni proposta aspetta sempre la tua conferma."),
]).declare_log_level()
