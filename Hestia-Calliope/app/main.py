"""Hestia-Calliope — real documents («Documenti», port 19027, Cindy 21, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5).

HTML draft → PDF / Word / Excel with three shared themes and a final check; files in Archive blobs, records in
``/api/office-store``; tool ``documento_crea`` for the assistant and Telegram (the file arrives under the card).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body
from fastapi.responses import Response

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common.display import action, display, file, item
from hestia_common.mcp_helpers import MCPTool
from hestia_common.module_kit import ModuleKit
from hestia_common.settings_client import setting
from hestia_common.transfer import StoreSection, Transfer

from .core.render import FORMATS, THEMES
from .core.service import Documents

API = "/api/office"
kit = ModuleKit("calliope", port=19027, api=API, domain="office", title="Documenti", store="office-store",
                when_to_use="creare documenti veri: PDF, Word, Excel (lettere, relazioni, tabelle, riepiloghi)",
                manual="documento_crea: scrivi il contenuto in HTML semplice (h1-h3, p, ul/ol, table con th/td, b, i) "
                       "e scegli format pdf|docx|xlsx (xlsx: ogni tabella diventa un foglio). must_contain = frasi o "
                       "numeri che devono esserci: il file viene ricontrollato prima di consegnarlo.")
app = kit.app
kit.settings.declare([
    setting("calliope.tema", "Stile dei documenti", "enum", "moderno", group="Documenti", order=0,
            options=[(k, v["label"]) for k, v in THEMES.items()],
            help="Lo stile usato quando non ne chiedi uno: Classico, Moderno o Sobrio."),
])
docs = Documents(kit.store, kit.hub, kit.settings.get)


@app.get(API)
def list_documents(limit: int = 30):
    return {"items": docs.list(limit), "themes": {k: v["label"] for k, v in THEMES.items()}, "formats": list(FORMATS)}


@app.post(API)
def create_document(body: dict = Body(...)):
    return docs.create(body.get("title", ""), body.get("html", ""), body.get("format", "pdf"), body.get("theme", ""),
                       body.get("must_contain"))


@app.get(f"{API}/{{did}}")
def get_document(did: str):
    return docs.find(did)


@app.get(f"{API}/{{did}}/file")
def download(did: str):
    d, data = docs.file(did)
    return Response(content=data, media_type=d["mime"],
                    headers={"Content-Disposition": f'attachment; filename="{d["name"]}"'})


@app.delete(f"{API}/{{did}}")
def delete_document(did: str):
    return docs.delete(did)


def _create(title: str, html: str, format: str = "pdf", theme: str = "", must_contain: list | None = None) -> dict:
    out = docs.create(title, html, format, theme, must_contain)
    if not out.get("created"):
        return out
    return {**{k: out[k] for k in ("id", "title", "format", "name", "pages", "size")}, "created": True,
            "display": display(out["title"], subtitle=f"{out['format'].upper()} · {THEMES[out['theme']]['label']}",
                               lines=[f"{out['pages']} {'pagine' if out['format'] == 'pdf' else 'parti'}, "
                                      f"{max(1, out['size'] // 1024)} KB · controllato"],
                               files=[file(out["blob_id"], out["name"], out["mime"])],
                               actions=[action("Elimina", "documento_creato_elimina", {"document": out["id"]})])}


def _list() -> dict:
    rows = docs.list()
    return {"items": [{"id": d["id"], "title": d["title"], "format": d["format"], "created_at": d["created_at"]}
                      for d in rows],
            "display": display("Documenti creati", items=[item(d["title"], [d["format"].upper(), d["created_at"][:10]])
                                                          for d in rows[:20]],
                               lines=[] if rows else ["Nessun documento creato."])}


def _send(document: str) -> dict:
    d = docs.find(document)
    return {"id": d["id"], "title": d["title"],
            "display": display(d["title"], subtitle=d["format"].upper(), files=[file(d["blob_id"], d["name"], d["mime"])])}


S = {"type": "string"}
G = "documenti"
kit.tools([
    MCPTool(name="documento_crea", description="Crea un PDF, Word o Excel: title, html (h1-h3, p, ul/ol/li, "
            "table/tr/th/td, b, i), format pdf|docx|xlsx, theme classico|moderno|sobrio, must_contain (testi che "
            "devono comparire, ricontrollati).",
            parameters={"type": "object", "properties": {
                "title": S, "html": {"type": "string", "description": "contenuto in HTML semplice"},
                "format": {"type": "string", "enum": list(FORMATS)}, "theme": {"type": "string", "enum": list(THEMES)},
                "must_contain": {"type": "array", "items": S}}, "required": ["title", "html"]},
            handler=_create, title="Crea documento", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Documenti", "primary": 1}),
    MCPTool(name="documento_creati", description="I documenti creati di recente.",
            parameters={"type": "object", "properties": {}}, handler=_list, title="Documenti creati",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Documenti", "primary": 2}),
    MCPTool(name="documento_creato_invia", description="Manda di nuovo il file di un documento creato.",
            parameters={"type": "object", "properties": {"document": S}, "required": ["document"]}, handler=_send,
            title="Manda documento", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Documenti"}),
    MCPTool(name="documento_creato_elimina", description="Elimina un documento creato (e il suo file).",
            parameters={"type": "object", "properties": {"document": S}, "required": ["document"]},
            handler=lambda document: docs.delete(document), title="Elimina documento creato", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Documenti"}),
], prefix="documento_")

transfer = Transfer("calliope", kit.hub, sections=[
    StoreSection("documenti", "Documenti creati", kit.store, ["document"], icon="file",
                 title=lambda r: r["data"].get("title", ""), file_fields=["blob_id"]),
])
app.include_router(transfer.router())
kit.capabilities(transfer.capabilities)
kit.finish()
