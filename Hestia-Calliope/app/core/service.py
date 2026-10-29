"""Calliope — real documents («Documenti», Cindy 21, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5).

The assistant writes a small HTML draft; Calliope turns it into PDF, Word or Excel with one of three shared themes,
opens the result again to check it (pages/sheets, the title, every «must contain» text), keeps the file in Archive
blobs and the record in ``office-store``. A failed check is said plainly and nothing half-made is kept.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso

from .parse import parse
from .render import FORMATS, THEMES, RenderError, check, render

logger = logging.getLogger("hestia_calliope.service")
MAX_HTML = 200_000


def filename(title: str, ext: str) -> str:
    slug = re.sub(r"[^\w\- ]+", "", title, flags=re.U).strip().replace(" ", "-")[:60] or "documento"
    return f"{slug}.{ext}"


class Documents:
    def __init__(self, store, hub, get=lambda k, d=None: d):
        self.store = store
        self.hub = hub
        self.get = get

    def create(self, title: str, html: str, fmt: str = "pdf", theme: str = "", must_contain: Any = None) -> dict:
        title = str(title or "").strip()[:120]
        if not title:
            raise Invalid("serve un titolo")
        fmt = str(fmt or "pdf").lower().lstrip(".")
        if fmt not in FORMATS:
            raise Invalid("formato: pdf, docx o xlsx")
        if len(html or "") > MAX_HTML:
            raise Invalid("testo troppo lungo")
        theme = theme if theme in THEMES else (self.get("calliope.tema", "moderno") or "moderno")
        must = [must_contain] if isinstance(must_contain, str) else list(must_contain or [])
        blocks = parse(html)
        if not blocks:
            raise Invalid("il testo del documento è vuoto")
        try:
            data = render(fmt, blocks, title, theme)
        except RenderError as exc:
            raise Invalid(str(exc)) from None
        verdict = check(fmt, data, title, [str(m)[:200] for m in must][:20])
        if not verdict["ok"]:
            logger.warning("event=calliope_check_failed format=%s missing=%d", fmt, len(verdict["missing"]))
            return {"created": False, "check": verdict,
                    "error": "il documento non ha passato il controllo: manca " + "; ".join(verdict["missing"][:5])}
        mime, ext = FORMATS[fmt]
        name = filename(title, ext)
        meta = self.hub.ok("archive", "POST", "api/blobs", body={
            "owner_module": "calliope", "content_type": mime, "data_base64": base64.b64encode(data).decode(),
            "meta": {"name": name, "kind": "document"}}, timeout=30) or {}
        if not meta.get("blob_id"):
            raise Invalid("non riesco a salvare il file, riprova tra poco")
        did = new_id("doc")
        rec = {"title": title, "format": fmt, "theme": theme, "name": name, "mime": mime, "blob_id": meta["blob_id"],
               "size": len(data), "pages": verdict["pages"], "check": verdict, "created_at": now_iso()}
        self.store.upsert("document", did, rec, ref_id=meta["blob_id"])
        logger.info("event=calliope_document_created format=%s theme=%s pages=%d size=%d", fmt, theme,
                    verdict["pages"], len(data))
        return {"created": True, **rec, "id": did}

    def list(self, limit: int = 30) -> list[dict]:
        self.store.refresh()
        return sorted(self.store.items("document"), key=lambda d: d.get("created_at") or "", reverse=True)[:limit]

    def find(self, did: str) -> dict:
        self.store.refresh()
        d = self.store.data("document", did)
        if not d:
            raise NotFound("documento non trovato")
        return d

    def file(self, did: str) -> tuple[dict, bytes]:
        d = self.find(did)
        blob = self.hub.ok("archive", "GET", f"api/blobs/{d['blob_id']}/base64", timeout=30) or {}
        return d, base64.b64decode(blob.get("data_b64") or "")

    def delete(self, did: str) -> dict:
        d = self.find(did)
        try:
            self.hub.ok("archive", "DELETE", f"api/blobs/{d['blob_id']}", timeout=10)
        except Exception as exc:
            logger.warning("[🔄] event=calliope_blob_delete_failed error=%s fallback=orphan_blob", exc)
        self.store.delete("document", did)
        return {"deleted": True, "title": d["title"]}
