"""Default lists of the self care module (SPEC §3): areas, categories, actives, journal metrics, conflict rules.

Lists are data: these are only the seeds. The user adds his own values (kind ``option``) and they merge with
these at read time, so a new area, category or active never needs a code change.
"""
from __future__ import annotations

import re
import unicodedata

AREAS: list[dict] = [
    {"value": "viso", "label": "Viso", "icon": "face"},
    {"value": "occhi", "label": "Occhi", "icon": "eye"},
    {"value": "labbra", "label": "Labbra", "icon": "lips"},
    {"value": "capelli", "label": "Capelli", "icon": "hair"},
    {"value": "cuoio_capelluto", "label": "Cuoio capelluto", "icon": "hair"},
    {"value": "barba", "label": "Barba", "icon": "beard"},
    {"value": "corpo", "label": "Body", "icon": "body"},
    {"value": "mani", "label": "Mani", "icon": "hand"},
    {"value": "piedi", "label": "Piedi", "icon": "foot"},
    {"value": "unghie", "label": "Unghie", "icon": "hand"},
    {"value": "denti", "label": "Denti e bocca", "icon": "tooth"},
    {"value": "profumo", "label": "Profumo", "icon": "drop"},
]

CATEGORIES: list[dict] = [{"value": slug, "label": label, "area": area} for slug, label, area in [
    ("detergente", "Detergente", "viso"), ("struccante", "Struccante", "viso"), ("tonico", "Tonico", "viso"),
    ("esfoliante", "Esfoliante", "viso"), ("siero", "Siero", "viso"), ("trattamento", "Trattamento", "viso"),
    ("crema", "Crema idratante", "viso"), ("contorno_occhi", "Contorno occhi", "occhi"), ("spf", "Protezione solare", "viso"),
    ("maschera", "Maschera", "viso"), ("olio", "Olio", ""), ("balsamo_labbra", "Balsamo labbra", "labbra"),
    ("shampoo", "Shampoo", "capelli"), ("balsamo", "Balsamo", "capelli"), ("maschera_capelli", "Maschera capelli", "capelli"),
    ("styling", "Styling", "capelli"), ("bagnoschiuma", "Bagnoschiuma", "corpo"), ("crema_corpo", "Crema corpo", "corpo"),
    ("deodorante", "Deodorante", "corpo"), ("scrub", "Scrub", "corpo"), ("rasatura", "Rasatura", "barba"),
    ("dopobarba", "Dopobarba", "barba"), ("olio_barba", "Olio barba", "barba"), ("dentifricio", "Dentifricio", "denti"),
    ("collutorio", "Collutorio", "denti"), ("filo", "Filo / scovolino", "denti"), ("profumo", "Profumo", "profumo"),
    ("integratore", "Supplement", ""), ("strumento", "Strumento", ""), ("altro", "Other", ""),
]]

ACTIVES: list[dict] = [{"value": slug, "label": label, "family": family} for slug, label, family in [
    ("retinolo", "Retinolo", "retinoid"), ("retinale", "Retinale", "retinoid"), ("tretinoina", "Tretinoina", "retinoid"),
    ("adapalene", "Adapalene", "retinoid"), ("bakuchiol", "Bakuchiol", ""),
    ("aha_glicolico", "Acido glicolico (AHA)", "aha"), ("aha_lattico", "Acido lattico (AHA)", "aha"),
    ("aha_mandelico", "Acido mandelico (AHA)", "aha"), ("bha_salicilico", "Acido salicilico (BHA)", "bha"),
    ("pha", "PHA (gluconolattone)", "pha"), ("acido_azelaico", "Acido azelaico", ""),
    ("vitamina_c", "Vitamina C (acido ascorbico)", "vitc"), ("benzoile", "Benzoyl peroxide", "bpo"),
    ("niacinamide", "Niacinamide", ""), ("acido_ialuronico", "Acido ialuronico", ""), ("ceramidi", "Ceramidi", ""),
    ("peptidi", "Peptidi", ""), ("pantenolo", "Pantenolo", ""), ("centella", "Centella asiatica", ""),
    ("urea", "Urea", ""), ("zinco", "Zinco", ""), ("spf_filtri", "Filtri solari", "spf"), ("caffeina", "Caffeina", ""),
    ("minoxidil", "Minoxidil", ""), ("ketoconazolo", "Ketoconazolo", ""), ("fluoro", "Fluoro", ""),
]]

