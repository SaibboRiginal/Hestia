"""Default menus — DATA ONLY (docs/work/2026-10-23-telegram-da-zero §5.11, layer 1).

Change the look of Telegram's menus here or, without touching code, in the Themis setting
``telegram.menu.layout`` (same shape, every part optional, later wins). Tools that nothing mentions still appear:
their area comes from the module's ``telegram_group``, else from ``SERVICE_AREAS``, else «Altro».
"""

# Bottom keyboard: door keys (see DOORS).
KEYBOARD = [["today", "areas"], ["notifications", "settings"]]

# The four doors and the words their keyboard buttons send.
DOORS = {
    "today": "Today",
    "areas": "Areas",
    "notifications": "Notifications",
    "settings": "Settings",
}

# The `/` menu (setMyCommands), in this order. Description = what Telegram shows next to the command.
COMMANDS = [
    ("today", "Your day"),
    ("areas", "All areas and their actions"),
    ("now", "What you need now"),
    ("discover", "Features you haven't tried yet"),
    ("notifications", "Notifications to see or answer"),
    ("settings", "Chat, menu and settings"),
    ("new", "New conversation"),
    ("voice", "Voice replies on or off"),
    ("status", "Assistant status"),
    ("aiuto", "How to use it"),
]

# Old command names still typed by habit → new ones.
ALIASES = {
    "start": "home", "help": "aiuto", "commands": "areas", "menu": "areas", "clear": "new", "settings": "settings",
    "set": "settings", "live": "voice_on", "chat": "voice_off", "documents": "documents",
    "create_event": "create_event", "create_reminder": "new_reminder", "create_task": "new_activity",
    "notification_add": "new_alert", "notification_get": "notifications_active", "notification_remove": "notification_disable",
    "now": "metis_now", "discover": "metis_discover",
    "webui_revoke": "webui_revoke", "revoke_webui": "webui_revoke", "scout_list": "scout.search",
}

# Areas in order (`aliases`: older or module group names that mean the same area) and, as last resort when a
# tool declares no area, its module's area: one list for every client (hestia_common.areas).
from hestia_common.areas import AREAS, SERVICE_AREAS  # noqa: E402,F401

# Section shown last inside «Tutte le azioni», and sections never shown (used by the client itself).
LAST_SECTION = "Advanced"
HIDDEN_SECTIONS = ["interno"]

# What the «Oggi» card shows (tools rendered one under the other) and its buttons.
TODAY = {"tools": ["agenda_today", "weather_now"], "actions": ["agenda", "create_event", "new_reminder"]}

# How many primary actions an area card shows before «Tutte le azioni».
PRIMARY_MAX = 6
