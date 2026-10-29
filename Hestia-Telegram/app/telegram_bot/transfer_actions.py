"""Esporta e importa from Telegram (dossier docs/work/2026-10-24-tutto-brainstorm-cindy F; format and module contract:
docs/work/2026-10-20-import-export).

Like the WebUI page, the client orchestrates: every module exports and imports only its own data through Hub
``/route/<svc>/api/transfer/*``; Telegram builds or reads the same ``.hestia`` file (gzip JSON).

- «Esporta i dati»: every module that has export, without photos (Telegram file limits) → sent as a document.
- «Importa dati»: asks for the ``.hestia`` file, shows the preview (dry run, always first), then «Importa»
  (mode *unisci*: adds and updates, never deletes). Before writing, the current data of the same modules is sent
  back as a document «prima dell'importazione»: importing that file restores the previous state.
The file waits in memory for 30 minutes at most (personal data: never written to disk here).
- «Ripristina un backup» / «Annulla ripristino»: the owner's own restore of a Google Drive backup (Archive
  ``/api/backup/restore`` · ``/undo``); there is deliberately no assistant tool for it.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import requests

from telegram_bot import catalog, core, ui
from telegram_bot.render import Action, Rendered

logger = logging.getLogger("hestia_telegram.transfer")

FORMAT = 1
_TTL = 1800
_pending: dict[str, dict] = {}


class TransferError(Exception):
    user_facing = True


def modules() -> dict[str, dict]:
    """Modules advertising the ``transfer`` capability on Hub."""
    try:
        resp = requests.get(f"{core.HUB_API_URL}/registry/services", timeout=10)
        services = (resp.json() or {}).get("services") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=transfer_registry_failed error=%s", exc)
        raise TransferError("Non riesco a vedere i moduli adesso, riprova tra poco.") from exc
    return {s["name"]: s["capabilities"]["transfer"] for s in services
            if isinstance(s, dict) and isinstance((s.get("capabilities") or {}).get("transfer"), dict)}


def build(owners: list[str]) -> dict:
    data = {"hestia": "transfer", "format": FORMAT, "exported_at": datetime.now(timezone.utc).isoformat(),
            "since": None, "include_files": False, "modules": {}, "files": {}}
    for owner in owners:
        ok, out = catalog.route(owner, "api/transfer/export", "POST",
                                body={"sections": None, "since": None, "include_files": False}, timeout=120)
        if ok and isinstance(out, dict):
            data["modules"][owner] = out
        else:
            logger.warning("[🔄] event=transfer_export_module_failed module=%s fallback=skip", owner)
    return data


def encode(data: dict) -> bytes:
    return gzip.compress(json.dumps(data, ensure_ascii=False).encode())


def decode(raw: bytes) -> dict:
    try:
        data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    except (OSError, ValueError) as exc:
        raise TransferError("Questo file non è un file di Hestia.") from exc
    if not isinstance(data, dict) or data.get("hestia") != "transfer" or (data.get("format") or 1) > FORMAT:
        raise TransferError("Questo file non è di Hestia, o è di una versione più recente.")
    return data


def _count(data: dict) -> int:
    return sum(len(s.get("records") or []) for m in data["modules"].values() for s in (m.get("sections") or {}).values())


def run(data: dict, *, dry_run: bool, available: dict) -> dict[str, dict]:
    reports = {}
    for owner, block in data["modules"].items():
        if owner not in available:
            reports[owner] = {"missing": True}
            continue
        ok, rep = catalog.route(owner, "api/transfer/import", "POST", body={
            "data": block, "mode": "merge", "dry_run": dry_run, "sections": None, "files_map": {}}, timeout=120)
        reports[owner] = rep if ok and isinstance(rep, dict) else {"error": True}
    return reports


def _lines(reports: dict, labels: dict) -> list[str]:
    lines = []
    for owner, rep in reports.items():
        name = labels.get(owner) or owner.title()
        if rep.get("missing"):
            lines.append(ui.item(name, ["non presente qui, saltato"]))
            continue
        if rep.get("error"):
            lines.append(ui.item(name, ["non risponde"]))
            continue
        totals = {k: 0 for k in ("added", "updated", "unchanged", "skipped", "problems")}
        for r in (rep.get("sections") or {}).values():
            for k in totals:
                totals[k] += int(r.get(k) or 0)
        parts = [f"{totals[k]} {label}" for k, label in (("added", "nuovi"), ("updated", "aggiornati"),
                                                         ("skipped", "ignorati"), ("problems", "problemi"))
                 if totals[k]]
        lines.append(ui.item(name, parts or ["nessuna modifica"]))
    return lines


def _labels(available: dict) -> dict:
    return {k: str(v.get("label") or "") for k, v in available.items() if isinstance(v, dict)}


# ── tools ───────────────────────────────────────────────────────────────────
def esporta(chat_id, args):
    available = modules()
    if not available:
        raise TransferError("Nessun modulo ha dati da esportare adesso.")
    data = build(sorted(available))
    name = f"hestia-{datetime.now().strftime('%Y-%m-%d')}.hestia"
    logger.info("event=telegram_transfer_export modules=%d records=%d", len(data["modules"]), _count(data))
    return Rendered(ui.card("Dati esportati", [
        f"{_count(data)} elementi da {len(data['modules'])} aree, senza foto.",
        ui.note("Il file contiene dati personali: tienilo per te. Per riportarli: «Importa dati».")]),
        document=(name, encode(data)))


def importa(chat_id, args):
    f = args.get("file") or {}
    raw = base64.b64decode(f.get("data_b64") or "") if isinstance(f, dict) else b""
    if not raw:
        raise TransferError("Mandami il file .hestia.")
    data = decode(raw)
    available = modules()
    reports = run(data, dry_run=True, available=available)
    for token, p in list(_pending.items()):
        if p["at"] < time.time() - _TTL:
            _pending.pop(token, None)
    token = uuid.uuid4().hex[:10]
    _pending[token] = {"data": data, "chat_id": str(chat_id), "at": time.time()}
    logger.info("event=telegram_transfer_preview modules=%d records=%d", len(data["modules"]), _count(data))
    return Rendered(ui.card("Anteprima dell'importazione", [
        *_lines(reports, _labels(available)),
        ui.note("Unisci: aggiunge e aggiorna, non elimina nulla. Prima ti mando una copia di come è adesso.")],
        subtitle=f"file del {str(data.get('exported_at') or '')[:10]}"),
        actions=[Action("Importa", "importa_conferma", {"token": token}, style="primary"),
                 Action("Annulla", "importa_annulla", {"token": token})])


def importa_conferma(chat_id, args):
    p = _pending.pop(str(args.get("token") or ""), None)
    if not p or p["chat_id"] != str(chat_id):
        raise TransferError("Questa anteprima è scaduta: mandami di nuovo il file.")
    available = modules()
    owners = [o for o in p["data"]["modules"] if o in available]
    before = build(owners)
    reports = run(p["data"], dry_run=False, available=available)
    logger.info("event=telegram_transfer_import modules=%d", len(owners))
    return Rendered(ui.outcome("Dati importati") + "\n" + "\n".join(_lines(reports, _labels(available))) + "\n"
                    + ui.note("Il file qui sotto è com'era prima: importalo per tornare indietro."),
                    document=(f"hestia-prima-{datetime.now().strftime('%Y-%m-%d-%H%M')}.hestia", encode(before)))


def importa_annulla(chat_id, args):
    _pending.pop(str(args.get("token") or ""), None)
    return Rendered(ui.outcome("Importazione annullata"))


# ── restore a Drive backup (owner only: no assistant tool restores) ───────────
def ripristina(chat_id, args):
    ok, hist = catalog.route("archive", "api/backup/list", timeout=30)
    items = (hist or {}).get("items") or [] if ok and isinstance(hist, dict) else []
    if not ok:
        raise TransferError("Non riesco a leggere i backup adesso, riprova tra poco.")
    if not items:
        return Rendered(ui.card("Ripristina un backup", [ui.note("Nessun backup su Google Drive.")]))
    lines, actions = [], []
    for b in items[:6]:
        when = str(b.get("created_at") or "")[:16].replace("T", " ")
        meta = [f"{int(b.get('size') or 0) / 1048576:.0f} MB"] + (["verificato"] if b.get("verified_at") else [])
        lines.append(ui.item(when, meta))
        actions.append(Action(f"Ripristina {when[:10]}", "ripristina_conferma", {"file_id": str(b["id"])},
                              style="danger"))
    return Rendered(ui.card("Ripristina un backup", [*lines, ui.note(
        "Tutti i dati tornano come in quel momento; quelli di adesso si possono riavere con «Annulla ripristino».")]),
        actions=actions)


def ripristina_conferma(chat_id, args):
    ok, out = catalog.route("archive", "api/backup/restore", "POST",
                            body={"file_id": str(args.get("file_id") or ""), "confirm": True}, timeout=30)
    if not ok:
        detail = (out or {}).get("detail") if isinstance(out, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else None
        raise TransferError(f"Ripristino non avviato: {message}." if message else "Ripristino non avviato, riprova.")
    logger.info("event=telegram_backup_restore_started")
    return Rendered(ui.outcome("Ripristino avviato") + "\n" + ui.note(
        "Dura qualche minuto: ti avviso quando ha finito."),
        actions=[Action("Stato dei backup", "backup_status"), Action("Annulla ripristino", "ripristina_annulla",
                                                                     style="danger")])


def ripristina_annulla(chat_id, args):
    ok, out = catalog.route("archive", "api/backup/undo", "POST", body={"confirm": True}, timeout=30)
    if not ok:
        raise TransferError("Non c'è un ripristino da annullare." if "nothing_to_undo" in str(out)
                            else "Non riesco ad annullare adesso, riprova.")
    return Rendered(ui.outcome("Torno ai dati di prima del ripristino"))


def tools() -> list[catalog.Tool]:
    T = catalog.Tool
    return [
        T("esporta", "Esporta i dati", "Un file con i tuoi dati e le impostazioni, da portare su un altro Hestia",
          group="sistema", hints={"section": "Dati e backup"}, handler=esporta),
        T("importa", "Importa dati", "Riporta i dati da un file .hestia (prima vedi l'anteprima)", group="sistema",
          hints={"section": "Dati e backup"},
          schema={"type": "object", "required": ["file"], "properties": {"file": {
              "type": "string", "contentMediaType": "application/octet-stream", "title": "Il file .hestia"}}},
          handler=importa),
        T("importa_conferma", "Conferma importazione", "", group="sistema", hints={"section": "interno"},
          schema={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
          writes=True, handler=importa_conferma),
        T("importa_annulla", "Annulla importazione", "", group="sistema", hints={"section": "interno"},
          schema={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
          handler=importa_annulla),
        T("ripristina", "Ripristina un backup", "Riporta tutti i dati a un backup su Google Drive", group="sistema",
          hints={"section": "Dati e backup"}, handler=ripristina),
        T("ripristina_conferma", "Ripristina", "", group="sistema", hints={"section": "interno"},
          schema={"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]},
          writes=True, destructive=True, handler=ripristina_conferma),
        T("ripristina_annulla", "Annulla ripristino", "Torna ai dati di prima dell'ultimo ripristino",
          group="sistema", hints={"section": "Dati e backup"}, writes=True, destructive=True,
          handler=ripristina_annulla),
    ]
