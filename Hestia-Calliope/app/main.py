"""Hestia-Calliope — real documents («Documenti», port 19027, Cindy 21, dossier docs/work/2026-10-24-whole-brainstorm-cindy W5).

HTML draft → PDF / Word / Excel with three shared themes and a final check; files in Archive blobs, records in
``/api/office-store``; tool ``document_create`` for the assistant and Telegram (the file arrives under the card).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body
from fastapi.responses import Response
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common.display import action, display, file, item
from hestia_common.mcp_helpers import MCPTool
from hestia_common.plugin_client import page
from hestia_common.module_kit import ModuleKit
from hestia_common.settings_client import setting
from hestia_common.transfer import StoreSection, Transfer

from .core.render import FORMATS, THEMES
from .core.service import Documents

API = "/api/office"
kit = ModuleKit("calliope", port=19027, api=API, domain="office", title="Documents", store="office-store",
                when_to_use="create real documents: PDF, Word, Excel (letters, reports, tables, summaries)",
                manual="document_create: write the content in simple HTML (h1-h3, p, ul/ol, table with th/td, b, i) and pick format pdf|docx|xlsx (xlsx: each table becomes a sheet). must_contain = phrases or numbers that must be there: the file is checked again before delivery.")
app = kit.app
kit.settings.declare([
    setting("calliope.tema", "Document style", "enum", "moderno", group="Documents", order=0,
            options=[(k, v["label"]) for k, v in THEMES.items()],
            help="The style used when you don't ask for one: Classic, Modern or Sober."),
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


@app.get(f"{API}/{{did}}/b64")
def download_b64(did: str):
    """The file as base64 for the WebUI plugin (its calls go through Hub as JSON)."""
    import base64
    d, data = docs.file(did)
    return {"name": d["name"], "mime": d["mime"], "data_b64": base64.b64encode(data).decode()}


@app.delete(f"{API}/{{did}}")
def delete_document(did: str):
    return docs.delete(did)


def _create(title: str, html: str, format: str = "pdf", theme: str = "", must_contain: list | None = None) -> dict:
    out = docs.create(title, html, format, theme, must_contain)
    if not out.get("created"):
        return out
    return {**{k: out[k] for k in ("id", "title", "format", "name", "pages", "size")}, "created": True,
            "display": display(out["title"], subtitle=f"{out['format'].upper()} · {THEMES[out['theme']]['label']}",
                               lines=[tr("{0} pages, {1} KB · checked", out['pages'], max(1, out['size'] // 1024)) if out['format'] == 'pdf'
                                     else tr("{0} parts, {1} KB · checked", out['pages'], max(1, out['size'] // 1024))],
                               files=[file(out["blob_id"], out["name"], out["mime"])],
                               actions=[action(tr("Delete"), "document_delete", {"document": out["id"]})])}


def _list() -> dict:
    rows = docs.list()
    return {"items": [{"id": d["id"], "title": d["title"], "format": d["format"], "created_at": d["created_at"]}
                      for d in rows],
            "display": display(tr("Documents created"), items=[item(d["title"], [d["format"].upper(), d["created_at"][:10]])
                                                          for d in rows[:20]],
                               lines=[] if rows else [tr("No document created.")])}


def _send(document: str) -> dict:
    d = docs.find(document)
    return {"id": d["id"], "title": d["title"],
            "display": display(d["title"], subtitle=d["format"].upper(), files=[file(d["blob_id"], d["name"], d["mime"])])}


S = {"type": "string"}
G = "documents"
kit.tools([
    MCPTool(name="document_create", description=("Create a PDF, Word or Excel file: title, html (h1-h3, p, ul/ol/li, table/tr/th/td, b, i), "
                                                "format pdf|docx|xlsx, theme classico|moderno|sobrio, must_contain (texts that must appear, "
                                                "checked again)."),
            parameters={"type": "object", "properties": {
                "title": S, "html": {"type": "string", "description": "content in simple HTML"},
                "format": {"type": "string", "enum": list(FORMATS)}, "theme": {"type": "string", "enum": list(THEMES)},
                "must_contain": {"type": "array", "items": S}}, "required": ["title", "html"]},
            handler=_create, title="Create document", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Documents", "primary": 1}),
    MCPTool(name="document_list", description="The documents created recently.",
            parameters={"type": "object", "properties": {}}, handler=_list, title="Documents created",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Documents", "primary": 2}),
    MCPTool(name="document_send", description="Send again the file of a created document.",
            parameters={"type": "object", "properties": {"document": S}, "required": ["document"]}, handler=_send,
            title="Send document", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Documents"}),
    MCPTool(name="document_delete", description="Delete a created document (and its file).",
            parameters={"type": "object", "properties": {"document": S}, "required": ["document"]},
            handler=lambda document: docs.delete(document), title="Delete created document", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Documents"}),
], prefix="document_")

transfer = Transfer("calliope", kit.hub, sections=[
    StoreSection("documenti", "Documents created", kit.store, ["document"], icon="file",
                 title=lambda r: r["data"].get("title", ""), file_fields=["blob_id"]),
])
app.include_router(transfer.router())
kit.capabilities(transfer.capabilities)
kit.webui(icon="file", color="indigo", description="Real PDF, Word and Excel files, checked before delivery.",
          pages=[page("documenti", "Documents created", element="calliope-docs", icon="file", order=200,
                      help="The documents the assistant created for you (PDF, Word, Excel): download them or create a new one. You can also ask in chat: «make me a PDF with…».")])
kit.finish()
