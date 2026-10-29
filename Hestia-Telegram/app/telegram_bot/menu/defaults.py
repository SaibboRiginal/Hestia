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
    "webui_revoke": "webui_revoke", "revoke_webui": "webui_revoke", "scout_list": "scout_listings",
}

# Areas in order. `aliases`: older or module group names that mean the same area.
AREAS = [
    {"key": "giornata", "label": "Giornata", "emoji": "📅", "order": 10,
     "aliases": ["pianificazione", "agenda", "calendario", "chat", "meteo"]},
    {"key": "scadenze", "label": "Scadenze", "emoji": "⏳", "order": 15, "aliases": ["deadlines", "kairos"]},
    {"key": "allenamento", "label": "Allenamento", "emoji": "🏋️", "order": 20, "aliases": ["fitness", "palestra"]},
    {"key": "alimentazione", "label": "Alimentazione", "emoji": "🥗", "order": 25,
     "aliases": ["cibo", "food", "dieta", "demeter"]},
    {"key": "selfcare", "label": "Cura di sé", "emoji": "✨", "order": 30, "aliases": ["self care", "hygieia"]},
    {"key": "persone", "label": "Persone", "emoji": "👥", "order": 35, "aliases": ["people", "hera"]},
    {"key": "guardaroba", "label": "Guardaroba", "emoji": "👕", "order": 40, "aliases": ["wardrobe"]},
    {"key": "spese", "label": "Spese", "emoji": "💶", "order": 50, "aliases": ["finanze", "soldi"]},
    {"key": "case", "label": "Immobili", "emoji": "🏠", "order": 60, "aliases": ["immobiliare", "case in vendita"]},
    {"key": "casa", "label": "Casa", "emoji": "💡", "order": 65, "aliases": ["home", "domotica", "lares"]},
    {"key": "posta", "label": "Posta", "emoji": "✉️", "order": 70, "aliases": ["email", "mail"]},
    {"key": "memoria", "label": "Memoria", "emoji": "🧠", "order": 80,
     "aliases": ["preferenze", "web", "ricerca"]},
    {"key": "documenti", "label": "Documenti", "emoji": "📄", "order": 82, "aliases": ["documents", "calliope"]},
    {"key": "notifiche", "label": "Notifiche", "emoji": "🔔", "order": 85, "aliases": ["avvisi"]},
    {"key": "sviluppo", "label": "Sviluppo", "emoji": "🛠", "order": 90, "aliases": ["forge"]},
    {"key": "aspetto", "label": "Immagini e aspetto", "emoji": "🎨", "order": 95,
     "aliases": ["immagini", "images", "appearance", "apollo", "aphrodite"]},
    {"key": "sistema", "label": "Sistema", "emoji": "⚙️", "order": 100,
     "aliases": ["impostazioni", "webui", "🌐 webui", "salute"]},
    {"key": "altro", "label": "Altro", "emoji": "•", "order": 999, "aliases": []},
]

# Last resort when a tool declares no area: its module.
SERVICE_AREAS = {
    "chronos": "giornata", "hecate": "giornata", "athena": "giornata", "hercules": "allenamento",
    "hygieia": "selfcare", "wardrobe": "guardaroba", "plutus": "spese", "scout": "case", "iris": "posta",
    "oracle": "memoria", "atlas": "memoria", "archive": "memoria", "hephaestus": "sviluppo", "metis": "sviluppo",
    "argus": "sistema", "themis": "sistema", "hub": "sistema", "mcp": "sistema", "echo": "sistema",
    "hermes": "notifiche", "telegram": "sistema", "webui": "sistema", "apollo": "aspetto", "aphrodite": "aspetto",
    "lares": "casa", "hera": "persone", "demeter": "alimentazione", "calliope": "documenti", "kairos": "scadenze",
}

# Section shown last inside «Tutte le azioni», and sections never shown (used by the client itself).
LAST_SECTION = "Avanzate"
HIDDEN_SECTIONS = ["interno"]

# What the «Oggi» card shows (tools rendered one under the other) and its buttons.
TODAY = {"tools": ["agenda_today", "weather_now"], "actions": ["agenda", "create_event", "nuovo_promemoria"]}

# How many primary actions an area card shows before «Tutte le azioni».
PRIMARY_MAX = 6
