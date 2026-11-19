"""Default lists of the self care module (SPEC §3): areas, categories, actives, journal metrics, conflict rules.

Lists are data: these are only the seeds. The user adds his own values (kind ``option``) and they merge with
these at read time, so a new area, category or active never needs a code change.
"""
from __future__ import annotations

import re
import unicodedata

AREAS: list[dict] = [
    {"value": "face", "label": "Face", "icon": "face"},
    {"value": "eyes", "label": "Eyes", "icon": "eye"},
    {"value": "lips", "label": "Lips", "icon": "lips"},
    {"value": "hair", "label": "Hair", "icon": "hair"},
    {"value": "scalp", "label": "Scalp", "icon": "hair"},
    {"value": "beard", "label": "Beard", "icon": "beard"},
    {"value": "body", "label": "Body", "icon": "body"},
    {"value": "hands", "label": "Hands", "icon": "hand"},
    {"value": "feet", "label": "Feet", "icon": "foot"},
    {"value": "nails", "label": "Nails", "icon": "hand"},
    {"value": "teeth", "label": "Teeth and mouth", "icon": "tooth"},
    {"value": "perfume", "label": "Perfume", "icon": "drop"},
]

CATEGORIES: list[dict] = [{"value": slug, "label": label, "area": area} for slug, label, area in [
    ("cleanser", "Cleanser", "face"), ("makeup_remover", "Make-up remover", "face"), ("toner", "Toner", "face"),
    ("exfoliant", "Exfoliant", "face"), ("serum", "Serum", "face"), ("treatment", "Treatment", "face"),
    ("cream", "Moisturiser", "face"), ("eye_contour", "Eye cream", "eyes"), ("spf", "Sunscreen", "face"),
    ("mask", "Mask", "face"), ("oil", "Oil", ""), ("lip_balm", "Lip balm", "lips"),
    ("shampoo", "Shampoo", "hair"), ("conditioner", "Conditioner", "hair"), ("hair_mask", "Hair mask", "hair"),
    ("styling", "Styling", "hair"), ("body_wash", "Shower gel", "body"), ("body_cream", "Body cream", "body"),
    ("deodorant", "Deodorant", "body"), ("scrub", "Scrub", "body"), ("shaving", "Shaving", "beard"),
    ("aftershave", "Aftershave", "beard"), ("beard_oil", "Beard oil", "beard"), ("toothpaste", "Toothpaste", "teeth"),
    ("mouthwash", "Mouthwash", "teeth"), ("floss", "Floss / interdental brush", "teeth"), ("perfume", "Perfume", "perfume"),
    ("supplement", "Supplement", ""), ("tool", "Tool", ""), ("other", "Other", ""),
]]

ACTIVES: list[dict] = [{"value": slug, "label": label, "family": family} for slug, label, family in [
    ("retinol", "Retinol", "retinoid"), ("retinal", "Retinal", "retinoid"), ("tretinoin", "Tretinoin", "retinoid"),
    ("adapalene", "Adapalene", "retinoid"), ("bakuchiol", "Bakuchiol", ""),
    ("aha_glycolic", "Glycolic acid (AHA)", "aha"), ("aha_lactic", "Lactic acid (AHA)", "aha"),
    ("aha_mandelic", "Mandelic acid (AHA)", "aha"), ("bha_salicylic", "Salicylic acid (BHA)", "bha"),
    ("pha", "PHA (gluconolactone)", "pha"), ("azelaic_acid", "Azelaic acid", ""),
    ("vitamin_c", "Vitamin C (ascorbic acid)", "vitc"), ("benzoyl", "Benzoyl peroxide", "bpo"),
    ("niacinamide", "Niacinamide", ""), ("hyaluronic_acid", "Hyaluronic acid", ""), ("ceramides", "Ceramides", ""),
    ("peptides", "Peptides", ""), ("panthenol", "Panthenol", ""), ("centella", "Centella asiatica", ""),
    ("urea", "Urea", ""), ("zinc", "Zinc", ""), ("spf_filters", "Sunscreen filters", "spf"), ("caffeine", "Caffeine", ""),
    ("minoxidil", "Minoxidil", ""), ("ketoconazole", "Ketoconazole", ""), ("fluoride", "Fluoride", ""),
]]

# Metrics of the optional journal (1–5 each), per area; "*" applies to any area without its own list.
METRICS: dict[str, list[dict]] = {
    "face": [{"value": "hydration", "label": "Hydration"}, {"value": "pimples", "label": "Spots", "lower_better": True},
             {"value": "redness", "label": "Redness", "lower_better": True},
             {"value": "oiliness", "label": "Oiliness", "lower_better": True},
             {"value": "sensitivity", "label": "Sensitivity", "lower_better": True}],
    "hair": [{"value": "hair_loss", "label": "Hair loss", "lower_better": True},
                {"value": "shine", "label": "Shine"}, {"value": "frizz", "label": "Frizz", "lower_better": True}],
    "scalp": [{"value": "dandruff", "label": "Dandruff", "lower_better": True},
                        {"value": "itch", "label": "Itching", "lower_better": True},
                        {"value": "greasiness", "label": "Greasiness", "lower_better": True}],
    "beard": [{"value": "irritation", "label": "Irritation", "lower_better": True},
              {"value": "ingrown_hairs", "label": "Ingrown hairs", "lower_better": True}],
    "body": [{"value": "dryness", "label": "Dryness", "lower_better": True},
              {"value": "irritation", "label": "Irritation", "lower_better": True}],
    "*": [{"value": "status", "label": "General state"}],
}

JOURNAL_TAGS = ["cycle", "stress", "sun", "trip", "sport", "little_sleep", "new product", "nutrition", "illness"]

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
