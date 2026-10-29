"""Default menus — DATA ONLY (docs/work/2026-10-23-telegram-da-zero §5.11, layer 1).

Change the look of Telegram's menus here or, without touching code, in the Themis setting
``telegram.menu.layout`` (same shape, every part optional, later wins). Tools that nothing mentions still appear:
their area comes from the module's ``telegram_group``, else from ``SERVICE_AREAS``, else «Altro».
"""

# Bottom keyboard: door keys (see DOORS).
KEYBOARD = [["oggi", "aree"], ["notifiche", "impostazioni"]]

# The four doors and the words their keyboard buttons send.
DOORS = {
    "oggi": "Oggi",
    "aree": "Aree",
    "notifiche": "Notifiche",
    "impostazioni": "Impostazioni",
}

# The `/` menu (setMyCommands), in this order. Description = what Telegram shows next to the command.
COMMANDS = [
    ("oggi", "La tua giornata"),
    ("aree", "Tutte le aree e le loro azioni"),
    ("adesso", "Cosa ti serve adesso"),
    ("scopri", "Funzioni che non hai ancora provato"),
    ("notifiche", "Notifiche da vedere o rispondere"),
    ("impostazioni", "Chat, menu e impostazioni"),
    ("nuova", "Nuova conversazione"),
    ("voce", "Risposte a voce sì o no"),
    ("stato", "Stato dell'assistente"),
    ("aiuto", "Come si usa"),
]

# Old command names still typed by habit → new ones.
ALIASES = {
    "start": "home", "help": "aiuto", "comandi": "aree", "menu": "aree", "clear": "nuova", "settings": "impostazioni",
    "set": "impostazioni", "live": "voce_on", "chat": "voce_off", "documents": "documenti",
    "create_event": "create_event", "create_reminder": "nuovo_promemoria", "create_task": "nuova_attivita",
    "notifica_add": "nuovo_avviso", "notifica_get": "notifiche_attive", "notifica_remove": "notifica_disattiva",
    "adesso": "metis_adesso", "scopri": "metis_scopri",
    "webui_revoke": "webui_revoke", "revoke_webui": "webui_revoke", "scout_list": "scout_listings",
}

# Areas in order (`aliases`: older or module group names that mean the same area) and, as last resort when a
# tool declares no area, its module's area: one list for every client (hestia_common.areas).
from hestia_common.areas import AREAS, SERVICE_AREAS  # noqa: E402,F401

# Section shown last inside «Tutte le azioni», and sections never shown (used by the client itself).
LAST_SECTION = "Avanzate"
HIDDEN_SECTIONS = ["interno"]

# What the «Oggi» card shows (tools rendered one under the other) and its buttons.
TODAY = {"tools": ["agenda_today", "weather_now"], "actions": ["agenda", "create_event", "nuovo_promemoria"]}

# How many primary actions an area card shows before «Tutte le azioni».
PRIMARY_MAX = 6