# Metrics of the optional journal (1–5 each), per area; "*" applies to any area without its own list.
METRICS: dict[str, list[dict]] = {
    "viso": [{"value": "idratazione", "label": "Idratazione"}, {"value": "brufoli", "label": "Brufoli", "lower_better": True},
             {"value": "rossori", "label": "Rossori", "lower_better": True},
             {"value": "oleosita", "label": "Oiliness", "lower_better": True},
             {"value": "sensibilita", "label": "Sensitivity", "lower_better": True}],
    "capelli": [{"value": "caduta", "label": "Caduta", "lower_better": True},
                {"value": "lucentezza", "label": "Lucentezza"}, {"value": "crespo", "label": "Crespo", "lower_better": True}],
    "cuoio_capelluto": [{"value": "forfora", "label": "Forfora", "lower_better": True},
                        {"value": "prurito", "label": "Prurito", "lower_better": True},
                        {"value": "untuosita", "label": "Greasiness", "lower_better": True}],
    "barba": [{"value": "irritazione", "label": "Irritazione", "lower_better": True},
              {"value": "peli_incarniti", "label": "Peli incarniti", "lower_better": True}],
    "corpo": [{"value": "secchezza", "label": "Secchezza", "lower_better": True},
              {"value": "irritazione", "label": "Irritazione", "lower_better": True}],
    "*": [{"value": "stato", "label": "Stato generale"}],
}

JOURNAL_TAGS = ["ciclo", "stress", "sole", "viaggio", "sport", "dormito poco", "new product", "alimentazione", "malattia"]

# Advisory conflicts between active families (SPEC §4): same day, never blocking. Custom ones are options too.
CONFLICTS: list[dict] = [
    {"a": "retinoid", "b": "aha", "note": "Retinoids and AHA on the same day irritate: alternate them."},
    {"a": "retinoid", "b": "bha", "note": "Retinoids and BHA on the same day irritate: alternate them."},
    {"a": "retinoid", "b": "bpo", "note": "Benzoyl peroxide deactivates retinol: use them on different days."},
    {"a": "retinoid", "b": "vitc", "note": "Vitamin C in the morning, retinoid in the evening, not together."},
    {"a": "vitc", "b": "aha", "note": "Vitamina C e AHA insieme possono irritare."},
    {"a": "vitc", "b": "bpo", "note": "Benzoyl peroxide oxidises vitamin C."},
    {"a": "aha", "b": "bha", "note": "AHA and BHA together: strong exfoliation, better on different days."},
]

SLOTS = {"morning": "Morning", "evening": "Evening", "anytime": "When it happens"}
STATUSES = {"wishlist": "Wish", "stock": "In scorta", "in_use": "In use", "paused": "Paused",
            "finished": "Finished", "discarded": "Thrown away"}
LEVELS = {"full": "Pieno", "3/4": "Tre quarti", "half": "Half", "1/4": "A quarter", "almost_empty": "Quasi finito"}
LEVEL_VALUE = {"full": 1.0, "3/4": 0.75, "half": 0.5, "1/4": 0.25, "almost_empty": 0.08}
VERDICTS = {"repurchase": "I'd buy it again", "maybe": "Forse", "never": "Never again"}
UNITS = ["ml", "g", "pz", "applicazioni"]
CADENCE_MODES = {"daily": "Every day", "fixed_days": "Fixed days", "target": "At least N times",
                 "as_needed": "When it happens"}
PERIODS = {"week": "settimana", "month": "mese"}
EVENT_TYPES = ("bought", "opened", "level_changed", "finished", "discarded", "rated", "replaced", "note", "status")
LISTS = ("areas", "categories", "actives", "metrics", "conflicts", "tags")


def slug(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def product_key(brand: str, name: str) -> str:
    """Same product bought again → same key (lifetime of each bottle, repurchases)."""
    return slug(f"{brand} {name}")[:120]


def families(actives: list[str], options: list[dict] | None = None) -> set[str]:
    """Active slugs → conflict families (retinoid, aha…), custom actives included."""
    fam = {a["value"]: a.get("family") or "" for a in ACTIVES}
    for o in options or []:
        fam.setdefault(o["value"], o.get("family") or "")
    out = set()
    for a in actives:
        f = fam.get(a) or ""
        out.add(f or a)
    return out
