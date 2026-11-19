"""Default menus — DATA ONLY (docs/work/2026-10-23-telegram-from-scratch §5.11, layer 1).

Change the look of Telegram's menus here or, without touching code, in the Themis setting
``telegram.menu.layout`` (same shape, every part optional, later wins). Tools that nothing mentions still appear:
their area comes from the module's ``telegram_group``, else from ``SERVICE_AREAS``, else «Altro».
"""

# Bottom keyboard: door keys (see DOORS).
KEYBOARD = [["oggi", "aree"], ["notifiche", "impostazioni"]]

# The four doors and the words their keyboard buttons send.
DOORS = {
    "oggi": "Today",
    "aree": "Areas",
    "notifiche": "Notifications",
    "impostazioni": "Settings",
}

# The `/` menu (setMyCommands), in this order. Description = what Telegram shows next to the command.
COMMANDS = [
    ("oggi", "Your day"),
    ("aree", "All areas and their actions"),
    ("adesso", "What you need now"),
    ("scopri", "Features you haven't tried yet"),
    ("notifiche", "Notifications to see or answer"),
    ("impostazioni", "Chat, menu and settings"),
    ("nuova", "New conversation"),
    ("voce", "Voice replies on or off"),
    ("stato", "Assistant status"),
    ("aiuto", "How to use it"),
]

# Old command names still typed by habit → new ones.
ALIASES = {
    "start": "home", "help": "aiuto", "comandi": "aree", "menu": "aree", "clear": "nuova", "settings": "impostazioni",
    "set": "impostazioni", "live": "voce_on", "chat": "voce_off", "documents": "documenti",
    "create_event": "create_event", "create_reminder": "nuovo_promemoria", "create_task": "nuova_attivita",
    "notifica_add": "nuovo_avviso", "notifica_get": "notifications_active", "notifica_remove": "notification_off",
    "adesso": "metis_now", "scopri": "metis_discover",
    "webui_revoke": "webui_revoke", "revoke_webui": "webui_revoke", "scout_list": "scout.search",
}

# Areas in order (`aliases`: older or module group names that mean the same area) and, as last resort when a
# tool declares no area, its module's area: one list for every client (hestia_common.areas).
from hestia_common.areas import AREAS, SERVICE_AREAS  # noqa: E402,F401

# Section shown last inside «Tutte le azioni», and sections never shown (used by the client itself).
LAST_SECTION = "Advanced"
HIDDEN_SECTIONS = ["internal"]

# What the «Oggi» card shows (tools rendered one under the other) and its buttons.
TODAY = {"tools": ["agenda_today", "weather_now"], "actions": ["agenda", "create_event", "nuovo_promemoria"]}

# How many primary actions an area card shows before «Tutte le azioni».
PRIMARY_MAX = 6
