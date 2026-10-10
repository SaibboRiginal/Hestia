"""Forge settings declared to Themis (central settings).

Default engine and permission modes replace ``HEPHAESTUS_FORGE_ENGINE`` and the
``default_engine``/``modes`` keys of ``data/forge/settings.json`` (which keeps only the
Claude Pro schedule/state). All live: Forge applies them through ``on_change``.
"""
from __future__ import annotations

from ..core.shared_imports import import_shared_symbol

SettingsClient = import_shared_symbol("hestia_common.settings_client", "SettingsClient")
setting = import_shared_symbol("hestia_common.settings_client", "setting")

ENGINE = "hephaestus.forge.engine"
MODE = {"local": "hephaestus.forge.mode.local", "cloud": "hephaestus.forge.mode.cloud"}

_ENGINES = [("local", "Locale (Ollama)"), ("cloud", "Cloud (Gemini)"), ("claude", "Claude Code")]
_MODES = [("ask", "Chiedi sempre"), ("auto", "Sviluppa da solo, il merge chiede"),
          ("full_auto", "Tutto da solo se i test passano")]

settings = SettingsClient("hephaestus")
settings.declare([
    setting(ENGINE, "Motore di sviluppo predefinito", "enum", "local", group="Sviluppo (Forge)",
            options=_ENGINES, order=0,
            help="Chi scrive il codice quando chiedi una modifica. Se non è disponibile si usa il successivo."),
    # Safety switches: the assistant can read them but never propose a change.
    setting(MODE["local"], "Permessi · motore locale", "enum", "auto", group="Sviluppo (Forge)",
            options=_MODES, order=1, oracle="read",
            help="Quanta autonomia ha Forge quando usa il modello locale (gratis)."),
    setting(MODE["cloud"], "Permessi · cloud e Claude", "enum", "ask", group="Sviluppo (Forge)",
            options=_MODES, order=2, oracle="read",
            help="Quanta autonomia ha Forge quando usa motori a pagamento o a consumo."),
]).declare_log_level()
