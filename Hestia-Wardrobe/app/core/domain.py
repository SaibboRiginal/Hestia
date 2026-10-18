"""Wardrobe data model (SPEC §4): validation and normalisation of pieces, outfits, wears, collections, vocabularies.

Archive stores rows as JSON; everything about their meaning lives here. Labels are Italian (they reach the user).
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any


class Invalid(ValueError):
    """Bad input from a caller (422)."""


def new_id() -> str:
    return uuid.uuid4().hex


KINDS = {"garment": "Capo", "shoes": "Scarpe", "accessory": "Accessorio"}
SEASONS = {"spring": "Primavera", "summer": "Estate", "autumn": "Autunno", "winter": "Inverno"}
STATUSES = {"active": "Nell'armadio", "laundry": "In lavanderia", "lent": "Prestato", "stored": "Messo via",
            "to_repair": "Da riparare", "to_donate": "Da donare", "donated": "Donato", "sold": "Venduto",
            "wishlist": "Desiderato", "archived": "Archiviato"}
WEARABLE = {"active"}                         # what suggestions may use
OWNED = set(STATUSES) - {"wishlist", "donated", "sold", "archived"}
CONDITIONS = {"new": "Nuovo", "good": "Buono", "worn": "Usurato", "to_repair": "Da riparare"}
SLOTS = {"base": "Strato base", "top": "Sopra", "mid": "Strato intermedio", "outer": "Capospalla",
         "bottom": "Sotto", "onepiece": "Pezzo unico", "shoes": "Scarpe", "accessory": "Accessori"}
SLOT_ORDER = list(SLOTS)
COLLECTION_TYPES = {"capsule": "Capsule", "packing": "Valigia", "shopping": "Da comprare", "custom": "Lista"}

# ── default vocabularies (seeded once, then the user's) ─────────────────────
# category: key, label, kind, parent (subcategory), slot (default outfit slot), warmth/formality hints
_C = lambda key, label, kind, slot, parent="", warmth=None, formality=None: {  # noqa: E731
    "key": key, "label": label, "kind": kind, "slot": slot, "parent": parent,
    **({"warmth": warmth} if warmth else {}), **({"formality": formality} if formality else {})}

DEFAULT_CATEGORIES = [
    _C("top", "Parte sopra", "garment", "top"),
    _C("tshirt", "T-shirt", "garment", "top", "top", 1, 1), _C("shirt", "Camicia", "garment", "top", "top", 2, 3),
    _C("polo", "Polo", "garment", "top", "top", 1, 2), _C("tank", "Canotta", "garment", "base", "top", 1, 1),
    _C("sweater", "Maglione", "garment", "mid", "top", 4, 3), _C("hoodie", "Felpa", "garment", "mid", "top", 3, 1),
    _C("cardigan", "Cardigan", "garment", "mid", "top", 3, 3), _C("longsleeve", "Maglia a maniche lunghe", "garment", "top", "top", 2, 2),
    _C("bottom", "Parte sotto", "garment", "bottom"),
    _C("jeans", "Jeans", "garment", "bottom", "bottom", 3, 2), _C("trousers", "Pantaloni", "garment", "bottom", "bottom", 3, 3),
    _C("chinos", "Chino", "garment", "bottom", "bottom", 2, 3), _C("shorts", "Pantaloncini", "garment", "bottom", "bottom", 1, 1),
    _C("joggers", "Pantaloni tuta", "garment", "bottom", "bottom", 2, 1), _C("skirt", "Gonna", "garment", "bottom", "bottom", 2, 3),
    _C("outerwear", "Capospalla", "garment", "outer"),
    _C("jacket", "Giacca", "garment", "outer", "outerwear", 3, 3), _C("blazer", "Blazer", "garment", "outer", "outerwear", 2, 4),
    _C("coat", "Cappotto", "garment", "outer", "outerwear", 5, 4), _C("puffer", "Piumino", "garment", "outer", "outerwear", 5, 1),
    _C("raincoat", "Impermeabile", "garment", "outer", "outerwear", 2, 2), _C("vest", "Gilet", "garment", "mid", "outerwear", 3, 3),
    _C("onepiece", "Pezzo unico", "garment", "onepiece"),
    _C("dress", "Vestito", "garment", "onepiece", "onepiece", 2, 4), _C("suit", "Completo", "garment", "onepiece", "onepiece", 3, 5),
    _C("jumpsuit", "Tuta intera", "garment", "onepiece", "onepiece", 2, 2),
    _C("underwear", "Intimo e calze", "garment", "base"), _C("socks", "Calze", "garment", "base", "underwear", 1, 1),
    _C("sport", "Sport", "garment", "top"), _C("sleepwear", "Pigiama", "garment", "top"), _C("swimwear", "Costume", "garment", "bottom"),
    _C("shoes", "Scarpe", "shoes", "shoes"),
    _C("sneakers", "Sneakers", "shoes", "shoes", "shoes", 2, 1), _C("dress_shoes", "Scarpe eleganti", "shoes", "shoes", "shoes", 2, 5),
    _C("loafers", "Mocassini", "shoes", "shoes", "shoes", 2, 4), _C("boots", "Stivali", "shoes", "shoes", "shoes", 4, 3),
    _C("sandals", "Sandali", "shoes", "shoes", "shoes", 1, 1), _C("running", "Scarpe sportive", "shoes", "shoes", "shoes", 2, 1),
    _C("slippers", "Ciabatte", "shoes", "shoes", "shoes", 1, 1),
    _C("accessory", "Accessori", "accessory", "accessory"),
    *[_C(k, label, "accessory", "accessory", "accessory") for k, label in [
        ("bag", "Borsa"), ("backpack", "Zaino"), ("belt", "Cintura"), ("watch", "Orologio"), ("jewelry", "Gioielli"),
        ("glasses", "Occhiali"), ("sunglasses", "Occhiali da sole"), ("hat", "Cappello"), ("beanie", "Berretto"),
        ("scarf", "Sciarpa"), ("gloves", "Guanti"), ("tie", "Cravatta"), ("wallet", "Portafoglio"), ("other_acc", "Altro")]],
]

DEFAULT_VOCABULARIES: dict[str, list[dict]] = {
    "category": DEFAULT_CATEGORIES,
    "style": [{"key": k, "label": v} for k, v in [
        ("casual", "Casual"), ("smart_casual", "Smart casual"), ("formal", "Elegante"), ("business", "Business"),
        ("sport", "Sportivo"), ("streetwear", "Streetwear"), ("minimal", "Minimal"), ("vintage", "Vintage"),
        ("outdoor", "Outdoor"), ("home", "Da casa")]],
    "occasion": [{"key": k, "label": v} for k, v in [
        ("work", "Lavoro"), ("office", "Ufficio"), ("evening", "Sera"), ("date", "Appuntamento"), ("travel", "Viaggio"),
        ("home", "Casa"), ("sport", "Sport"), ("ceremony", "Cerimonia"), ("weekend", "Weekend"), ("party", "Festa")]],
    "pattern": [{"key": k, "label": v} for k, v in [
        ("plain", "Tinta unita"), ("striped", "A righe"), ("checked", "A quadri"), ("printed", "Stampato"),
        ("floral", "Floreale"), ("dotted", "A pois"), ("camo", "Mimetico"), ("logo", "Con logo"), ("textured", "Lavorato")]],
    "fit": [{"key": k, "label": v} for k, v in [
        ("slim", "Slim"), ("regular", "Regolare"), ("relaxed", "Comodo"), ("oversize", "Oversize"), ("tailored", "Sartoriale")]],
    "location": [{"key": k, "label": v} for k, v in [
        ("wardrobe", "Armadio"), ("drawer", "Cassetto"), ("shoe_rack", "Scarpiera"), ("storage", "Scatola / cantina"),
        ("other_house", "Altra casa"), ("suitcase", "In valigia")]],
    "color": [{"key": k, "label": v, "hex": h} for k, v, h in [
        ("black", "Nero", "#111111"), ("white", "Bianco", "#f5f5f5"), ("grey", "Grigio", "#8a8a8a"),
        ("navy", "Blu navy", "#1f2a44"), ("blue", "Blu", "#2f5fb3"), ("light_blue", "Azzurro", "#8fb8e8"),
        ("beige", "Beige", "#d8c3a0"), ("brown", "Marrone", "#6b4423"), ("camel", "Cammello", "#b8875a"),
        ("green", "Verde", "#3c7a3c"), ("olive", "Verde oliva", "#6b6b2f"), ("red", "Rosso", "#c0392b"),
        ("burgundy", "Bordeaux", "#6d1f2c"), ("pink", "Rosa", "#e8a0b4"), ("orange", "Arancione", "#e67e22"),
        ("yellow", "Giallo", "#f1c40f"), ("purple", "Viola", "#7d3c98"), ("denim", "Denim", "#4a6a8a"),
        ("cream", "Panna", "#efe6d0"), ("gold", "Oro", "#c9a227"), ("silver", "Argento", "#c0c0c0")]],
}

NEUTRAL_COLORS = {"black", "white", "grey", "navy", "beige", "brown", "camel", "cream", "denim", "silver", "gold"}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


# ── helpers ─────────────────────────────────────────────────────────────────
def _text(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _keys(value: Any, allowed: dict | set | None = None, limit: int = 30) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[,;]", value)]
    out: list[str] = []
    for v in value:
        k = slug(v)
        if not k or k in out:
            continue
        if allowed is not None and k not in allowed:
            raise Invalid(f"valore '{v}' non valido (ammessi: {', '.join(sorted(allowed))})")
        out.append(k)
    return out[:limit]


def slug(value: Any) -> str:
    s = str(value or "").strip().lower()
    s = (s.replace("à", "a").replace("è", "e").replace("é", "e").replace("ì", "i").replace("ò", "o").replace("ù", "u"))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


def _int(value: Any, lo: int, hi: int, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        n = int(round(float(str(value).replace(",", "."))))
    except ValueError:
        raise Invalid(f"numero non valido: {value!r}")
    return max(lo, min(hi, n))


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(str(value).replace(",", ".").replace("€", "").strip()), 2)
    except ValueError:
        raise Invalid(f"numero non valido: {value!r}")


def iso_date(value: Any, *, required: bool = False) -> str | None:
    if value in (None, ""):
        if required:
            raise Invalid("data mancante")
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()[:10]
    if not _DATE.match(s):
        raise Invalid(f"data non valida: {value!r} (formato AAAA-MM-GG)")
    try:
        date.fromisoformat(s)
    except ValueError:
        raise Invalid(f"data non valida: {value!r}")
    return s


def _weather(value: Any) -> dict:
    v = value if isinstance(value, dict) else {}
    out: dict[str, Any] = {}
    for k in ("min_c", "max_c"):
        if v.get(k) not in (None, ""):
            out[k] = _int(v[k], -40, 50)
    if "rain_ok" in v:
        out["rain_ok"] = bool(v["rain_ok"])
    return out


def colors(value: Any, vocab: dict[str, dict] | None = None) -> list[dict]:
    """``["navy", "white"]`` or ``[{name, hex, share}]`` → ``[{key, name, hex, share}]`` (primary first)."""
    if not value:
        return []
    if isinstance(value, str):
        value = [c for c in re.split(r"[,;/]| e ", value) if c.strip()]
    vocab = vocab or {}
    by_label = {slug(v.get("label")): k for k, v in vocab.items()}
    out = []
    for c in value[:6]:
        if isinstance(c, dict):
            name, hexv, share = c.get("name") or c.get("key") or c.get("label"), c.get("hex"), c.get("share")
        else:
            name, hexv, share = c, None, None
        key = slug(name)
        key = key if key in vocab else by_label.get(key, key)
        if not key:
            continue
        hexv = hexv if hexv and _HEX.match(str(hexv)) else (vocab.get(key) or {}).get("hex")
        out.append({"key": key, "name": (vocab.get(key) or {}).get("label") or _text(name, 40),
                    **({"hex": hexv} if hexv else {}), **({"share": _int(share, 0, 100)} if share not in (None, "") else {})})
    return out


# ── pieces ──────────────────────────────────────────────────────────────────
def piece(data: dict, categories: dict[str, dict], color_vocab: dict[str, dict] | None = None) -> dict:
    """Normalise a piece (garment, shoes or accessory). Only ``name`` and ``category`` are required."""
    name = _text(data.get("name"), 120)
    if not name:
        raise Invalid("il nome del capo è obbligatorio")
    cat_key = slug(data.get("category") or data.get("subcategory"))
    cat = categories.get(cat_key)
    if not cat:
        by_label = {slug(c["label"]): c for c in categories.values()}
        cat = by_label.get(cat_key)
    if not cat:
        raise Invalid(f"categoria '{data.get('category')}' sconosciuta")
    sub_key = slug(data.get("subcategory")) if data.get("subcategory") else ""
    if cat.get("parent"):                     # a subcategory was given as category
        sub_key, cat = cat["key"], categories.get(cat["parent"], cat)
    sub = categories.get(sub_key) if sub_key else None
    kind = slug(data.get("kind")) or (sub or cat).get("kind") or "garment"
    if kind not in KINDS:
        raise Invalid(f"tipo '{kind}' non valido")
    hint = sub or cat
    status = slug(data.get("status")) or "active"
    if status not in STATUSES:
        raise Invalid(f"stato '{status}' non valido")
    condition = slug(data.get("condition")) or "good"
    if condition not in CONDITIONS:
        condition = "good"
    purchase = data.get("purchase") if isinstance(data.get("purchase"), dict) else {}
    care = data.get("care") if isinstance(data.get("care"), dict) else {}
    materials = []
    for m in (data.get("materials") or [])[:6]:
        if isinstance(m, dict) and _text(m.get("name"), 40):
            materials.append({"name": _text(m["name"], 40).lower(), **({"percent": _int(m.get("percent"), 0, 100)}
                                                                      if m.get("percent") not in (None, "") else {})})
        elif isinstance(m, str) and m.strip():
            materials.append({"name": m.strip().lower()[:40]})
    return {
        "kind": kind, "name": name, "category": cat["key"], "subcategory": sub["key"] if sub else "",
        "brand": _text(data.get("brand"), 60), "model": _text(data.get("model"), 80),
        "colors": colors(data.get("colors"), color_vocab), "pattern": slug(data.get("pattern")) or "",
        "materials": materials, "size": _text(data.get("size"), 20), "fit": slug(data.get("fit")) or "",
        "seasons": _keys(data.get("seasons"), SEASONS) or list(SEASONS),
        "styles": _keys(data.get("styles")), "occasions": _keys(data.get("occasions")),
        "warmth": _int(data.get("warmth"), 1, 5, hint.get("warmth") or 3),
        "formality": _int(data.get("formality"), 1, 5, hint.get("formality") or 3),
        "weather": _weather(data.get("weather")),
        "condition": condition, "status": status, "location": slug(data.get("location")) or "",
        "care": {k: care[k] for k in ("wash_c", "machine", "dry_clean", "iron", "notes") if k in care},
        "purchase": {"date": iso_date(purchase.get("date")), "price": _float(purchase.get("price")),
                     "currency": _text(purchase.get("currency"), 3).upper() or None, "store": _text(purchase.get("store"), 60),
                     "gift": bool(purchase.get("gift"))},
        "photos": [str(p) for p in (data.get("photos") or []) if p][:12],
        "favorite": bool(data.get("favorite")), "tags": _keys(data.get("tags")),
        "notes": _text(data.get("notes"), 2000),
        "last_worn_manual": iso_date(data.get("last_worn_manual")),
    }


# ── outfits ─────────────────────────────────────────────────────────────────
def outfit(data: dict, pieces: dict[str, dict]) -> dict:
    name = _text(data.get("name"), 120)
    slots = []
    for s in data.get("slots") or []:
        pid = str((s or {}).get("piece_id") or "")
        if not pid:
            continue
        if pid not in pieces:
            raise Invalid(f"capo {pid} non trovato")
        slot = slug(s.get("slot")) or "top"
        if slot not in SLOTS:
            raise Invalid(f"posizione '{slot}' non valida")
        slots.append({"slot": slot, "piece_id": pid})
    for pid in data.get("piece_ids") or []:          # shortcut: pieces without slot → their category's slot
        if pid in pieces and pid not in {s["piece_id"] for s in slots}:
            slots.append({"slot": pieces[pid].get("_slot") or "top", "piece_id": pid})
    if not slots:
        raise Invalid("un outfit ha bisogno di almeno un capo")
    slots.sort(key=lambda s: SLOT_ORDER.index(s["slot"]))
    if not name:
        name = " + ".join(pieces[s["piece_id"]]["name"] for s in slots[:3])[:120]
    seasons = _keys(data.get("seasons"), SEASONS)
    if not seasons:                                   # default: seasons every piece supports
        common = set(SEASONS)
        for s in slots:
            common &= set(pieces[s["piece_id"]].get("seasons") or SEASONS)
        seasons = [k for k in SEASONS if k in common] or list(SEASONS)
    return {"name": name, "slots": slots, "styles": _keys(data.get("styles")), "occasions": _keys(data.get("occasions")),
            "seasons": seasons, "weather": _weather(data.get("weather")),
            "rating": _int(data.get("rating"), 1, 5), "favorite": bool(data.get("favorite")),
            "photos": [str(p) for p in (data.get("photos") or []) if p][:12],
            "board": data.get("board") if isinstance(data.get("board"), dict) else {},
            "source": "assistant" if data.get("source") == "assistant" else "user",
            "status": "archived" if data.get("status") == "archived" else "active",
            "notes": _text(data.get("notes"), 2000)}


# ── wears ("Indossato" marks) ───────────────────────────────────────────────
def wear(data: dict, pieces: dict[str, dict], outfits: dict[str, dict], today: date) -> dict:
    oid = str(data.get("outfit_id") or "") or None
    if oid and oid not in outfits:
        raise Invalid("outfit non trovato")
    pids = [str(p) for p in (data.get("piece_ids") or []) if p]
    for p in pids:
        if p not in pieces:
            raise Invalid(f"capo {p} non trovato")
    if oid and not pids:
        pids = [s["piece_id"] for s in outfits[oid].get("slots") or []]
    if not pids:
        raise Invalid("indica un outfit o almeno un capo")
    day = iso_date(data.get("date")) or today.isoformat()
    if day > today.isoformat():
        raise Invalid("non si può segnare un giorno futuro")
    w = data.get("weather") if isinstance(data.get("weather"), dict) else {}
    return {"date": day, "outfit_id": oid, "piece_ids": list(dict.fromkeys(pids)),
            "occasion": slug(data.get("occasion")) or "", "rating": _int(data.get("rating"), 1, 5),
            "weather": {k: w[k] for k in ("temp_c", "condition") if k in w},
            "notes": _text(data.get("note") or data.get("notes"), 500),
            "source": data.get("source") if data.get("source") in ("webui", "telegram", "assistant", "reminder") else "webui"}


# ── collections ─────────────────────────────────────────────────────────────
def collection(data: dict, pieces: dict[str, dict], outfits: dict[str, dict]) -> dict:
    name = _text(data.get("name"), 120)
    if not name:
        raise Invalid("il nome della lista è obbligatorio")
    ctype = slug(data.get("type")) or "custom"
    if ctype not in COLLECTION_TYPES:
        raise Invalid(f"tipo di lista '{ctype}' non valido")
    pids = [p for p in dict.fromkeys(str(x) for x in data.get("piece_ids") or []) if p in pieces]
    oids = [o for o in dict.fromkeys(str(x) for x in data.get("outfit_ids") or []) if o in outfits]
    trip = data.get("trip") if isinstance(data.get("trip"), dict) else {}
    items = []                                  # free-text lines ("caricabatterie") for packing lists
    for it in data.get("items") or []:
        label = _text(it.get("label") if isinstance(it, dict) else it, 80)
        if label:
            items.append({"id": (it.get("id") if isinstance(it, dict) else None) or new_id()[:8], "label": label})
    valid = set(pids) | set(oids) | {i["id"] for i in items}
    return {"name": name, "type": ctype, "piece_ids": pids, "outfit_ids": oids, "items": items,
            "checked": [c for c in dict.fromkeys(str(x) for x in data.get("checked") or []) if c in valid],
            "trip": {"from": iso_date(trip.get("from")), "to": iso_date(trip.get("to")), "place": _text(trip.get("place"), 80)},
            "notes": _text(data.get("notes"), 2000), "archived": bool(data.get("archived"))}


# ── vocabularies ────────────────────────────────────────────────────────────
def vocabulary(name: str, values: list[dict]) -> list[dict]:
    if name not in DEFAULT_VOCABULARIES:
        raise Invalid(f"vocabolario '{name}' sconosciuto")
    out, seen = [], set()
    for i, v in enumerate(values or []):
        if not isinstance(v, dict):
            v = {"label": str(v)}
        label = _text(v.get("label"), 60)
        key = slug(v.get("key") or label)
        if not key or key in seen:
            continue
        seen.add(key)
        item = {"key": key, "label": label or key, "order": int(v.get("order", i)), "hidden": bool(v.get("hidden"))}
        if name == "category":
            kind = slug(v.get("kind")) or "garment"
            item.update({"kind": kind if kind in KINDS else "garment", "slot": slug(v.get("slot")) if slug(v.get("slot")) in SLOTS else "top",
                         "parent": slug(v.get("parent"))})
            for k in ("warmth", "formality"):
                if v.get(k):
                    item[k] = _int(v[k], 1, 5)
        if name == "color" and v.get("hex") and _HEX.match(str(v["hex"])):
            item["hex"] = str(v["hex"]).lower()
        out.append(item)
    return out
