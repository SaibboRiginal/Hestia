"""Photos (SPEC §4.6): orientation fixed, metadata (GPS) stripped, two thumbnails; bytes live in Archive blobs.

A ``photo`` row in the wardrobe store groups the three blobs ``{original, medium, thumb}`` of one picture.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging

logger = logging.getLogger("hestia_wardrobe.photos")

SIZES = {"medium": 768, "thumb": 256}
ACCEPTED = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif", "image/gif", "image/bmp"}


class PhotoError(ValueError):
    pass


def decode(upload: dict, max_mb: float) -> tuple[bytes, str]:
    """``{name, mime, data_b64}`` (plugin contract upload) → raw bytes + mime."""
    if not isinstance(upload, dict):
        raise PhotoError("foto mancante")
    mime = str(upload.get("mime") or upload.get("content_type") or "").split(";")[0].strip().lower()
    raw64 = str(upload.get("data_b64") or upload.get("data_base64") or "")
    if raw64.startswith("data:") and "," in raw64:
        header, raw64 = raw64.split(",", 1)
        mime = mime or header[5:].split(";")[0].lower()
    if mime and mime not in ACCEPTED:
        raise PhotoError(f"formato {mime} non supportato")
    try:
        raw = base64.b64decode(raw64, validate=False)
    except (binascii.Error, ValueError):
        raise PhotoError("foto non leggibile")
    if not raw:
        raise PhotoError("foto vuota")
    if len(raw) > max_mb * 1024 * 1024:
        raise PhotoError(f"foto più grande di {max_mb:g} MB")
    return raw, mime or "image/jpeg"


def process(raw: bytes) -> dict:
    """Return ``{original: (bytes, mime), medium: …, thumb: …, width, height}``. Re-encoding drops EXIF/GPS."""
    try:
        from PIL import Image, ImageOps
    except ModuleNotFoundError:                      # tests / no Pillow: keep the bytes as they are
        logger.warning("[🔄] event=wardrobe_photo_pillow_missing fallback=original_only")
        return {"original": (raw, "image/jpeg"), "medium": (raw, "image/jpeg"), "thumb": (raw, "image/jpeg"),
                "width": None, "height": None}
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise PhotoError(f"immagine non valida: {exc}")
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    out = {"width": img.width, "height": img.height}
    buf = io.BytesIO()
    if has_alpha:                                      # cut-outs (future outfit board) keep transparency
        img.save(buf, "WEBP", quality=90)
        out["original"] = (buf.getvalue(), "image/webp")
    else:
        img.save(buf, "JPEG", quality=90, optimize=True)
        out["original"] = (buf.getvalue(), "image/jpeg")
    for name, side in SIZES.items():
        copy = img.copy()
        copy.thumbnail((side, side))
        b = io.BytesIO()
        copy.save(b, "WEBP", quality=80 if name == "medium" else 72)
        out[name] = (b.getvalue(), "image/webp")
    return out
