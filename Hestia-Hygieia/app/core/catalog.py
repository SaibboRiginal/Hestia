"""Default lists of the self care module (SPEC §3): areas, categories, actives, journal metrics, conflict rules.

Lists are data: these are only the seeds. The user adds his own values (kind ``option``) and they merge with
these at read time, so a new area, category or active never needs a code change.
"""
from __future__ import annotations

import re
import unicodedata

AREAS: list[dict] = [
    {"value": "viso", "label": "Face", "icon": "face"},
    {"value": "occhi", "label": "Eyes", "icon": "eye"},
    {"value": "labbra", "label": "Lips", "icon": "lips"},
    {"value": "capelli", "label": "Hair", "icon": "hair"},
    {"value": "scalp", "label": "Scalp", "icon": "hair"},
    {"value": "barba", "label": "Beard", "icon": "beard"},
    {"value": "corpo", "label": "Body", "icon": "body"},
    {"value": "mani", "label": "Hands", "icon": "hand"},
    {"value": "piedi", "label": "Feet", "icon": "foot"},
    {"value": "unghie", "label": "Nails", "icon": "hand"},
    {"value": "denti", "label": "Teeth and mouth", "icon": "tooth"},
    {"value": "profumo", "label": "Perfume", "icon": "drop"},
]

CATEGORIES: list[dict] = [{"value": slug, "label": label, "area": area} for slug, label, area in [
    ("detergente", "Cleanser", "viso"), ("struccante", "Make-up remover", "viso"), ("tonico", "Toner", "viso"),
    ("esfoliante", "Exfoliant", "viso"), ("siero", "Serum", "viso"), ("trattamento", "Treatment", "viso"),
    ("crema", "Moisturiser", "viso"), ("eye_contour", "Eye cream", "occhi"), ("spf", "Sunscreen", "viso"),
    ("maschera", "Mask", "viso"), ("olio", "Oil", ""), ("lip_balm", "Lip balm", "labbra"),
    ("shampoo", "Shampoo", "capelli"), ("balsamo", "Conditioner", "capelli"), ("hair_mask", "Hair mask", "capelli"),
    ("styling", "Styling", "capelli"), ("bagnoschiuma", "Shower gel", "corpo"), ("body_cream", "Body cream", "corpo"),
    ("deodorante", "Deodorant", "corpo"), ("scrub", "Scrub", "corpo"), ("rasatura", "Shaving", "barba"),
    ("dopobarba", "Aftershave", "barba"), ("beard_oil", "Beard oil", "barba"), ("dentifricio", "Toothpaste", "denti"),
    ("collutorio", "Mouthwash", "denti"), ("filo", "Floss / interdental brush", "denti"), ("profumo", "Perfume", "profumo"),
    ("integratore", "Supplement", ""), ("strumento", "Tool", ""), ("altro", "Other", ""),
]]

ACTIVES: list[dict] = [{"value": slug, "label": label, "family": family} for slug, label, family in [
    ("retinolo", "Retinol", "retinoid"), ("retinale", "Retinal", "retinoid"), ("tretinoina", "Tretinoin", "retinoid"),
    ("adapalene", "Adapalene", "retinoid"), ("bakuchiol", "Bakuchiol", ""),
    ("aha_glycolic", "Glycolic acid (AHA)", "aha"), ("aha_lactic", "Lactic acid (AHA)", "aha"),
    ("aha_mandelic", "Mandelic acid (AHA)", "aha"), ("bha_salicylic", "Salicylic acid (BHA)", "bha"),
    ("pha", "PHA (gluconolactone)", "pha"), ("azelaic_acid", "Azelaic acid", ""),
    ("vitamin_c", "Vitamin C (ascorbic acid)", "vitc"), ("benzoile", "Benzoyl peroxide", "bpo"),
    ("niacinamide", "Niacinamide", ""), ("hyaluronic_acid", "Hyaluronic acid", ""), ("ceramidi", "Ceramides", ""),
    ("peptidi", "Peptides", ""), ("pantenolo", "Panthenol", ""), ("centella", "Centella asiatica", ""),
    ("urea", "Urea", ""), ("zinco", "Zinc", ""), ("spf_filters", "Sunscreen filters", "spf"), ("caffeina", "Caffeine", ""),
    ("minoxidil", "Minoxidil", ""), ("ketoconazolo", "Ketoconazole", ""), ("fluoro", "Fluoride", ""),
]]

# Metrics of the optional journal (1–5 each), per area; "*" applies to any area without its own list.
METRICS: dict[str, list[dict]] = {
    "viso": [{"value": "idratazione", "label": "Hydration"}, {"value": "brufoli", "label": "Spots", "lower_better": True},
             {"value": "rossori", "label": "Redness", "lower_better": True},
             {"value": "oleosita", "label": "Oiliness", "lower_better": True},
             {"value": "sensibilita", "label": "Sensitivity", "lower_better": True}],
    "capelli": [{"value": "caduta", "label": "Hair loss", "lower_better": True},
                {"value": "lucentezza", "label": "Shine"}, {"value": "crespo", "label": "Frizz", "lower_better": True}],
    "scalp": [{"value": "forfora", "label": "Dandruff", "lower_better": True},
                        {"value": "prurito", "label": "Itching", "lower_better": True},
                        {"value": "untuosita", "label": "Greasiness", "lower_better": True}],
    "barba": [{"value": "irritazione", "label": "Irritation", "lower_better": True},
              {"value": "ingrown_hairs", "label": "Ingrown hairs", "lower_better": True}],
    "corpo": [{"value": "secchezza", "label": "Dryness", "lower_better": True},
              {"value": "irritazione", "label": "Irritation", "lower_better": True}],
    "*": [{"value": "stato", "label": "General state"}],
}

JOURNAL_TAGS = ["ciclo", "stress", "sole", "viaggio", "sport", "dormito poco", "new product", "alimentazione", "malattia"]

# Advisory conflicts between active families (SPEC §4): same day, never blocking. Custom ones are options too.
CONFLICTS: list[dict] = [
    {"a": "retinoid", "b": "aha", "note": "Retinoids and AHA on the same day irritate: alternate them."},
    {"a": "retinoid", "b": "bha", "note": "Retinoids and BHA on the same day irritate: alternate them."},
    {"a": "retinoid", "b": "bpo", "note": "Benzoyl peroxide deactivates retinol: use them on different days."},
    {"a": "retinoid", "b": "vitc", "note": "Vitamin C in the morning, retinoid in the evening, not together."},
    {"a": "vitc", "b": "aha", "note": "Vitamin C and AHA together can irritate."},
    {"a": "vitc", "b": "bpo", "note": "Benzoyl peroxide oxidises vitamin C."},
    {"a": "aha", "b": "bha", "note": "AHA and BHA together: strong exfoliation, better on different days."},
]

SLOTS = {"morning": "Morning", "evening": "Evening", "anytime": "When it happens"}
STATUSES = {"wishlist": "Wish", "stock": "In stock", "in_use": "In use", "paused": "Paused",
            "finished": "Finished", "discarded": "Thrown away"}
LEVELS = {"full": "Full", "3/4": "Three quarters", "half": "Half", "1/4": "A quarter", "almost_empty": "Almost empty"}
LEVEL_VALUE = {"full": 1.0, "3/4": 0.75, "half": 0.5, "1/4": 0.25, "almost_empty": 0.08}
VERDICTS = {"repurchase": "I'd buy it again", "maybe": "Maybe", "never": "Never again"}
UNITS = ["ml", "g", "pcs", "applications"]
CADENCE_MODES = {"daily": "Every day", "fixed_days": "Fixed days", "target": "At least N times",
                 "as_needed": "When it happens"}
PERIODS = {"week": "week", "month": "month"}
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
